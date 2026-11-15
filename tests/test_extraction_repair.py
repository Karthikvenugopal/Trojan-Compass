"""Synthetic provider mistakes are repaired only with verifiable student evidence."""

import json
from typing import Any

import httpx
import pytest

from trojan_compass.contracts import ChatMessage, ContextExtractor
from trojan_compass.extraction import ExtractionFailure, OpenAIContextExtractor, grounded_context
from trojan_compass.failures import FailureReason
from trojan_compass.gemini import GeminiContextExtractor


def evidence(index: int, text: str) -> list[dict[str, object]]:
    return [{"message_index": index, "quote": text}]


def test_unique_student_quote_repairs_miscounted_index() -> None:
    messages = [
        ChatMessage(role="user", content="Hi"),
        ChatMessage(role="assistant", content="What do you study?"),
        ChatMessage(role="user", content="I study film"),
    ]
    context = grounded_context(
        json.dumps(
            {
                "program": {"value": "film", "evidence": evidence(1, "I study film")},
                "answers": [
                    {
                        "field": "work_experience",
                        "status": "not_answered",
                        "value": None,
                        "evidence": evidence(1, "What do you study?"),
                    }
                ],
            }
        ),
        messages,
    )
    assert context.program is not None
    assert context.program.evidence[0].message_index == 2
    assert context.answers[0].evidence == []


@pytest.mark.parametrize("quote", ["Only the assistant said this", "I ... know Python", "Invented"])
def test_repair_never_invents_student_evidence(quote: str) -> None:
    messages = [
        ChatMessage(role="user", content="I do not know Python"),
        ChatMessage(role="assistant", content="Only the assistant said this"),
    ]
    with pytest.raises(ExtractionFailure) as caught:
        grounded_context(
            json.dumps(
                {"skills": [{"name": "Python", "status": "known", "evidence": evidence(1, quote)}]}
            ),
            messages,
        )
    assert caught.value.reason == FailureReason.EVIDENCE


def test_ambiguous_repeated_quote_cannot_be_rebound() -> None:
    messages = [
        ChatMessage(role="user", content="I do not know"),
        ChatMessage(role="assistant", content="Another question"),
        ChatMessage(role="user", content="I do not know"),
    ]
    with pytest.raises(ExtractionFailure):
        grounded_context(
            json.dumps(
                {
                    "answers": [
                        {
                            "field": "program",
                            "status": "unknown",
                            "value": None,
                            "evidence": evidence(1, "I do not know"),
                        }
                    ]
                }
            ),
            messages,
        )


def test_duplicate_snapshot_fields_keep_latest_explicit_correction_and_constraints() -> None:
    messages = [
        ChatMessage(role="user", content="I know Python. No evenings."),
        ChatMessage(role="assistant", content="Anything else?"),
        ChatMessage(role="user", content="Correction: I am learning Python now."),
    ]
    skills = [
        {"name": "Python", "status": status, "evidence": evidence(index, text)}
        for status, index, text in [
            ("known", 0, "I know Python"),
            ("learning", 2, "I am learning Python now."),
        ]
    ]
    context = grounded_context(
        json.dumps(
            {
                "skills": skills,
                "constraints": {
                    "additional_preferences": [
                        {"value": "No evenings", "evidence": evidence(0, "No evenings.")}
                    ]
                },
            }
        ),
        messages,
    )
    assert len(context.skills) == 1
    assert context.skills[0].status == "learning"
    assert context.constraints.additional_preferences[0].value == "No evenings"


def test_same_turn_conflicting_statuses_are_rejected() -> None:
    messages = [ChatMessage(role="user", content="I am learning Python")]
    skills = [
        {"name": "Python", "status": status, "evidence": evidence(0, "I am learning Python")}
        for status in ["known", "learning"]
    ]
    with pytest.raises(ExtractionFailure) as caught:
        grounded_context(json.dumps({"skills": skills}), messages)
    assert caught.value.reason == FailureReason.CONFLICT


