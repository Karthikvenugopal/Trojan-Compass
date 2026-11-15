"""Synthetic journeys through readiness, corrections and request-local snapshots."""

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from test_chat import FakeExtractor, resource

from trojan_compass.api import create_app
from trojan_compass.contracts import (
    ChatMessage,
    ChatRequest,
    Clarification,
    ContextExtractor,
    ContextRequirement,
    InformationEdit,
    RecommendationRequest,
    RecommendationResult,
    RetrievalContext,
    StudentAnswer,
    StudentStatement,
    SupportedText,
)
from trojan_compass.extraction import ExtractionFailure, validate_evidence
from trojan_compass.readiness import DIRECTION_QUESTION, request_information
from trojan_compass.services import ChatService


def user(text: str, edit: InformationEdit | None = None) -> ChatMessage:
    return ChatMessage(role="user", content=text, edit=edit)


def said(text: str, index: int = 0) -> list[StudentStatement]:
    return [StudentStatement(message_index=index, quote=text)]


class RetrievalSpy:
    def __init__(self, question: Clarification | None = None) -> None:
        self.requests: list[RecommendationRequest] = []
        self.question = question

    async def recommend(self, request: RecommendationRequest) -> RecommendationResult:
        self.requests.append(request)
        return RecommendationResult(recommendations=[resource()], clarification=self.question)


@pytest.mark.parametrize("text", ["Hi", "Show courses", "Show events", "I am a student"])
async def test_no_context_never_calls_recommendations(text: str) -> None:
    spy = RetrievalSpy()
    response = await ChatService(FakeExtractor(), spy).chat(ChatRequest(messages=[user(text)]))
    assert spy.requests == []
    assert not response.recommendations
    assert response.information.missing_fields == ["direction"]
    assert all(f.value is None and f.status == "not_answered" for f in response.information.fields)


async def test_a_previous_question_does_not_count_as_an_answer() -> None:
    spy = RetrievalSpy()
    response = await ChatService(FakeExtractor(), spy).chat(
        ChatRequest(
            messages=[
                user("Hi"),
                ChatMessage(role="assistant", content=DIRECTION_QUESTION),
                user("Hello again"),
            ]
        )
    )
    assert spy.requests == []
    assert response.information.missing_fields == ["direction"]


@pytest.mark.parametrize("text", ["I don't know", "None"])
async def test_explicit_unavailability_is_answered_and_acknowledged(text: str) -> None:
    spy = RetrievalSpy()
    response = await ChatService(FakeExtractor(), spy).chat(
        ChatRequest(
            messages=[
                user("Hi"),
                ChatMessage(role="assistant", content=DIRECTION_QUESTION),
                user(text),
            ]
        )
    )
    assert len(spy.requests) == 1
    assert response.information.ready
    assert response.recommendations
    assert "general campus starting points" in response.message
    assert "not personalized" in response.message
    answer = next(f for f in response.information.fields if f.field == "direction")
    assert answer.value is None
    assert answer.status == ("unknown" if text == "I don't know" else "none")


async def test_panel_reset_clears_old_facts_and_blocks_retrieval_again() -> None:
    context = RetrievalContext(
        interests=[SupportedText(value="robotics", evidence=said("robotics"))]
    )
    spy = RetrievalSpy()
    messages = [
        user("robotics"),
        ChatMessage(role="assistant", content="Synthetic reply"),
        user(
            "Update my direction: Not answered.",
            InformationEdit(field="direction", status="not_answered"),
        ),
    ]
    response = await ChatService(FakeExtractor(context), spy).chat(ChatRequest(messages=messages))
    assert spy.requests == []
    assert response.information.missing_fields == ["direction"]
    assert response.information.fields[0].value is None
    assert not request_information(context, messages).context.interests
    # A later natural correction wins over the old typed edit.
    messages += [ChatMessage(role="assistant", content=response.message), user("I like music")]
    later = RetrievalContext(interests=[SupportedText(value="music", evidence=said("music", 4))])
    updated = request_information(later, messages)
    assert updated.snapshot().ready
    assert updated.context.interests[0].value == "music"


async def test_saved_sentence_replaces_old_values_and_carries_latest_query() -> None:
    context = RetrievalContext(
        interests=[SupportedText(value="robotics", evidence=said("robotics"))]
    )
    spy = RetrievalSpy()
    edit = InformationEdit(field="direction", status="provided", value="I like music")
    messages = [
        user("Find robotics events"),
        ChatMessage(role="assistant", content="Synthetic reply"),
        user("Update my direction: I like music", edit),
    ]
    response = await ChatService(FakeExtractor(context), spy).chat(ChatRequest(messages=messages))
    assert response.information.ready
    assert spy.requests[0].user_query == "Update my direction: I like music"
    assert [i.value for i in spy.requests[0].context.interests] == ["I like music"]
    fresh = await ChatService(FakeExtractor(), spy).chat(ChatRequest(messages=[user("Hi")]))
    assert not fresh.information.ready
    assert fresh.information.fields[0].value is None


