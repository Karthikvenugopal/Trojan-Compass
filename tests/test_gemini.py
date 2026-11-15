"""Synthetic Gemini responses; no live provider calls or credentials."""

import asyncio
import json
from typing import Any

import httpx
import pytest
from compact_checklist import create_configured_app
from fastapi.testclient import TestClient

from trojan_compass.api import configured_extractor
from trojan_compass.composition import RuntimeSettings
from trojan_compass.contracts import (
    ChatMessage,
    ChatResponse,
    RetrievalContext,
    Skill,
    StudentStatement,
    SupportedText,
    Target,
)
from trojan_compass.extraction import ExtractionFailure, OpenAIContextExtractor
from trojan_compass.gemini import GeminiContextExtractor


def provider_response(content: str, finish: str = "STOP") -> dict[str, Any]:
    return {"candidates": [{"finishReason": finish, "content": {"parts": [{"text": content}]}}]}


def quote(text: str, index: int = 0) -> StudentStatement:
    return StudentStatement(message_index=index, quote=text)


@pytest.mark.asyncio
async def test_full_conversation_corrections_schema_and_header_only_credentials() -> None:
    messages = [
        ChatMessage(role="user", content="I know Python"),
        ChatMessage(role="assistant", content="You could learn SQL"),
        ChatMessage(role="user", content="Correction: I am learning Python now."),
    ]
    context = RetrievalContext(
        skills=[
            Skill(
                name="Python",
                status="learning",
                evidence=[quote("I am learning Python now.", 2)],
            )
        ]
    )

    def respond(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "generativelanguage.googleapis.com"
        assert request.url.path.endswith("/gemini-test-model:generateContent")
        assert not request.url.query
        assert request.headers["x-goog-api-key"] == "synthetic-key"
        payload = json.loads(request.content)
        assert json.loads(payload["contents"][0]["parts"][0]["text"]) == [
            m.model_dump() for m in messages
        ]
        assert (
            payload["generationConfig"]["responseJsonSchema"]
            == RetrievalContext.model_json_schema()
        )
        assert "Assistant suggestions" in payload["systemInstruction"]["parts"][0]["text"]
        assert not {"tools", "cachedContent", "previousInteractionId", "store"}.intersection(
            payload
        )
        response = provider_response(context.model_dump_json())
        # Thought text must not be interpreted as extraction output or replayed.
        response["candidates"][0]["content"]["parts"].insert(
            0,
            {
                "text": "PRIVATE_THOUGHT",
                "thought": True,
            },
        )
        return httpx.Response(200, json=response)

    extractor = GeminiContextExtractor(
        "synthetic-key", "gemini-test-model", httpx.MockTransport(respond)
    )
    result = await extractor.extract(messages)
    assert result == context
    assert result.skill_status("Python") == "learning"
    assert result.skill_status("SQL") == "unknown"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind",
    [
        "blocked_prompt",
        "blocked_candidate",
        "truncated",
        "no_candidates",
        "empty_parts",
        "thoughts_only",
        "nontext",
        "invalid_json",
        "invalid_schema",
        "assistant_evidence",
        "invalid_quote",
        "http",
        "timeout",
    ],
)
async def test_failures_are_private_and_fail_closed(kind: str) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        if kind == "timeout":
            raise httpx.ReadTimeout("PRIVATE_SENTINEL", request=request)
        if kind == "http":
            return httpx.Response(429, text="PRIVATE_SENTINEL")
        payload = provider_response("{}")
        candidate = payload["candidates"][0]
        if kind == "blocked_prompt":
            payload["promptFeedback"] = {"blockReason": "SAFETY"}
        elif kind == "blocked_candidate":
            candidate["finishReason"] = "SAFETY"
        elif kind == "truncated":
            candidate["finishReason"] = "MAX_TOKENS"
        elif kind == "no_candidates":
            payload["candidates"] = []
        elif kind == "empty_parts":
            candidate["content"]["parts"] = []
        elif kind == "thoughts_only":
            candidate["content"]["parts"] = [{"text": "{}", "thought": True}]
        elif kind == "nontext":
            candidate["content"]["parts"] = [{"functionCall": {"name": "never_execute"}}]
        elif kind == "invalid_json":
            candidate["content"]["parts"] = [{"text": "PRIVATE_SENTINEL"}]
        elif kind == "invalid_schema":
            candidate["content"]["parts"] = [{"text": '{"unsupported": "PRIVATE_SENTINEL"}'}]
        elif kind in ("assistant_evidence", "invalid_quote"):
            context = RetrievalContext(
                skills=[
                    Skill(
                        name="Python",
                        evidence=[
                            quote(
                                "Try Python" if kind == "assistant_evidence" else "invented",
                                1 if kind == "assistant_evidence" else 0,
                            )
                        ],
                    )
                ]
            )
            candidate["content"]["parts"] = [{"text": context.model_dump_json()}]
        return httpx.Response(200, json=payload)

    extractor = GeminiContextExtractor(
        "synthetic-key", "gemini-test-model", httpx.MockTransport(respond)
    )
    with pytest.raises(ExtractionFailure) as exc:
        await extractor.extract(
            [
                ChatMessage(role="user", content="Help me"),
                ChatMessage(role="assistant", content="Try Python"),
                ChatMessage(role="user", content="Other ideas?"),
            ]
        )
    assert str(exc.value) == ""
    assert exc.value.__suppress_context__


