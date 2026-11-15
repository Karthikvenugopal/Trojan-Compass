"""Knowledge-graph construction and pathway recommendations over synthetic data."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from test_catalog import CATALOG, course

from trojan_compass.catalog import CatalogIndex
from trojan_compass.contracts import (
    ChatMessage,
    ChatRequest,
    RecommendationRequest,
    RecommendationResult,
    RetrievalContext,
    Skill,
    StudentStatement,
    SupportedText,
)
from trojan_compass.knowledge_graph import KnowledgeGraph
from trojan_compass.pathways import (
    CHANGE_REPLY,
    EXPLAIN_REPLY,
    LinkedSkill,
    PathwayRecommendationService,
    SkillLinks,
    student_level,
)
from trojan_compass.readiness import starter_question
from trojan_compass.services import ChatService

NOW = datetime(2026, 11, 15, tzinfo=UTC)
SKILLS = {
    "CSCI 572": ["information retrieval", "web search engines"],
    "CSCI 544": ["natural language processing", "large language models"],
    "CSCI 103L": ["object oriented programming", "programming"],
    "CSCI 270": ["algorithms"],
    "ANAT 501": ["human anatomy"],
}
FACULTY = [
    {
        "name": "Ada Lovelace",
        "first_name": "Ada",
        "last_name": "Lovelace",
        "title": "Professor of Computer Science",
        "departments": ["Computer Science"],
        "profile_url": "https://www.cs.usc.edu/directory/faculty/profile/?lname=Lovelace&fname=Ada",
        "research_text": "Search engines and retrieval.",
        "areas": ["information retrieval", "question answering"],
    },
    {
        "name": "Grace Hopper",
        "first_name": "Grace",
        "last_name": "Hopper",
        "title": "Research Professor",
        "departments": ["Computer Science"],
        "profile_url": "https://www.cs.usc.edu/directory/faculty/profile/?lname=Hopper&fname=Grace",
        "research_text": "Compilers and retrieval.",
        "areas": ["information retrieval"],
    },
]
EVENTS = [
    {
        "id": "hs-mock-1",
        "name": "Search tech talk",
        "event_type": "Tech Talk",
        "host": "Nimbus Labs",
        "start_date": "2026-12-01T17:00:00-08:00",
        "end_date": "2026-12-01T18:00:00-08:00",
        "time_zone": "America/Los_Angeles",
        "medium": "in_person",
        "location": "SGM 123",
        "description": "Sample tech talk.",
        "skills": ["information retrieval"],
        "audience": {"schools": ["Viterbi School of Engineering"]},
        "rsvp_url": "https://usc.joinhandshake.com/",
        "is_mock": True,
    },
    {
        "id": "hs-mock-2",
        "name": "Past event",
        "event_type": "Workshop",
        "start_date": "2026-01-01T17:00:00-08:00",
        "end_date": "2026-01-01T18:00:00-08:00",
        "skills": ["information retrieval"],
    },
]


def statement() -> list[StudentStatement]:
    return [StudentStatement(message_index=0, quote="x")]


def text(value: str) -> SupportedText:
    return SupportedText(value=value, evidence=statement())


@pytest.fixture
def graph(tmp_path: Path) -> KnowledgeGraph:
    payload = json.loads(json.dumps(CATALOG))
    payload["courses"].append(
        course("CSCI 270", "Introduction to Algorithms", "Algorithm design and analysis.")
    )
    for raw in payload["courses"]:
        if raw["code"] == "CSCI 572":
            raw["prerequisites"] = [
                {"courseOptions": [{"courseSpace": "CSCI 270"}, {"courseSpace": "CSCI 999"}]}
            ]
            raw["offerings"]["20263"]["instructors"] = ["Ada Lovelace"]
    catalog_path = tmp_path / "catalog.json"
    catalog_path.write_text(json.dumps(payload), encoding="utf-8")
    skills_path = tmp_path / "skills.json"
    skills_path.write_text(json.dumps(SKILLS), encoding="utf-8")
    faculty_path = tmp_path / "faculty.json"
    faculty_path.write_text(json.dumps({"faculty": FACULTY}), encoding="utf-8")
    events_path = tmp_path / "events.json"
    events_path.write_text(json.dumps({"events": EVENTS}), encoding="utf-8")
    return KnowledgeGraph.load(
        CatalogIndex.load(catalog_path), catalog_path, skills_path, faculty_path, events_path
    )


class FakeLLM:
    def __init__(self, links: SkillLinks | None = None) -> None:
        self.links = links
        self.payload: dict[str, Any] = {}

    async def complete(self, system: str, user: str, schema: type[Any]) -> Any:
        self.payload = json.loads(user)
        if self.links is None:
            raise RuntimeError("provider down")
        return self.links


def request(context: RetrievalContext, query: str = "x") -> RecommendationRequest:
    return RecommendationRequest(context=context, user_query=query, limit=4)


def test_graph_connects_courses_skills_professors_and_events(graph: KnowledgeGraph) -> None:
    stats = graph.stats()
    assert stats["courses"] == 5 and stats["events"] == 2
    assert stats["edges_prerequisite"] == 2
    retrieval = graph.find_skill("Information Retrieval")
    assert retrieval is not None
    assert retrieval.courses == ["CSCI 572"]
    assert graph.prerequisites["csci572"] == [["CSCI 270", "CSCI 999"]]
    teacher = graph.professors_of("CSCI 572")[0]
    assert teacher.name == "Ada Lovelace"
    assert teacher.profile_url is not None and "question-answering" in teacher.areas[1]
    # Research-only faculty still become people nodes linked to the skill.
    assert {graph.professors[k].name for k in retrieval.professors} == {
        "Ada Lovelace",
        "Grace Hopper",
    }


def test_candidates_come_from_skill_names_and_course_text(graph: KnowledgeGraph) -> None:
    names = [c.skill.name.lower() for c in graph.candidate_skills(["agentic RAG systems"], 10)]
    assert "information retrieval" in names[:3]
    names = [
        c.skill.name.lower() for c in graph.candidate_skills(["web crawling and indexing"], 10)
    ]
    assert names[0] in ("information retrieval", "web search engines")
    assert graph.candidate_skills(["zzzz"], 5) == []


async def test_pathway_walks_graph_and_returns_cards_graph_and_roadmap(
    graph: KnowledgeGraph,
) -> None:
    llm = FakeLLM(
        SkillLinks(
            focus="search and RAG",
            learn=[
                LinkedSkill(id="skill:information-retrieval", why="it powers RAG systems"),
                LinkedSkill(id="skill:not-in-graph", why="ignored"),
            ],
            known=[],
        )
    )
    context = RetrievalContext(
        interests=[text("agentic RAG and information retrieval")],
        skills=[Skill(name="Python", status="known", evidence=statement())],
        program=text("MS in Computer Science"),
    )
    service = PathwayRecommendationService(graph, llm, now=lambda: NOW)
    result = await service.recommend(request(context))

    assert all(c["id"].startswith("skill:") for c in llm.payload["candidates"])
    first = result.recommendations[0]
    assert first.title == "CSCI 572: Information Retrieval and Web Search Engines"
    assert first.why_relevant[0] == "Teaches Information retrieval. It powers RAG systems."
    assert "Ada Lovelace teaches it in Fall 2026" in first.why_relevant[1]
    assert first.prerequisites_or_access[0] == "Prerequisite: CSCI 270 or CSCI 999"
    assert first.evidence_path[:2] == [
        "Your interest: search and RAG",
        "Skill: Information retrieval",
    ]
    event = result.recommendations[-1]
    assert event.kind == "event" and event.title == "Search tech talk (sample event)"
    assert event.status == "sample data"
    assert any("sample data" in item for item in result.limitations)

    assert result.graph is not None and result.roadmap is not None
    kinds = {n.kind for n in result.graph.nodes}
    assert kinds == {"interest", "skill", "course", "professor", "event"}
    labels = {(e.source, e.target): e.label for e in result.graph.edges}
    assert labels[("interest", "skill:information-retrieval")] == "needs"
    assert labels[("skill:information-retrieval", "course:csci572")] == "taught in"
    assert labels[("course:csci270", "course:csci572")] == "prerequisite for"
    assert labels[("course:csci572", "prof:ada-lovelace")] == "taught by"
    assert labels[("skill:information-retrieval", "prof:grace-hopper")] == "researched by"
    assert labels[("skill:information-retrieval", "hs-mock-1")] == "practised at"

    roadmap = result.roadmap
    assert roadmap.known == ["Python (known)"]
    assert roadmap.to_learn[0].name == "Information retrieval"
    assert [c.code for c in roadmap.courses[:2]] == ["CSCI 270", "CSCI 572"]
    assert roadmap.courses[0].note == "Take first: prerequisite for CSCI 572"
    assert {p.name for p in roadmap.people} == {"Ada Lovelace", "Grace Hopper"}
    assert result.follow_ups[-2:] == [EXPLAIN_REPLY, CHANGE_REPLY]
    assert result.summary is not None and "CSCI 572" in result.summary


async def test_linking_failure_falls_back_to_lexical_links(graph: KnowledgeGraph) -> None:
    context = RetrievalContext(interests=[text("information retrieval")])
    service = PathwayRecommendationService(graph, FakeLLM(None), now=lambda: NOW)
    result = await service.recommend(request(context))
    assert result.recommendations[0].title.startswith("CSCI 572")
    assert result.roadmap is not None


async def test_completed_courses_are_skipped_and_prerequisite_marked_done(
    graph: KnowledgeGraph,
) -> None:
    context = RetrievalContext(
        interests=[text("information retrieval")], completed_courses=[text("CSCI 270")]
    )
    result = await PathwayRecommendationService(graph, None, now=lambda: NOW).recommend(
        request(context)
    )
    first = result.recommendations[0]
    assert first.prerequisites_or_access[0].endswith("(you've taken this)")
    assert result.roadmap is not None
    assert "CSCI 270" not in [c.code for c in result.roadmap.courses]


async def test_no_direction_or_no_graph_match_uses_the_fallback(graph: KnowledgeGraph) -> None:
    marker = RecommendationResult(limitations=["fallback"])

    class Fallback:
        async def recommend(self, request: RecommendationRequest) -> RecommendationResult:
            return marker

    service = PathwayRecommendationService(graph, None, fallback=Fallback(), now=lambda: NOW)
    assert await service.recommend(request(RetrievalContext())) is marker
    unknown = RetrievalContext(interests=[text("zzzz qqqq")])
    assert await service.recommend(request(unknown)) is marker


def test_student_level_and_starter_questions() -> None:
    assert student_level(RetrievalContext(program=text("MS in Computer Science"))) == "graduate"
    assert student_level(RetrievalContext(program=text("PhD student"))) == "doctoral"
    assert student_level(RetrievalContext(program=text("sophomore"))) == "undergraduate"
    assert student_level(RetrievalContext()) is None
    question = starter_question("I have an interest to explore.")
    assert question is not None and question[0].startswith("What interest")
    assert starter_question("I know what I want to do.") is not None
    assert starter_question("Help me get started") is None


async def test_chat_service_passes_graph_roadmap_and_follow_ups(graph: KnowledgeGraph) -> None:
    context = RetrievalContext(interests=[text("information retrieval")])

    class Extractor:
        async def extract(self, messages: list[ChatMessage]) -> RetrievalContext:
            return context

    service = ChatService(Extractor(), PathwayRecommendationService(graph, None, now=lambda: NOW))
    message = ChatMessage(role="user", content="information retrieval. I have no experience.")
    response = await service.chat(ChatRequest(messages=[message]))
    assert response.message.startswith("Here's a path for information retrieval")
    assert response.graph is not None and response.roadmap is not None
    assert CHANGE_REPLY in response.suggested_replies
    assert len(response.recommendations) <= 4
