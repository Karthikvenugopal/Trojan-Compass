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
from pydantic import BaseModel

from trojan_compass.extraction import ProviderResponse, strict_schema
from trojan_compass.gemini import GeminiResponse

Model = TypeVar("Model", bound=BaseModel)


class LLMFailure(Exception):
    """Sanitized provider/schema failure."""


class StructuredLLM(Protocol):
    async def complete(self, system: str, user: str, schema: type[Model]) -> Model: ...


class OpenAIStructuredLLM:
    def __init__(
        self, api_key: str, model: str, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._transport = transport

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
                        "max_completion_tokens": 2048,
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
            if choice.finish_reason != "stop" or choice.message.refusal:
                raise LLMFailure()
            return schema.model_validate_json(choice.message.content or "")
        except Exception:
            raise LLMFailure() from None


class GeminiStructuredLLM:
    def __init__(
        self, api_key: str, model: str, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", model):
            raise ValueError("GEMINI_MODEL must be a plain model ID")
        self._api_key = api_key
        self._model = model
        self._transport = transport

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
                            "maxOutputTokens": 2048,
                            "responseMimeType": "application/json",
                            "responseJsonSchema": schema.model_json_schema(),
                        },
                    },
                )
                response.raise_for_status()
                parsed = GeminiResponse.model_validate_json(response.content)
            candidate = parsed.candidates[0]
            if candidate.finish_reason != "STOP":
                raise LLMFailure()
            text = "".join(p.text or "" for p in candidate.content.parts if not p.thought)
            return schema.model_validate_json(text)
        except Exception:
            raise LLMFailure() from None


def configured_llm() -> StructuredLLM:
    """Same server-only provider settings as extraction."""
    if os.environ.get("LLM_PROVIDER", "openai") == "gemini":
        return GeminiStructuredLLM(os.environ["GEMINI_API_KEY"], os.environ["GEMINI_MODEL"])
    return OpenAIStructuredLLM(os.environ["OPENAI_API_KEY"], os.environ["OPENAI_MODEL"])


def conversation_json(messages: Sequence[object]) -> str:
    return json.dumps(
        [m.model_dump() if isinstance(m, BaseModel) else m for m in messages],
        ensure_ascii=False,
    )
