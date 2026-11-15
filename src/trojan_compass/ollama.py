"""Native loopback Ollama adapter: JSON schema, no cloud fallback or conversation handles."""

import os
import re
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from trojan_compass.contracts import ChatMessage, RetrievalContext
from trojan_compass.extraction import (
    EXTRACTION_PROMPT,
    ExtractionFailure,
    grounded_context,
    indexed_conversation,
)
from trojan_compass.failures import FailureReason, provider_reason
from trojan_compass.llm import LLMFailure, Model


class LocalMessage(BaseModel):
    model_config = ConfigDict(extra="ignore")
    role: str
    content: str


class LocalResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")
    message: LocalMessage
    done: bool
    done_reason: str


class LocalModelInfo(BaseModel):
    model_config = ConfigDict(extra="ignore")
    remote_model: str | None = None
    remote_host: str | None = None
    model_info: dict[str, object] = Field(default_factory=dict)


class OllamaStructuredLLM:
    """No API keys or disk I/O; local daemon settings/OS retention are separately documented."""

    def __init__(
        self,
        model: str,
        base_url: str = "http://127.0.0.1:11434",
        *,
        context_length: int = 32768,
        max_output_tokens: int = 4096,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        parts = urlsplit(base_url)
        if (
            parts.scheme != "http"
            or parts.hostname not in {"127.0.0.1", "localhost", "::1"}
            or parts.username
            or parts.password
            or parts.path not in {"", "/"}
            or parts.query
            or parts.fragment
        ):
            raise ValueError("OLLAMA_BASE_URL must be a plain loopback HTTP endpoint")
        if (
            not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_./:-]{0,127}", model)
            or "cloud" in model.casefold()
        ):
            raise ValueError("OLLAMA_MODEL must name an installed local model, never a cloud tag")
        if not 4096 <= context_length <= 65536 or not 1 <= max_output_tokens <= 8192:
            raise ValueError("Invalid local context or output budget")
        host = "[::1]" if parts.hostname == "::1" else "127.0.0.1"
        self._endpoint = f"http://{host}:{parts.port or 11434}/api/chat"
        self._model = model
        self._context_length = context_length
        self._max_output_tokens = min(max_output_tokens, 4096)
        self._transport = transport

    async def complete(self, system: str, user: str, schema: type[Model]) -> Model:
        # For the supported Qwen byte-level tokenizer this upper-bounds input
        # tokens conservatively, with additional room for the chat template. Fail
        # explicitly instead of letting Ollama discard earlier corrections.
        budget = (
            len(system.encode("utf-8")) + len(user.encode("utf-8")) + 1024 + self._max_output_tokens
        )
        if budget > self._context_length:
            raise LLMFailure(FailureReason.LOCAL_CONTEXT)
        # The configured window is a ceiling, not a mandatory KV allocation.
        # Small turns should not allocate the same 32K window as a long document.
        requested_context = min(self._context_length, max(4096, ((budget + 1023) // 1024) * 1024))
        payload: dict[str, object] = {
            "model": self._model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "format": schema.model_json_schema(),
            "stream": False,
            # Unload after the call so this application does not request retained
            # cross-request KV/prefix state. This trades latency for isolation.
            "keep_alive": 0,
            "options": {
                "temperature": 0,
                "num_ctx": requested_context,
                "num_predict": self._max_output_tokens,
            },
        }
        if self._model.split("/")[-1].startswith("qwen3:"):
            payload["think"] = False
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(90, connect=3),
                trust_env=False,
                follow_redirects=False,
                transport=self._transport,
            ) as client:
                # Check public model metadata before transmitting any conversation.
                # A local-looking alias can still point to a cloud model in Ollama.
                model_response = await client.post(
                    self._endpoint.removesuffix("chat") + "show", json={"model": self._model}
                )
                model_response.raise_for_status()
                model = LocalModelInfo.model_validate_json(model_response.content)
                if model.remote_host or model.remote_model:
                    raise LLMFailure(FailureReason.CONFIGURATION)
                windows = [
                    value
                    for key, value in model.model_info.items()
                    if key.endswith(".context_length") and isinstance(value, int)
                ]
                if windows and requested_context > min(windows):
                    raise LLMFailure(FailureReason.LOCAL_CONTEXT)
                response = await client.post(self._endpoint, json=payload)
                response.raise_for_status()
                parsed = LocalResponse.model_validate_json(response.content)
            if not parsed.done or parsed.done_reason == "length":
                raise LLMFailure(FailureReason.TRUNCATED)
            if parsed.done_reason != "stop" or parsed.message.role != "assistant":
                raise LLMFailure(FailureReason.SCHEMA)
            return schema.model_validate_json(parsed.message.content)
        except httpx.HTTPStatusError as error:
            raise LLMFailure(provider_reason(error)) from None
        except httpx.TimeoutException:
            raise LLMFailure(FailureReason.TIMEOUT) from None
        except httpx.RequestError:
            raise LLMFailure(FailureReason.NETWORK) from None
        except (ValidationError, ValueError):
            raise LLMFailure(FailureReason.SCHEMA) from None
        except LLMFailure as error:
            raise LLMFailure(error.reason) from None
        except Exception:
            raise LLMFailure() from None


def configured_ollama(*, max_output_tokens: int = 4096) -> OllamaStructuredLLM:
    return OllamaStructuredLLM(
        model=os.getenv("OLLAMA_MODEL", "qwen3:4b"),
        base_url=os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434"),
        context_length=int(os.getenv("OLLAMA_CONTEXT_LENGTH", "32768")),
        max_output_tokens=max_output_tokens,
    )


class OllamaContextExtractor:
    """Compatibility with the shared extractor interface; AI-led chat uses the same provider."""

    async def extract(self, messages: list[ChatMessage]) -> RetrievalContext:
        try:
            context = await configured_ollama().complete(
                EXTRACTION_PROMPT, indexed_conversation(messages), RetrievalContext
            )
            return grounded_context(context.model_dump_json(), messages)
        except LLMFailure as error:
            raise ExtractionFailure(error.reason) from None
