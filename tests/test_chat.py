"""Only synthetic conversations; providers and graph dependencies are isolated fakes."""

import asyncio
import builtins
import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel, ValidationError
from starlette.types import Message, Scope

from trojan_compass.api import create_app
from trojan_compass.contracts import (
    ChatMessage,
    ChatRequest,
    ChatResponse,
    Clarification,
    EventSchedule,
    Recommendation,
    RecommendationRequest,
    RecommendationResult,
    RetrievalContext,
    Skill,
    Source,
    StudentStatement,
    SupportedText,
)
from trojan_compass.extraction import (
    EXTRACTION_PROMPT,
    ExtractionFailure,
    OpenAIContextExtractor,
    validate_evidence,
)
from trojan_compass.services import AskBackPolicy, ChatService, ChatUnavailable


class FakeExtractor:
    def __init__(self, context: RetrievalContext | None = None) -> None:
        self.context = context or RetrievalContext()

    async def extract(self, messages: list[ChatMessage]) -> RetrievalContext:
        return self.context.model_copy(deep=True)


class FakeRecommendations:
    def __init__(self, result: RecommendationResult | None = None) -> None:
        self.result = result or RecommendationResult()

    async def recommend(self, request: RecommendationRequest) -> RecommendationResult:
        return self.result.model_copy(deep=True)


def student(text: str) -> ChatMessage:
    return ChatMessage(role="user", content=text)


def statement(quote: str, index: int = 0) -> StudentStatement:
    return StudentStatement(message_index=index, quote=quote)


def resource() -> Recommendation:
    return Recommendation(
        id="synthetic-course",
        kind="course",
        title="Fixture: programming course",
        summary="Synthetic testing resource, not an actual USC offering.",
        why_relevant=["Synthetic interest maps to the fixture topic."],
        benefits=["Practice programming in the fixture scenario."],
        unknowns=["Eligibility and availability have not been verified."],
        sources=[Source(url="https://example.invalid/fixture", title="Synthetic fixture")],
        evidence_path=["fixture:interest", "fixture:topic", "fixture:course"],
    )


def clarification(field: str = "interests") -> Clarification:
    return Clarification(
        text="Which topic would you like to explore?",
        options=["Building apps", "Understanding people", "Working with data"],
        requested_fields=[field],
        reason="A topic narrows graph retrieval.",
    )


@pytest.mark.asyncio
async def test_targeted_clarification_with_no_required_career_target() -> None:
    service = ChatService(
        FakeExtractor(),
        FakeRecommendations(
            RecommendationResult(clarification=clarification()),
        ),
    )
    response = await service.chat(ChatRequest(messages=[student("Help me get started")]))
    assert response.message == clarification().text
    assert "I’m not sure — show broad starting points" in response.suggested_replies
    assert not response.recommendations
    assert "profile" not in response.model_dump_json()
    assert "session" not in response.model_dump_json()


@pytest.mark.asyncio
async def test_experienced_student_gets_sourced_results_without_discovery() -> None:
    context = RetrievalContext(
        skills=[
            Skill(
                name="Python",
                status="known",
                evidence=[statement("I know Python")],
            )
        ]
    )
    result = RecommendationResult(recommendations=[resource()])
    response = await ChatService(FakeExtractor(context), FakeRecommendations(result)).chat(
        ChatRequest(messages=[student("I know Python; show me related courses")]),
    )
    assert response.recommendations == [resource()]
    assert not response.suggested_replies
    assert response.recommendations[0].sources


def test_askback_skips_answered_and_repeat_questions() -> None:
    policy = AskBackPolicy()
    context = RetrievalContext(
        interests=[
            SupportedText(
                value="robotics",
                evidence=[statement("robotics")],
            )
        ]
    )
    assert policy.choose(clarification(), context, []) is None
    assert policy.choose(clarification("contact.email"), context, []) is None
    assert (
        policy.choose(
            clarification(),
            RetrievalContext(),
            [
                student("Help"),
                ChatMessage(role="assistant", content=clarification().text),
                student("I’m not sure"),
            ],
        )
        is None
    )


def test_unknown_skill_is_not_missing_and_course_does_not_imply_skill() -> None:
    context = RetrievalContext(
        completed_courses=[
            SupportedText(
                value="Synthetic intro course",
                evidence=[statement("I finished an intro course")],
            )
        ]
    )
    assert context.skill_status("Python") == "unknown"
    assert not context.skills
    assert AskBackPolicy().choose(clarification("skills.python"), context, []) is not None