async def test_request_specific_availability_blocks_until_answered() -> None:
    text = "Find robotics events that fit my schedule"
    context = RetrievalContext(
        interests=[SupportedText(value="robotics", evidence=said("robotics"))],
        requested_context=[
            ContextRequirement(field="time_window", evidence=said("fit my schedule"))
        ],
    )
    spy = RetrievalSpy()
    service = ChatService(FakeExtractor(context), spy)
    first = await service.chat(ChatRequest(messages=[user(text)]))
    assert first.information.missing_fields == ["time_window"]
    assert spy.requests == []
    second = await service.chat(
        ChatRequest(
            messages=[
                user(text),
                ChatMessage(role="assistant", content=first.message),
                user("I don't know"),
            ]
        )
    )
    assert second.information.ready
    assert len(spy.requests) == 1
    assert any("Availability" in note for note in second.limitations)


async def test_graph_prerequisite_question_holds_back_provisional_cards() -> None:
    text = "I like robotics"
    context = RetrievalContext(
        interests=[SupportedText(value="robotics", evidence=said("robotics"))]
    )
    question = Clarification(
        text="How comfortable are you with Python?",
        requested_fields=["skills.python"],
        options=["I know Python", "I don't know"],
        reason="Changes which level is feasible",
    )
    service = ChatService(FakeExtractor(context), RetrievalSpy(question))
    first = await service.chat(ChatRequest(messages=[user(text)]))
    assert first.message == question.text
    assert not first.recommendations
    assert first.information.missing_fields == ["skills.python"]
    second = await service.chat(
        ChatRequest(
            messages=[
                user(text),
                ChatMessage(role="assistant", content=first.message),
                user("I don't know"),
            ]
        )
    )
    assert second.information.ready
    assert second.recommendations
    assert any("python" in note.casefold() for note in second.limitations)


def test_explicit_zero_background_does_not_invent_missing_skills() -> None:
    context = RetrievalContext(
        answers=[StudentAnswer(field="background", status="none", evidence=said("no experience"))]
    )
    info = request_information(context, [user("no experience")])
    assert info.answer("background").status == "none"
    assert info.context.skill_status("Python") == "unknown"


def test_answer_evidence_cannot_come_from_assistant_suggestions() -> None:
    context = RetrievalContext(
        answers=[StudentAnswer(field="direction", status="none", evidence=said("None", 1))]
    )
    with pytest.raises(ExtractionFailure):
        validate_evidence(context, [user("Hi"), ChatMessage(role="assistant", content="None")])


@pytest.mark.parametrize(
    "edit",
    [
        {"field": "direction", "status": "provided", "value": None},
        {"field": "direction", "status": "none", "value": "Invented"},
        {"field": "execute", "status": "none", "value": None},
    ],
)
def test_invalid_edits_are_rejected_without_echoing_student_data(edit: dict[str, object]) -> None:
    response = TestClient(create_app()).post(
        "/api/chat",
        json={
            "messages": [
                {"role": "user", "content": "PRIVATE_EDIT_SENTINEL", "edit": edit},
            ]
        },
    )
    assert response.status_code == 422
    assert "PRIVATE_EDIT_SENTINEL" not in response.text


def test_assistant_cannot_attach_an_edit() -> None:
    with pytest.raises(ValidationError):
        ChatMessage(
            role="assistant",
            content="Synthetic",
            edit=InformationEdit(field="direction", status="none"),
        )


def test_unconfirmed_skill_mastery_is_unanswered_until_explicitly_acknowledged() -> None:
    from trojan_compass.contracts import Skill

    context = RetrievalContext(
        skills=[Skill(name="Python", status="unknown", evidence=said("Python"))]
    )
    info = request_information(context, [user("I've heard of Python")])
    assert info.answer("skills.python").status == "not_answered"
    context.answers = [
        StudentAnswer(field="skills.python", status="unknown", evidence=said("don't know", 1))
    ]
    info = request_information(context, [user("I've heard of Python"), user("I don't know")])
    assert info.answer("skills.python").status == "unknown"
    assert info.context.skill_status("Python") == "unknown"


