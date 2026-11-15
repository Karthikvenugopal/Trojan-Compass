"""Stateless Gemini Developer API extraction; no threads, tools or explicit caches."""

import re

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from trojan_compass.contracts import ChatMessage, RetrievalContext
from trojan_compass.extraction import (
    REPAIRABLE,
    ExtractionFailure,
    extraction_prompt,
    grounded_context,
    indexed_conversation,
)
from trojan_compass.failures import FailureReason, provider_reason


class GeminiPart(BaseModel):
    model_config = ConfigDict(extra="ignore")
    text: str | None = None
    thought: bool = False


class GeminiContent(BaseModel):
    model_config = ConfigDict(extra="ignore")
    parts: list[GeminiPart]


class GeminiCandidate(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)
    content: GeminiContent
    finish_reason: str = Field(alias="finishReason")


class GeminiFeedback(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)
    block_reason: str | None = Field(default=None, alias="blockReason")


class GeminiResponse(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)
    candidates: list[GeminiCandidate] = Field(default_factory=list)
    prompt_feedback: GeminiFeedback | None = Field(default=None, alias="promptFeedback")


class GeminiContextExtractor:
    """One generateContent call. Provider retention is governed by Google's account terms.

    The caller chooses a model supporting generateContent and structured JSON output.
    Pydantic validates the full schema locally even where the provider's constrained
    decoder does not enforce a JSON Schema keyword such as maxLength.
    """

    def __init__(
        self,
        api_key: str,
        model: str,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        # A model ID is a path segment, never a URL or arbitrary request path.
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", model):
            raise ValueError("GEMINI_MODEL must be a plain model ID, without a models/ prefix")
        self._api_key = api_key
        self._model = model
        self._transport = transport

    async def extract(self, messages: list[ChatMessage]) -> RetrievalContext:
        repair: FailureReason | None = None
        for attempt in range(2):
            try:
                async with httpx.AsyncClient(
                    timeout=httpx.Timeout(25.0),
                    transport=self._transport,
                    trust_env=False,
                ) as client:
                    response = await client.post(
                        f"https://generativelanguage.googleapis.com/v1beta/models/"
                        f"{self._model}:generateContent",
                        # Keep the key out of query strings, access logs and error URLs.
                        headers={"x-goog-api-key": self._api_key},
                        json={
                            "systemInstruction": {"parts": [{"text": extraction_prompt(repair)}]},
                            "contents": [
                                {
                                    "role": "user",
                                    "parts": [{"text": indexed_conversation(messages)}],
                                }
                            ],
                            "generationConfig": {
                                "candidateCount": 1,
                                "maxOutputTokens": 8192 if attempt else 4096,
                                "responseMimeType": "application/json",
                                "responseJsonSchema": RetrievalContext.model_json_schema(),
                            },
                        },
                    )
                    response.raise_for_status()
                    parsed = GeminiResponse.model_validate_json(response.content)
                if parsed.prompt_feedback and parsed.prompt_feedback.block_reason:
                    raise ExtractionFailure(FailureReason.REFUSAL)
                if len(parsed.candidates) != 1:
                    raise ExtractionFailure()
                candidate = parsed.candidates[0]
                if candidate.finish_reason == "MAX_TOKENS":
                    raise ExtractionFailure(FailureReason.TRUNCATED)
                if candidate.finish_reason != "STOP":
                    raise ExtractionFailure(FailureReason.REFUSAL)
                # Thought text/signatures are never returned, reused or treated as facts.
                parts = [part for part in candidate.content.parts if not part.thought]
                if not parts or any(part.text is None for part in parts):
                    raise ExtractionFailure()
                content = "".join(part.text or "" for part in parts)
                return grounded_context(content, messages)
            except httpx.HTTPStatusError as error:
                raise ExtractionFailure(provider_reason(error)) from None
            except httpx.TimeoutException:
                raise ExtractionFailure(FailureReason.TIMEOUT) from None
            except httpx.RequestError:
                raise ExtractionFailure(FailureReason.NETWORK) from None
            except (ValidationError, ValueError, ExtractionFailure) as error:
                reason = (
                    error.reason if isinstance(error, ExtractionFailure) else FailureReason.SCHEMA
                )
                if attempt == 0 and reason in REPAIRABLE:
                    repair = reason
                    continue
                raise ExtractionFailure(reason) from None
            except Exception:
                # Do not leak or chain provider bodies, credentials, prompts or output.
                raise ExtractionFailure() from None
        raise ExtractionFailure()
