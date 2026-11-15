"""Engine wired into the real chat backend (ChatService, AskBackPolicy, /api/chat).

Only the context extractor is faked; contracts, orchestration and HTTP are the real ones.
All conversations are synthetic.
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from trojan_compass.api import create_app
from trojan_compass.contracts import (
    ChatMessage,
    ChatRequest,
    Clarification,
    RecommendationRequest,
    RecommendationResult,
    RetrievalContext,
    Skill,
    StudentStatement,
    SupportedText,
    Target,
)
from trojan_compass.recommendations import FixedClock, RecommendationEngine
from trojan_compass.recommendations.synthetic_graph import synthetic_repository
from trojan_compass.services import AskBackPolicy, ChatService

NOW = datetime(2026, 11, 14, 12, 0, tzinfo=timezone(timedelta(hours=-8)))
EXAMPLES = Path(__file__).resolve().parents[1] / "docs" / "examples"


class ContextExtractorStub:
    """Returns a fixed context; quotes must still appear in the conversation."""

    def __init__(self, context: RetrievalContext) -> None:
        self._context = context

    async def extract(self, messages: list[ChatMessage]) -> RetrievalContext:
        return self._context.model_copy(deep=True)


def engine() -> RecommendationEngine:
    return RecommendationEngine(synthetic_repository(), clock=FixedClock(NOW))


def said(quote: str, index: int = 0) -> list[StudentStatement]:
    return [StudentStatement(message_index=index, quote=quote)]


async def test_published_example_request_round_trips() -> None:
    request = RecommendationRequest.model_validate_json(
        (EXAMPLES / "recommendation_request.json").read_text(encoding="utf-8")
    )
    result = await engine().recommend(request)
    # ChatService re-validates dependency output the same way.
    RecommendationResult.model_validate(result.model_dump())
    assert result.recommendations
    assert all(r.sources and r.evidence_path for r in result.recommendations)


def test_chat_endpoint_returns_engine_recommendations() -> None:
    message = "I'm into robotics and I haven't learned Python yet."
    context = RetrievalContext(
        interests=[SupportedText(value="robotics", evidence=said("robotics"))],
        skills=[
            Skill(name="Python", status="not_yet_learned", evidence=said("haven't learned Python"))
        ],
    )
    app = create_app(
        mode="production", extractor=ContextExtractorStub(context), recommendations=engine()
    )
    response = TestClient(app).post(
        "/api/chat", json={"messages": [{"role": "user", "content": message}]}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["recommendations"]
    for rec in body["recommendations"]:
        assert rec["sources"] and rec["evidence_path"] and rec["why_relevant"]
        assert rec["status"]


async def test_not_sure_reply_gets_broad_options_instead_of_the_same_question() -> None:
    service = ChatService(ContextExtractorStub(RetrievalContext()), engine())
    first = await service.chat(
        ChatRequest(messages=[ChatMessage(role="user", content="Help me get started")])
    )
    assert first.suggested_replies, "the first turn asks one question"
    assert first.recommendations == [], "a vague opening must not dump broad event/course cards"

    second = await service.chat(
        ChatRequest(
            messages=[
                ChatMessage(role="user", content="Help me get started"),
                ChatMessage(role="assistant", content=first.message),
                ChatMessage(role="user", content="I'm not sure"),
            ]
        )
    )
    assert second.recommendations, "after 'not sure' the student still gets starting points"
    assert second.suggested_replies == []
    assert second.message == "Here are campus options with supporting sources below."

    fresh = await service.chat(ChatRequest(messages=[ChatMessage(role="user", content="Hello")]))
    assert fresh.recommendations == [], "another request must not inherit discovery progress"
    assert fresh.suggested_replies


@pytest.mark.parametrize("opening", ["Hi", "Help me get started", "I have no idea what to do"])
async def test_vague_opening_asks_before_showing_graph_events(opening: str) -> None:
    service = ChatService(ContextExtractorStub(RetrievalContext()), engine())
    response = await service.chat(ChatRequest(messages=[ChatMessage(role="user", content=opening)]))
    assert not response.recommendations
    assert "enjoy" in response.message
    assert len(response.suggested_replies) > 1
    assert any("sure" in option for option in response.suggested_replies)
    assert not response.limitations  # No notices referring to unshown broad cards.


@pytest.mark.parametrize("query", ["Show me campus events", "Find introductory courses"])
async def test_explicit_browsing_can_get_graph_results_immediately(query: str) -> None:
    service = ChatService(ContextExtractorStub(RetrievalContext()), engine())
    response = await service.chat(ChatRequest(messages=[ChatMessage(role="user", content=query)]))
    assert response.recommendations
    assert all(resource.sources for resource in response.recommendations)


async def test_skill_question_path_is_understood_by_ask_back_policy() -> None:
    message = "I want to be a software engineer."
    base = RetrievalContext(
        target=Target(kind="role", name="Software Engineer", evidence=said("software engineer"))
    )
    result = await engine().recommend(RecommendationRequest(context=base, user_query=message))
    assert result.clarification is not None
    assert result.clarification.requested_fields == ["skills.python"]

    policy = AskBackPolicy()
    messages = [ChatMessage(role="user", content=message)]
    assert policy.choose(result.clarification, base, messages) is not None

    answered = base.model_copy(
        update={"skills": [Skill(name="Python", status="known", evidence=said("software"))]}
    )
    assert policy.choose(result.clarification, answered, messages) is None


def test_multiword_skill_path_matches_policy_by_name() -> None:
    """Paths use the casefolded graph name so multiword skills register as answered."""
    question = Clarification(
        text="How comfortable are you with Data structures?",
        options=["I'm not sure"],
        requested_fields=["skills.data structures"],
        reason="Synthetic.",
    )
    context = RetrievalContext(
        skills=[Skill(name="Data structures", status="learning", evidence=said("x"))]
    )
    messages = [ChatMessage(role="user", content="x")]
    assert AskBackPolicy().choose(question, context, messages) is None