@pytest.mark.parametrize("index,quote", [(1, "Try Python"), (0, "invented"), (8, "Help")])
def test_evidence_rejects_assistant_and_unquoted_facts(index: int, quote: str) -> None:
    context = RetrievalContext(
        skills=[
            Skill(
                name="Python",
                evidence=[statement(quote, index)],
            )
        ]
    )
    with pytest.raises(ExtractionFailure):
        validate_evidence(
            context,
            [
                student("Help"),
                ChatMessage(
                    role="assistant",
                    content="Try Python",
                ),
                student("Other ideas?"),
            ],
        )


@pytest.mark.asyncio
async def test_provider_receives_all_turns_and_returns_fresh_corrected_snapshot() -> None:
    messages = [
        student("I know Python and want robotics"),
        ChatMessage(role="assistant", content="You could try machine learning"),
        student("Correction: I am learning Python, not proficient. Keep robotics."),
    ]
    corrected = RetrievalContext(
        skills=[
            Skill(
                name="Python",
                status="learning",
                evidence=[
                    statement(
                        "I am learning Python, not proficient.",
                        2,
                    )
                ],
            )
        ],
        interests=[SupportedText(value="robotics", evidence=[statement("Keep robotics.", 2)])],
    )

    def respond(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert json.loads(payload["messages"][1]["content"]) == [m.model_dump() for m in messages]
        assert payload["store"] is False
        assert "thread" not in payload
        assert payload["response_format"]["json_schema"]["strict"] is True
        assert "Later explicit student corrections" in EXTRACTION_PROMPT
        assert "Assistant suggestions" in EXTRACTION_PROMPT
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": corrected.model_dump_json(),
                        },
                    }
                ]
            },
        )

    extractor = OpenAIContextExtractor("fake-key", "fake-model", httpx.MockTransport(respond))
    context = await extractor.extract(messages)
    assert context == corrected
    assert context.skill_status("Python") == "learning"
    assert context.skill_status("machine learning") == "unknown"


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["refusal", "truncated", "bad_json", "bad_schema", "http"])
async def test_provider_failures_are_sanitized(kind: str) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        if kind == "http":
            return httpx.Response(429, text="PRIVATE_PROVIDER_DETAILS")
        message = {"content": "not json" if kind == "bad_json" else "{}"}
        if kind == "bad_schema":
            message["content"] = '{"invented_profile": "PRIVATE_PROVIDER_DETAILS"}'
        if kind == "refusal":
            message["refusal"] = "PRIVATE_PROVIDER_DETAILS"
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "length" if kind == "truncated" else "stop",
                        "message": message,
                    }
                ]
            },
        )

    extractor = OpenAIContextExtractor("fake", "fake", httpx.MockTransport(respond))
    with pytest.raises(ExtractionFailure) as exc:
        await extractor.extract([student("Synthetic query")])
    assert str(exc.value) == ""
    assert exc.value.__suppress_context__


class QueryExtractor:
    """Pure fake proves requests are re-extracted, never merged across calls."""

    async def extract(self, messages: list[ChatMessage]) -> RetrievalContext:
        await asyncio.sleep(0)
        return RetrievalContext(
            interests=[
                SupportedText(
                    value=messages[-1].content,
                    evidence=[statement(messages[-1].content, len(messages) - 1)],
                )
            ]
        )


class EchoRecommendations:
    async def recommend(self, request: RecommendationRequest) -> RecommendationResult:
        await asyncio.sleep(0)
        assert len(request.context.interests) == 1
        assert request.context.interests[0].value == request.user_query
        recommendation = resource().model_copy(update={"id": request.user_query})
        return RecommendationResult(recommendations=[recommendation])


@pytest.mark.asyncio
async def test_request_isolation_concurrent_and_sequential() -> None:
    service = ChatService(QueryExtractor(), EchoRecommendations())
    responses = await asyncio.gather(
        *[service.chat(ChatRequest(messages=[student(query)])) for query in ["robotics", "music"]]
    )
    assert [r.recommendations[0].id for r in responses] == ["robotics", "music"]
    third = await service.chat(ChatRequest(messages=[student("design")]))
    assert third.recommendations[0].id == "design"
    assert set(vars(service)) == {"_extractor", "_recommendations", "_policy"}


@pytest.mark.parametrize(
    "messages",
    [
        [],
        [{"role": "system", "content": "synthetic"}],
        [{"role": "assistant", "content": "synthetic"}],
        [{"role": "user", "content": " "}],
        [{"role": "user", "content": "a" * 4001}],
        [{"role": "user", "content": "a" * 4000}] * 7,
        [{"role": "user", "content": "a"}] * 65,
    ],
)
def test_invalid_and_oversized_conversations(messages: list[dict[str, str]]) -> None:
    with TestClient(create_app()) as client:
        response = client.post("/api/chat", json={"messages": messages})
    assert response.status_code == 422
    assert response.headers["cache-control"] == "no-store"
    assert "Nothing was truncated" in response.text
    assert '"input"' not in response.text