def response(provider: str, content: str) -> dict[str, Any]:
    if provider == "openai":
        return {"choices": [{"finish_reason": "stop", "message": {"content": content}}]}
    return {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": content}]}}]}


def provider_extractor(provider: str, transport: httpx.MockTransport) -> ContextExtractor:
    if provider == "openai":
        return OpenAIContextExtractor("synthetic", "synthetic", transport)
    return GeminiContextExtractor("synthetic", "synthetic", transport)


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["openai", "gemini"])
async def test_one_bounded_same_provider_repair_preserves_full_input(provider: str) -> None:
    messages = [ChatMessage(role="user", content="I study film. No evenings.")]
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        calls.append(payload)
        content = (
            "not json"
            if len(calls) == 1
            else json.dumps(
                {
                    "program": {"value": "film", "evidence": evidence(0, "I study film")},
                    "constraints": {
                        "additional_preferences": [
                            {"value": "No evenings", "evidence": evidence(0, "No evenings.")}
                        ]
                    },
                }
            )
        )
        return httpx.Response(200, json=response(provider, content))

    transport = httpx.MockTransport(handler)
    extractor = provider_extractor(provider, transport)
    context = await extractor.extract(messages)
    assert context.program is not None and context.program.value == "film"
    assert context.constraints.additional_preferences
    assert len(calls) == 2
    if provider == "openai":
        assert all(c["store"] is False for c in calls)
        assert calls[0]["messages"][1] == calls[1]["messages"][1]
        assert "Validation repair" in calls[1]["messages"][0]["content"]
    else:
        assert calls[0]["contents"] == calls[1]["contents"]
        assert "Validation repair" in calls[1]["systemInstruction"]["parts"][0]["text"]


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["openai", "gemini"])
async def test_bad_output_stops_after_two_attempts_with_safe_reason(provider: str) -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json=response(provider, '{"invented":"PRIVATE"}'))

    transport = httpx.MockTransport(handler)
    extractor = provider_extractor(provider, transport)
    with pytest.raises(ExtractionFailure) as caught:
        await extractor.extract([ChatMessage(role="user", content="Synthetic student request")])
    assert caught.value.reason == FailureReason.SCHEMA
    assert len(calls) == 2
    assert str(caught.value) == "" and caught.value.__suppress_context__


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["openai", "gemini"])
async def test_auth_errors_are_never_retried(provider: str) -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(401, json={"error": {"message": "PRIVATE"}})

    transport = httpx.MockTransport(handler)
    extractor = provider_extractor(provider, transport)
    with pytest.raises(ExtractionFailure) as caught:
        await extractor.extract([ChatMessage(role="user", content="Synthetic")])
    assert caught.value.reason == FailureReason.AUTH
    assert len(calls) == 1


def test_entering_freeform_answer_survives_invalid_first_extraction() -> None:
    from fastapi.testclient import TestClient

    from trojan_compass.api import create_app
    from trojan_compass.contracts import RecommendationRequest, RecommendationResult
    from trojan_compass.readiness import STAGE_QUESTION

    class MustNotRetrieve:
        async def recommend(self, request: RecommendationRequest) -> RecommendationResult:
            raise AssertionError("Intake is not complete")

    attempts = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(request)
        raw = (
            "invalid JSON"
            if len(attempts) == 1
            else json.dumps(
                {"interests": [{"value": "film", "evidence": evidence(1, "I like film")}]}
            )
        )
        return httpx.Response(200, json=response("openai", raw))

    app = create_app(
        mode="campus",
        recommendations=MustNotRetrieve(),
        extractor=OpenAIContextExtractor("synthetic", "synthetic", httpx.MockTransport(handler)),
    )
    with TestClient(app) as client:
        result = client.post(
            "/api/chat", json={"messages": [{"role": "user", "content": "I like film"}]}
        )
    assert result.status_code == 200
    assert result.json()["message"].startswith(STAGE_QUESTION)
    assert not result.json()["recommendations"]
    assert len(attempts) == 2