async def test_request_specific_background_requires_an_answer_but_zero_is_valid() -> None:
    text = "Find robotics courses for my experience level"
    context = RetrievalContext(
        interests=[SupportedText(value="robotics", evidence=said("robotics"))],
        requested_context=[
            ContextRequirement(field="background", evidence=said("my experience level"))
        ],
    )
    spy = RetrievalSpy()
    service = ChatService(FakeExtractor(context), spy)
    first = await service.chat(ChatRequest(messages=[user(text)]))
    assert first.information.missing_fields == ["background"]
    assert not spy.requests
    second = await service.chat(
        ChatRequest(
            messages=[
                user(text),
                ChatMessage(role="assistant", content=first.message),
                user("I have no experience"),
            ]
        )
    )
    assert second.information.ready
    background = next(f for f in second.information.fields if f.field == "background")
    assert background.status == "none"
    assert not spy.requests[0].context.skills


async def test_changing_request_changes_volatile_requirements() -> None:
    first_context = RetrievalContext(
        interests=[SupportedText(value="robotics", evidence=said("robotics"))],
        requested_context=[ContextRequirement(field="time_window", evidence=said("my schedule"))],
    )
    messages = [user("Find robotics events that fit my schedule")]
    first = await ChatService(FakeExtractor(first_context), RetrievalSpy()).chat(
        ChatRequest(messages=messages)
    )
    assert first.information.missing_fields == ["time_window"]
    messages += [
        ChatMessage(role="assistant", content=first.message),
        user("Instead, suggest robotics courses with no timing preference"),
    ]
    new_context = RetrievalContext(
        interests=[SupportedText(value="robotics", evidence=said("robotics", 2))]
    )
    second = await ChatService(FakeExtractor(new_context), RetrievalSpy()).chat(
        ChatRequest(messages=messages)
    )
    assert second.information.ready
    assert not any(f.field == "time_window" for f in second.information.fields)


@pytest.mark.parametrize("provider", ["openai", "gemini"])
async def test_provider_structured_output_preserves_explicit_absence(provider: str) -> None:
    import httpx

    from trojan_compass.extraction import OpenAIContextExtractor
    from trojan_compass.gemini import GeminiContextExtractor

    text = "I don't have any interests to share yet"
    context = RetrievalContext(
        answers=[StudentAnswer(field="direction", status="none", evidence=said(text))]
    )

    def respond(request: httpx.Request) -> httpx.Response:
        if provider == "openai":
            body = {
                "choices": [
                    {"finish_reason": "stop", "message": {"content": context.model_dump_json()}}
                ]
            }
        else:
            body = {
                "candidates": [
                    {
                        "finishReason": "STOP",
                        "content": {"parts": [{"text": context.model_dump_json()}]},
                    }
                ]
            }
        return httpx.Response(200, json=body)

    extractor: ContextExtractor
    if provider == "openai":
        extractor = OpenAIContextExtractor(
            "synthetic-key", "synthetic-model", httpx.MockTransport(respond)
        )
    else:
        extractor = GeminiContextExtractor(
            "synthetic-key", "synthetic-model", httpx.MockTransport(respond)
        )
    response = await ChatService(extractor, RetrievalSpy()).chat(ChatRequest(messages=[user(text)]))
    assert response.information.ready
    assert response.information.fields[0].status == "none"
    assert "not personalized" in response.message


def test_edit_removes_old_target_even_when_extraction_includes_new_interest() -> None:
    from trojan_compass.contracts import Target

    messages = [
        user("I like robotics and want Synthetic Company"),
        ChatMessage(role="assistant", content="Synthetic reply"),
        user(
            "Update my direction: I prefer music",
            InformationEdit(field="direction", status="provided", value="I prefer music"),
        ),
    ]
    context = RetrievalContext(
        interests=[
            SupportedText(value="robotics", evidence=said("robotics")),
            SupportedText(value="music", evidence=said("music", 2)),
        ],
        target=Target(kind="company", name="Synthetic Company", evidence=said("Synthetic Company")),
    )
    info = request_information(context, messages)
    assert info.context.target is None
    assert [i.value for i in info.context.interests] == ["music"]
    assert info.answer("direction").value == "I prefer music"


async def test_collecting_a_schedule_does_not_claim_it_was_verified() -> None:
    from trojan_compass.contracts import Constraints

    context = RetrievalContext(
        interests=[SupportedText(value="robotics", evidence=said("robotics"))],
        constraints=Constraints(
            time_window=SupportedText(value="Mondays", evidence=said("Mondays"))
        ),
    )
    response = await ChatService(FakeExtractor(context), RetrievalSpy()).chat(
        ChatRequest(messages=[user("Find robotics courses; I'm available Mondays")])
    )
    assert response.information.ready
    assert any(
        "automatic schedule matching is not supported" in note for note in response.limitations
    )