def test_byte_limit_and_private_validation() -> None:
    with TestClient(create_app()) as client:
        response = client.post("/api/chat", content=b"x" * 65537)
        assert response.status_code == 413
        response = client.post(
            "/api/chat",
            json={
                "messages": [{"role": "tool", "content": "PRIVATE_SENTINEL"}],
            },
        )
        assert "PRIVATE_SENTINEL" not in response.text
        response = client.post("/api/chat", content='{"PRIVATE_SENTINEL":')
        assert "PRIVATE_SENTINEL" not in response.text
        assert response.status_code == 422
        assert "set-cookie" not in response.headers
        assert client.post("/api/sessions").status_code == 404


@pytest.mark.asyncio
async def test_chunked_body_limit_without_content_length() -> None:
    chunks = iter([b"x" * 1024] * 70)
    sent: list[Message] = []

    async def receive() -> Message:
        return {"type": "http.request", "body": next(chunks), "more_body": True}

    async def send(message: Message) -> None:
        sent.append(message)

    scope: Scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/chat",
        "raw_path": b"/api/chat",
        "query_string": b"",
        "headers": [],
        "scheme": "http",
        "http_version": "1.1",
        "server": ("test", 80),
        "client": ("test", 1),
        "root_path": "",
    }
    await create_app()(scope, receive, send)
    assert sent[0]["status"] == 413


class BrokenExtractor:
    async def extract(self, messages: list[ChatMessage]) -> RetrievalContext:
        raise RuntimeError("PRIVATE_SENTINEL")


class BrokenRecommendations:
    async def recommend(self, request: RecommendationRequest) -> RecommendationResult:
        raise RuntimeError("PRIVATE_SENTINEL")


@pytest.mark.parametrize("extraction", [True, False])
def test_failures_and_no_content_logs(extraction: bool, caplog: pytest.LogCaptureFixture) -> None:
    app = create_app(
        extractor=BrokenExtractor() if extraction else FakeExtractor(),
        recommendations=FakeRecommendations() if extraction else BrokenRecommendations(),
    )
    with TestClient(app) as client:
        response = client.post(
            "/api/chat",
            json={
                "messages": [{"role": "user", "content": "PRIVATE_SENTINEL"}],
            },
        )
    assert response.status_code == 503
    assert "PRIVATE_SENTINEL" not in response.text
    assert "PRIVATE_SENTINEL" not in caplog.text
    assert "traceback" not in caplog.text.lower()


def test_endpoint_does_not_open_student_files(monkeypatch: pytest.MonkeyPatch) -> None:
    app = create_app()
    with TestClient(app) as client:

        def forbid(*args: Any, **kwargs: Any) -> Any:
            raise AssertionError("File access during chat")

        with monkeypatch.context() as patch:
            patch.setattr(builtins, "open", forbid)
            patch.setattr(Path, "write_text", forbid)
            patch.setattr(Path, "write_bytes", forbid)
            response = client.post(
                "/api/chat",
                json={
                    "messages": [{"role": "user", "content": "Synthetic query"}],
                },
            )
        assert response.status_code == 200
        result = ChatResponse.model_validate(response.json())
        assert "Demo mode" in result.limitations[0]
        assert "set-cookie" not in response.headers


def test_production_requires_both_dependencies() -> None:
    with pytest.raises(ValueError, match="Production requires"):
        create_app(mode="production")


def test_schedule_validation() -> None:
    with pytest.raises(ValidationError):
        EventSchedule.model_validate({"start": "2026-11-15T10:00:00"})
    with pytest.raises(ValidationError):
        EventSchedule.model_validate(
            {
                "start": "2026-11-16T10:00:00-08:00",
                "end": "2026-11-15T10:00:00-08:00",
            }
        )


@pytest.mark.asyncio
async def test_untrusted_extractor_output_rechecked_at_service_boundary() -> None:
    context = RetrievalContext(skills=[Skill(name="Python", evidence=[statement("Invented")])])
    with pytest.raises(ChatUnavailable):
        await ChatService(FakeExtractor(context), FakeRecommendations()).chat(
            ChatRequest(messages=[student("Help me")]),
        )


