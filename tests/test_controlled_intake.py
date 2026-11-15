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


@pytest.mark.parametrize("program", ["CS", "Computer Science", "I haven't chosen a program"])
@pytest.mark.parametrize(
    "direction,detail",
    [
        ("Understanding people", "Psychology or behavior"),
        ("Building things", "Engineering or physical systems"),
        ("Business or public service", "Business or entrepreneurship"),
        ("Arts or storytelling", "Film or storytelling"),
    ],
)
def test_guided_journey_has_no_provider_dependency(
    direction: str, detail: str, program: str
) -> None:
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
            program,
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


def test_literal_program_answer_preserves_compound_constraints_on_llm_path() -> None:
    from trojan_compass.readiness import PROGRAM_QUESTION

    messages = [
        ChatMessage(role="user", content="Hi"),
        ChatMessage(role="assistant", content=PROGRAM_QUESTION),
        ChatMessage(role="user", content="CS, but only evening courses"),
    ]
    assert ControlledIntakeParser().parse(messages) is None


def test_explicit_course_picker_confirmation_needs_no_llm_and_proves_no_mastery() -> None:
    from trojan_compass.readiness import COURSES_QUESTION

    messages = [
        ChatMessage(role="user", content="Hi"),
        ChatMessage(role="assistant", content=COURSES_QUESTION),
        ChatMessage(role="user", content="I have completed these courses: CSCI 100, CSCI 102L."),
    ]
    context = ControlledIntakeParser().parse(messages)
    assert context is not None
    assert [course.value for course in context.completed_courses] == ["CSCI 100", "CSCI 102L"]
    assert context.skills == []


def test_course_history_accepts_common_usc_code_shorthand_and_natural_titles() -> None:
    from trojan_compass.readiness import COURSES_QUESTION

    parser = ControlledIntakeParser()
    coded = parser.parse(
        [
            ChatMessage(role="assistant", content=COURSES_QUESTION),
            ChatMessage(role="user", content="CS570 and CS 572"),
        ]
    )
    assert coded is not None
    assert [item.value for item in coded.completed_courses] == ["CSCI 570", "CSCI 572"]
    assert coded.skills == []

    named = parser.parse(
        [
            ChatMessage(role="assistant", content=COURSES_QUESTION),
            ChatMessage(role="user", content="I have done the Algorithms course"),
        ]
    )
    assert named is not None
    assert [item.value for item in named.completed_courses] == ["Algorithms course"]
    assert named.skills == []


def test_unrelated_followup_does_not_erase_completed_checklist_answers() -> None:
    from trojan_compass.readiness import COURSES_QUESTION, DIRECTION_QUESTION

    messages = [
        ChatMessage(role="assistant", content=DIRECTION_QUESTION),
        ChatMessage(role="user", content="Building things"),
        ChatMessage(role="assistant", content="What kind of things would you enjoy building?"),
        ChatMessage(role="user", content="Design or architecture"),
        ChatMessage(role="assistant", content=COURSES_QUESTION),
        ChatMessage(role="user", content="CS570 and CS 572"),
        ChatMessage(role="assistant", content="I don't have a verified match for those."),
        ChatMessage(role="user", content="I have done the Algorithms course"),
    ]
    context = ControlledIntakeParser().parse(messages)
    assert context is not None
    assert context.interests[0].value == "Design or architecture"
    assert [item.value for item in context.completed_courses] == [
        "CSCI 570",
        "CSCI 572",
        "Algorithms course",
    ]
    assert context.skills == []


@pytest.mark.asyncio
async def test_optional_router_timeout_is_cancelled_before_intake(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio

    from trojan_compass.assistant import CampusAssistant, RouteDecision
    from trojan_compass.contracts import ChatRequest
    from trojan_compass.services import ChatService

    cancelled = asyncio.Event()

    class SlowRouter(CampusAssistant):
        def __init__(self) -> None:
            pass

        async def route(self, messages: list[ChatMessage]) -> RouteDecision:
            try:
                await asyncio.sleep(60)
                raise AssertionError("Router should have been cancelled")
            finally:
                cancelled.set()

    class EmptyExtractor:
        async def extract(self, messages: list[ChatMessage]) -> RetrievalContext:
            return RetrievalContext()

    original = asyncio.timeout

    def quick_route_timeout(delay: float | None) -> asyncio.Timeout:
        return original(0.001 if delay == 3 else delay)

    monkeypatch.setattr(asyncio, "timeout", quick_route_timeout)
    service = ChatService(EmptyExtractor(), RecordingRecommendations(), assistant=SlowRouter())
    response = await service.chat(
        ChatRequest(messages=[ChatMessage(role="user", content="Help me explore")])
    )
    assert response.suggested_replies
    assert cancelled.is_set()
    assert not response.recommendations


def test_provider_timeout_reports_safe_processing_stage() -> None:
    class TimedOutExtractor:
        async def extract(self, messages: list[ChatMessage]) -> RetrievalContext:
            raise ExtractionFailure(FailureReason.TIMEOUT)

    app = create_app(
        mode="campus", extractor=TimedOutExtractor(), recommendations=RecordingRecommendations()
    )
    with TestClient(app) as client:
        response = client.post(
            "/api/chat", json={"messages": [{"role": "user", "content": "Synthetic private words"}]}
        )
    assert response.status_code == 503
    assert "interpreting your answer" in response.json()["error"]["message"]
    assert "Synthetic private words" not in response.text
