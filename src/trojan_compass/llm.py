"""Minimal stateless structured-output calls for OpenAI and Gemini.

One HTTPS request per call, no provider threads, tools or caches; OpenAI uses
``store=false``. Failures raise ``LLMFailure`` without provider text so nothing
sensitive is chained into logs.
"""

import json
import os
import re
from collections.abc import Sequence
from typing import Protocol, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from trojan_compass.extraction import ProviderResponse, strict_schema
from trojan_compass.failures import FailureReason, provider_reason
from trojan_compass.gemini import GeminiResponse

Model = TypeVar("Model", bound=BaseModel)


class LLMFailure(Exception):
    """Sanitized provider/schema failure; only a closed reason enum is retained."""

    def __init__(self, reason: FailureReason = FailureReason.INVALID_OUTPUT) -> None:
        super().__init__()
        self.reason = reason


class StructuredLLM(Protocol):
    async def complete(self, system: str, user: str, schema: type[Model]) -> Model: ...


class OpenAIStructuredLLM:
    def __init__(
        self,
        api_key: str,
        model: str,
        transport: httpx.AsyncBaseTransport | None = None,
        *,
        max_output_tokens: int = 2048,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._transport = transport
        self._max_output_tokens = max_output_tokens

    async def complete(self, system: str, user: str, schema: type[Model]) -> Model:
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(25.0), transport=self._transport, trust_env=False
            ) as client:
                response = await client.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    json={
                        "model": self._model,
                        "store": False,
                        "max_completion_tokens": self._max_output_tokens,
                        "messages": [
                            {"role": "system", "content": system},
                            {"role": "user", "content": user},
                        ],
                        "response_format": {
                            "type": "json_schema",
                            "json_schema": {
                                "name": schema.__name__.casefold(),
                                "strict": True,
                                "schema": strict_schema(schema.model_json_schema()),
                            },
                        },
                    },
                )
                response.raise_for_status()
                parsed = ProviderResponse.model_validate_json(response.content)
            choice = parsed.choices[0]
            if choice.message.refusal:
                raise LLMFailure(FailureReason.REFUSAL)
            if choice.finish_reason == "length":
                raise LLMFailure(FailureReason.TRUNCATED)
            if choice.finish_reason != "stop":
                raise LLMFailure(FailureReason.SCHEMA)
            return schema.model_validate_json(choice.message.content or "")
        except httpx.HTTPStatusError as error:
            raise LLMFailure(provider_reason(error)) from None
        except httpx.TimeoutException:
            raise LLMFailure(FailureReason.TIMEOUT) from None
        except httpx.RequestError:
            raise LLMFailure(FailureReason.NETWORK) from None
        except (ValidationError, ValueError, IndexError):
            raise LLMFailure(FailureReason.SCHEMA) from None
        except LLMFailure as error:
            raise LLMFailure(error.reason) from None
        except Exception:
            raise LLMFailure() from None


class GeminiStructuredLLM:
    def __init__(
        self,
        api_key: str,
        model: str,
        transport: httpx.AsyncBaseTransport | None = None,
        *,
        max_output_tokens: int = 2048,
    ) -> None:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", model):
            raise ValueError("GEMINI_MODEL must be a plain model ID")
        self._api_key = api_key
        self._model = model
        self._transport = transport
        self._max_output_tokens = max_output_tokens

    async def complete(self, system: str, user: str, schema: type[Model]) -> Model:
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(25.0), transport=self._transport, trust_env=False
            ) as client:
                response = await client.post(
                    "https://generativelanguage.googleapis.com/v1beta/models/"
                    f"{self._model}:generateContent",
                    headers={"x-goog-api-key": self._api_key},
                    json={
                        "systemInstruction": {"parts": [{"text": system}]},
                        "contents": [{"role": "user", "parts": [{"text": user}]}],
                        "generationConfig": {
                            "candidateCount": 1,
                            "maxOutputTokens": self._max_output_tokens,
                            "responseMimeType": "application/json",
                            "responseJsonSchema": schema.model_json_schema(),
                        },
                    },
                )
                response.raise_for_status()
                parsed = GeminiResponse.model_validate_json(response.content)
            candidate = parsed.candidates[0]
            if candidate.finish_reason == "MAX_TOKENS":
                raise LLMFailure(FailureReason.TRUNCATED)
            if candidate.finish_reason != "STOP":
                raise LLMFailure(FailureReason.REFUSAL)
            text = "".join(p.text or "" for p in candidate.content.parts if not p.thought)
            return schema.model_validate_json(text)
        except httpx.HTTPStatusError as error:
            raise LLMFailure(provider_reason(error)) from None
        except httpx.TimeoutException:
            raise LLMFailure(FailureReason.TIMEOUT) from None
        except httpx.RequestError:
            raise LLMFailure(FailureReason.NETWORK) from None
        except (ValidationError, ValueError, IndexError):
            raise LLMFailure(FailureReason.SCHEMA) from None
        except LLMFailure as error:
            raise LLMFailure(error.reason) from None
        except Exception:
            raise LLMFailure() from None


def configured_llm(*, max_output_tokens: int = 2048) -> StructuredLLM:
    """Same server-only provider settings as extraction."""
    provider = os.environ.get("LLM_PROVIDER", "openai")
    if provider == "ollama":
        from trojan_compass.ollama import configured_ollama

        return configured_ollama(max_output_tokens=max_output_tokens)
    if provider not in {"openai", "gemini"}:
        raise ValueError("LLM_PROVIDER must be openai, gemini or ollama")
    if provider == "gemini":
        return GeminiStructuredLLM(
            os.environ["GEMINI_API_KEY"],
            os.environ["GEMINI_MODEL"],
            max_output_tokens=max_output_tokens,
        )
    return OpenAIStructuredLLM(
        os.environ["OPENAI_API_KEY"],
        os.environ["OPENAI_MODEL"],
        max_output_tokens=max_output_tokens,
    )


def conversation_json(messages: Sequence[object]) -> str:
    return json.dumps(
        [m.model_dump() if isinstance(m, BaseModel) else m for m in messages],
        ensure_ascii=False,
    )