@pytest.mark.parametrize(
    "model", ["models/gemini-test", "../gemini", "gemini?key=x", "", "a" * 129]
)
def test_model_is_a_path_segment_not_an_arbitrary_url(model: str) -> None:
    with pytest.raises(ValueError, match="plain model ID"):
        GeminiContextExtractor("synthetic-key", model)


def test_provider_selection_is_explicit_and_has_no_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-openai")
    monkeypatch.setenv("OPENAI_MODEL", "synthetic-model")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(ValueError, match="GEMINI_API_KEY"):
        configured_extractor()
    monkeypatch.setenv("GEMINI_API_KEY", "synthetic-gemini")
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    with pytest.raises(ValueError, match="GEMINI_MODEL"):
        configured_extractor()
    monkeypatch.setenv("GEMINI_MODEL", "gemini-test-model")
    assert isinstance(configured_extractor(), GeminiContextExtractor)
    monkeypatch.delenv("LLM_PROVIDER")
    assert isinstance(configured_extractor(), OpenAIContextExtractor)
    monkeypatch.setenv("LLM_PROVIDER", "unknown")
    with pytest.raises(ValueError, match="LLM_PROVIDER"):
        configured_extractor()


@pytest.mark.asyncio
async def test_concurrent_extraction_is_request_local() -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        messages = json.loads(payload["contents"][0]["parts"][0]["text"])
        context = RetrievalContext(
            interests=[
                SupportedText(
                    value=messages[-1]["content"],
                    evidence=[quote(messages[-1]["content"])],
                )
            ]
        )
        return httpx.Response(200, json=provider_response(context.model_dump_json()))

    extractor = GeminiContextExtractor(
        "synthetic-key", "gemini-test-model", httpx.MockTransport(respond)
    )
    initial_state = dict(vars(extractor))
    contexts = await asyncio.gather(
        *[
            extractor.extract([ChatMessage(role="user", content=value)])
            for value in ["robotics", "music", "design"]
        ]
    )
    assert [c.interests[0].value for c in contexts] == ["robotics", "music", "design"]
    assert vars(extractor) == initial_state


def test_gemini_through_real_seed_engine_and_http_api(caplog: pytest.LogCaptureFixture) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        context = RetrievalContext(
            target=Target(
                kind="role", name="Software developer", evidence=[quote("Software developer")]
            ),
            skills=[
                Skill(
                    name="Computer programming",
                    status="not_yet_learned",
                    evidence=[quote("I haven't learned Computer programming yet")],
                )
            ],
        )
        return httpx.Response(200, json=provider_response(context.model_dump_json()))

    extractor = GeminiContextExtractor(
        "synthetic-key", "gemini-test-model", httpx.MockTransport(respond)
    )
    app = create_configured_app(RuntimeSettings(mode="campus"), extractor=extractor)
    with TestClient(app) as client:
        response = client.post(
            "/api/chat",
            json={
                "messages": [
                    {
                        "role": "user",
                        "content": (
                            "I want to be a Software developer. "
                            "I haven't learned Computer programming yet. "
                            "PRIVATE_SENTINEL"
                        ),
                    }
                ]
            },
        )
    assert response.status_code == 200
    result = ChatResponse.model_validate(response.json())
    assert any(r.id == "usc-course-csci-103l" for r in result.recommendations)
    assert all(r.sources and r.evidence_path for r in result.recommendations)
    assert "PRIVATE_SENTINEL" not in caplog.text
    assert response.headers["cache-control"] == "no-store"
