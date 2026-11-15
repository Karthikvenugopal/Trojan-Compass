"""Campus question routing, evidence assembly and live library hours (fake LLM)."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from test_catalog import CATALOG

from trojan_compass.assistant import (
    OTHER_MESSAGE,
    CampusAnswer,
    CampusAssistant,
    Evidence,
    KnowledgeBase,
    RouteDecision,
)
from trojan_compass.campus_live import LibrarySnapshot, LibraryStatus, parse_library_hours
from trojan_compass.catalog import CatalogIndex
from trojan_compass.contracts import (
    ChatMessage,
    ChatRequest,
    RecommendationRequest,
    RecommendationResult,
    RetrievalContext,
)
from trojan_compass.services import ChatService

LEAVEY = "1794643200|Opens at 9am|closed,1794675600|Closes at 9pm|open,1794718800|Closed|closed"
HOURS_HTML = f"""
<div class="library-hours__row library-hours-js" data-lid="1" data-hours="{LEAVEY}">
  <span class="library-status__library-name"><a href="/x">Leavey Library</a></span>
  <span class="library-status__group"><span class="library-status__hours">9am to 9pm</span></span>
</div>
<div class="library-hours__row library-hours-js" data-lid="2" data-hours="1794643200|Closed|closed">
  <span class="library-status__library-name"><a href="/y">Doheny Memorial Library</a></span>
  <span class="library-status__group"><span class="library-status__hours">Closed</span></span>
