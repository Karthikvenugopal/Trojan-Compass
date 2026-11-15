"""Production intake choices work without a provider; unsupported text never disappears."""

import httpx
import pytest
from fastapi.testclient import TestClient

from trojan_compass.api import create_app
from trojan_compass.contracts import (
    ChatMessage,
    RecommendationRequest,
    RecommendationResult,
    RetrievalContext,
)
from trojan_compass.controlled_intake import ControlledIntakeParser
from trojan_compass.extraction import ExtractionFailure, OpenAIContextExtractor
from trojan_compass.failures import FailureReason


class UnavailableExtractor:
    async def extract(self, messages: list[ChatMessage]) -> RetrievalContext:
        raise ExtractionFailure(FailureReason.AUTH)


class RecordingRecommendations:
    def __init__(self) -> None:
        self.requests: list[RecommendationRequest] = []

    async def recommend(self, request: RecommendationRequest) -> RecommendationResult:
        self.requests.append(request)
        return RecommendationResult()


@pytest.mark.parametrize(
    "direction,detail",
    [
        ("Understanding people", "Psychology or behavior"),
        ("Building things", "Engineering or physical systems"),
        ("Business or public service", "Business or entrepreneurship"),
        ("Arts or storytelling", "Film or storytelling"),
    ],
)
def test_guided_journey_has_no_provider_dependency(direction: str, detail: str) -> None:
    recommendations = RecordingRecommendations()
    app = create_app(
        mode="campus",
        extractor=UnavailableExtractor(),
        recommendations=recommendations,
        local_intake=ControlledIntakeParser(),
    )
    messages: list[dict[str, str]] = []
    with TestClient(app) as client:
        for answer in [
            "I'm not sure where to start.",
            direction,
            detail,
            "Undergraduate",
            "I haven't chosen a program",
            "I have no experience",
            "None",
        ]:
            messages.append({"role": "user", "content": answer})
            response = client.post("/api/chat", json={"messages": messages})
            assert response.status_code == 200, response.text
            if answer != "None":
                assert not recommendations.requests
                assert not response.json()["recommendations"]
            messages.append({"role": "assistant", "content": response.json()["message"]})
        assert len(recommendations.requests) == 1
        context = recommendations.requests[0].context
        assert not context.skills
        assert not context.completed_courses
        assert not context.experiences
        # Reusing the app carries no student context to another request.
        fresh = client.post("/api/chat", json={"messages": [{"role": "user", "content": "Hi"}]})
        assert fresh.status_code == 200
        assert len(recommendations.requests) == 1


def test_freeform_correction_cannot_be_dropped_to_take_local_path() -> None:
    parser = ControlledIntakeParser()
    assert (
        parser.parse([ChatMessage(role="user", content="I like art but cannot attend evenings")])
        is None
    )
    assert (
        parser.parse(
            [
                ChatMessage(role="assistant", content="Building things"),
                ChatMessage(role="user", content="Building things"),
            ]
        )
        is None
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,code,reason",
    [
        (401, "secret", FailureReason.AUTH),
        (429, "insufficient_quota", FailureReason.QUOTA),
        (429, "rate_limit", FailureReason.RATE_LIMIT),
        (503, "secret", FailureReason.PROVIDER),
    ],
)
async def test_provider_failure_is_actionable_without_raw_content(
    status: int, code: str, reason: FailureReason
) -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(status, json={"error": {"code": code, "message": "PRIVATE"}})
    )
    extractor = OpenAIContextExtractor("synthetic-key", "synthetic-model", transport=transport)
    with pytest.raises(ExtractionFailure) as caught:
        await extractor.extract([ChatMessage(role="user", content="Synthetic request")])
    assert caught.value.reason == reason
    assert "PRIVATE" not in str(caught.value)


def test_configured_application_enables_controlled_intake(monkeypatch: pytest.MonkeyPatch) -> None:
    from trojan_compass.composition import RuntimeSettings, create_configured_app, seed_repository

    monkeypatch.setattr(
        "trojan_compass.composition.configured_extractor", lambda: UnavailableExtractor()
    )
    # Explicit assistant injection avoids configuring an unrelated external router in this test.
    from trojan_compass.assistant import CampusAssistant
    from trojan_compass.llm import LLMFailure, Model

    class UnavailableLLM:
        calls = 0

        async def complete(self, system: str, user: str, schema: type[Model]) -> Model:
            self.calls += 1
            raise LLMFailure()

    llm = UnavailableLLM()

    # No assistant call is necessary for the opening controlled choices.
    app = create_configured_app(
        RuntimeSettings(mode="campus"),
        graph=seed_repository(),
        assistant=CampusAssistant(llm, None, None),
    )
    with TestClient(app) as client:
        response = client.post("/api/chat", json={"messages": [{"role": "user", "content": "Hi"}]})
        assert response.status_code == 200
        assert not response.json()["recommendations"]

    assert llm.calls == 0


def test_http_error_exposes_only_safe_provider_category() -> None:
    with TestClient(
        create_app(
            mode="campus",
            extractor=UnavailableExtractor(),
            recommendations=RecordingRecommendations(),
        )
    ) as client:
        response = client.post(
            "/api/chat",
            json={"messages": [{"role": "user", "content": "Synthetic private sentence"}]},
        )
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "provider_authentication"
        assert "server credentials" in response.json()["error"]["message"]
        assert "Synthetic private sentence" not in response.text
        assert response.headers["cache-control"] == "no-store"