def test_demo_beginner_journey_with_uncertain_reply() -> None:
    with TestClient(create_app()) as client:
        messages = [{"role": "user", "content": "Help me get started"}]
        first = client.post("/api/chat", json={"messages": messages})
        assert first.status_code == 200
        first_body = ChatResponse.model_validate(first.json())
        assert "I’m not sure" in first_body.suggested_replies
        messages += [
            {"role": "assistant", "content": first_body.message},
            {"role": "user", "content": "I’m not sure"},
        ]
        second = client.post("/api/chat", json={"messages": messages})
        assert second.status_code == 200
        result = ChatResponse.model_validate(second.json())
        assert result.recommendations[0].status == "demo_fixture"
        assert result.recommendations[0].sources
        assert "Demo mode" in result.limitations[0]
        assert not result.suggested_replies


@pytest.mark.asyncio
async def test_cap_results_and_preserve_provisional_clarification() -> None:
    resources = [resource().model_copy(update={"id": str(i)}) for i in range(5)]
    result = RecommendationResult(
        recommendations=resources,
        clarification=clarification(),
        limitations=["Fixture limitation"],
    )
    response = await ChatService(FakeExtractor(), FakeRecommendations(result)).chat(
        ChatRequest(messages=[student("Show me campus options")]),
    )
    assert len(response.recommendations) == 3
    assert clarification().text in response.message
    assert response.limitations == ["Fixture limitation"]
    assert response.recommendations[0].unknowns == resource().unknowns


@pytest.mark.asyncio
async def test_orchestration_timeout_is_safe(monkeypatch: pytest.MonkeyPatch) -> None:
    original_timeout = asyncio.timeout

    def fast_timeout(delay: float | None) -> asyncio.Timeout:
        return original_timeout(0.001)

    class SlowExtractor:
        async def extract(self, messages: list[ChatMessage]) -> RetrievalContext:
            await asyncio.sleep(1)
            return RetrievalContext()

    monkeypatch.setattr(asyncio, "timeout", fast_timeout)
    with pytest.raises(ChatUnavailable):
        await ChatService(SlowExtractor(), FakeRecommendations()).chat(
            ChatRequest(messages=[student("Synthetic query")]),
        )


def test_contract_examples_and_schema_stay_valid() -> None:
    from trojan_compass.contracts import RecommendationRequest

    models: dict[str, type[BaseModel]] = {
        "chat_request": ChatRequest,
        "chat_response": ChatResponse,
        "recommendation_request": RecommendationRequest,
        "recommendation_result": RecommendationResult,
    }
    directory = Path(__file__).parents[1] / "docs" / "examples"
    for name, model in models.items():
        model.model_validate_json((directory / f"{name}.json").read_text())
    schemas = json.loads((directory / "contracts.schema.json").read_text())
    schema_models: list[type[BaseModel]] = [
        ChatRequest,
        RetrievalContext,
        RecommendationRequest,
        RecommendationResult,
        ChatResponse,
    ]
    for model in schema_models:
        assert schemas[model.__name__] == model.model_json_schema()


@pytest.mark.asyncio
async def test_reextracts_later_correction_and_explicit_target_removal() -> None:
    from trojan_compass.contracts import Target

    first_messages = [student("I want a role at ExampleCo")]
    corrected_messages = first_messages + [
        ChatMessage(role="assistant", content="We can explore related skills."),
        student("Correction: remove ExampleCo as my target. I want to explore broadly."),
    ]

    def respond(request: httpx.Request) -> httpx.Response:
        messages = json.loads(json.loads(request.content)["messages"][1]["content"])
        context = RetrievalContext()
        if len(messages) == 1:
            context = RetrievalContext(
                target=Target(
                    kind="company",
                    name="ExampleCo",
                    evidence=[statement(first_messages[0].content)],
                )
            )
        else:
            assert messages[-1]["content"] == corrected_messages[-1].content
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": context.model_dump_json()},
                    }
                ]
            },
        )

    extractor = OpenAIContextExtractor("fake", "fake", httpx.MockTransport(respond))
    assert (await extractor.extract(first_messages)).target is not None
    assert (await extractor.extract(corrected_messages)).target is None


@pytest.mark.asyncio
async def test_invalid_retrieval_output_fails_without_fabricated_fallback() -> None:
    invalid = resource().model_copy(update={"sources": []})
    with pytest.raises(ChatUnavailable):
        await ChatService(
            FakeExtractor(),
            FakeRecommendations(
                RecommendationResult(
                    recommendations=[invalid],
                )
            ),
        ).chat(ChatRequest(messages=[student("Synthetic query")]))


@pytest.mark.asyncio
async def test_maximum_length_clarification_with_provisional_results() -> None:
    question = clarification().model_copy(update={"text": "Q" * 4000})
    response = await ChatService(
        FakeExtractor(),
        FakeRecommendations(
            RecommendationResult(
                recommendations=[resource()],
                clarification=question,
            )
        ),
    ).chat(ChatRequest(messages=[student("Show me campus options")]))
    assert response.message == question.text
    assert response.recommendations