</div>
"""


def test_library_hours_reflect_the_current_time() -> None:
    morning = parse_library_hours(HOURS_HTML, datetime.fromtimestamp(1794650000, UTC))
    midday = parse_library_hours(HOURS_HTML, datetime.fromtimestamp(1794680000, UTC))
    night = parse_library_hours(HOURS_HTML, datetime.fromtimestamp(1794720000, UTC))
    leavey = [s.libraries[0] for s in (morning, midday, night)]
    assert [lib.open_now for lib in leavey] == [False, True, False]
    assert leavey[0].next_change == "opens at 9:00 AM"
    assert leavey[1].next_change == "closes at 9:00 PM"
    assert midday.libraries[1].name == "Doheny Memorial Library"
    assert not midday.libraries[1].open_now
    assert "Leavey Library: OPEN now" in midday.as_text()


class FakeLLM:
    """Returns a scripted route, and records the evidence the answer step received."""

    def __init__(self, route: RouteDecision, answer: CampusAnswer | None = None) -> None:
        self.route = route
        self.answer = answer or CampusAnswer(answer="ok", source_ids=[], follow_ups=[])
        self.evidence: list[dict[str, Any]] = []

    async def complete(self, system: str, user: str, schema: type[Any]) -> Any:
        if schema is RouteDecision:
            return self.route
        self.evidence = json.loads(user)["evidence"]
        return self.answer


class FakeLibrary:
    async def snapshot(self) -> LibrarySnapshot:
        return LibrarySnapshot(
            fetched_at=datetime(2026, 11, 14, 18, tzinfo=UTC),
            libraries=(LibraryStatus("Leavey Library", "9am to 9pm", True, "closes at 9:00 PM"),),
        )


def route(intent: str, **extra: Any) -> RouteDecision:
    values: dict[str, Any] = {
        "intent": intent,
        "course_codes": [],
        "search_query": "question",
        "needs_library_hours": False,
    }
    return RouteDecision.model_validate(values | extra)


@pytest.fixture
def catalog(tmp_path: Path) -> CatalogIndex:
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps(CATALOG), encoding="utf-8")
    return CatalogIndex.load(path)


def knowledge() -> KnowledgeBase:
    return KnowledgeBase(
        [
            Evidence(
                "kb-1",
                "Student Health hours",
                "https://studenthealth.usc.edu/hours/",
                "Engemann Student Health Center is open weekdays 8am to 5pm.",
                None,
            ),
            Evidence("kb-2", "Parking", "https://transnet.usc.edu/", "Parking permits.", None),
        ]
    )


def ask(text: str) -> list[ChatMessage]:
    return [ChatMessage(role="user", content=text)]


async def test_library_question_uses_live_hours_and_cites_it(catalog: CatalogIndex) -> None:
    llm = FakeLLM(
        route("campus_question", needs_library_hours=True, search_query="Is Leavey open"),
        CampusAnswer(
            answer="Yes, Leavey is open until 9 PM.",
            source_ids=["live-library-hours", "made-up-id"],
            follow_ups=["What about Doheny?"],
        ),
    )
    assistant = CampusAssistant(llm, catalog, knowledge(), FakeLibrary())  # type: ignore[arg-type]
    response = await assistant.answer(ask("Is Leavey open now?"), llm.route)

    assert response.message == "Yes, Leavey is open until 9 PM."
    assert [str(s.url) for s in response.sources] == ["https://libraries.usc.edu/hours"]
    assert response.suggested_replies == ["What about Doheny?"]
    assert "Leavey Library: OPEN now" in llm.evidence[0]["text"]


async def test_course_question_gets_catalog_record(catalog: CatalogIndex) -> None:
    llm = FakeLLM(route("course_question", course_codes=["csci 572"]))
    assistant = CampusAssistant(llm, catalog, knowledge(), FakeLibrary())  # type: ignore[arg-type]
    await assistant.answer(ask("Who teaches CSCI 572?"), llm.route)
    record = llm.evidence[0]
    assert record["id"] == "course-CSCI572"
    assert "Information Retrieval and Web Search Engines" in record["text"]
    assert "Fall 2026" in record["text"]


async def test_campus_question_searches_official_pages(catalog: CatalogIndex) -> None:
    llm = FakeLLM(route("campus_question", search_query="student health center hours"))
    assistant = CampusAssistant(llm, catalog, knowledge(), FakeLibrary())  # type: ignore[arg-type]
    await assistant.answer(ask("When is student health open?"), llm.route)
    assert llm.evidence[0]["id"] == "kb-1"


async def test_off_topic_gets_a_capabilities_reply_without_an_llm_answer() -> None:
    llm = FakeLLM(route("other"))
    response = await CampusAssistant(llm).answer(ask("hi"), llm.route)
    assert response.message == OTHER_MESSAGE
    assert llm.evidence == []


class OneCardExtractor:
    def __init__(self) -> None:
        self.cancelled = False

    async def extract(self, messages: list[ChatMessage]) -> RetrievalContext:
        return RetrievalContext()


class NoRecommendations:
    async def recommend(self, request: RecommendationRequest) -> RecommendationResult:
        return RecommendationResult()


async def test_chat_service_answers_questions_without_the_course_flow() -> None:
    llm = FakeLLM(route("other"))
    service = ChatService(OneCardExtractor(), NoRecommendations(), assistant=CampusAssistant(llm))
    response = await service.chat(ChatRequest(messages=ask("hello")))
    assert response.message == OTHER_MESSAGE


async def test_recommendation_intent_and_router_failures_keep_the_course_flow() -> None:
    class Broken:
        async def complete(self, system: str, user: str, schema: type[Any]) -> Any:
            raise RuntimeError("provider down")

    for llm in (FakeLLM(route("recommendation")), Broken()):
        service = ChatService(
            OneCardExtractor(),
            NoRecommendations(),
            assistant=CampusAssistant(llm),
        )
        response = await service.chat(ChatRequest(messages=ask("Help me get started")))
        assert response.message.startswith("What interests you")


def test_extraction_drops_echoed_values_on_unanswered_states() -> None:
    from trojan_compass.extraction import parse_context

    raw = json.dumps(
        {
            "answers": [
                {
                    "field": "background",
                    "status": "none",
                    "value": "None",
                    "evidence": [{"message_index": 0, "quote": "None"}],
                }
            ]
        }
    )
    context = parse_context(raw)
    assert context.answers[0].status == "none"
    assert context.answers[0].value is None


@pytest.mark.parametrize(
    "quote",
    ["Programming \x14 apps or websites", "programming - apps or websites", "Programming apps"],
)
def test_quotes_tolerate_garbled_punctuation_but_not_new_words(quote: str) -> None:
    from trojan_compass.extraction import quoted

    content = "Programming — apps or websites"
    assert quoted(quote, content) is (quote != "Programming websites")
    assert not quoted("Programming games or websites", content)
