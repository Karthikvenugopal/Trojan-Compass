"""Full-catalog fallback search over a synthetic Schedule of Classes snapshot."""

import json
from pathlib import Path
from typing import Any

import pytest

from trojan_compass.catalog import (
    CatalogIndex,
    CatalogRecommendationService,
    query_phrases,
    tokenize,
)
from trojan_compass.contracts import (
    Clarification,
    Recommendation,
    RecommendationRequest,
    RecommendationResult,
    RecommendationService,
    RetrievalContext,
    Skill,
    StudentStatement,
    SupportedText,
)
from trojan_compass.extraction import quoted

API = "https://classes.usc.edu/api/Courses/Course?termCode={term}&courseCode={code}"


def offering(term: str, label: str, code: str, active: int = 1) -> dict[str, Any]:
    return {
        "term": term,
        "term_label": label,
        "source_url": API.format(term=term, code=code),
        "active_sections": active,
        "modes": ["Lecture"],
        "seats_total": 100,
        "seats_remaining": 20,
        "syllabus_urls": [f"https://usc.simplesyllabus.com/en-US/syllabus/{label}/{code}"],
    }


def course(
    code: str, title: str, description: str, level: str = "graduate", **extra: object
) -> dict[str, Any]:
    hyphen = code.replace(" ", "-")
    return {
        "code": code,
        "title": title,
        "level": level,
        "description": description,
        "units": [4],
        "schools": ["Viterbi School of Engineering"],
        "programs": ["Computer Science"],
        "offerings": {"20263": offering("20263", "Fall 2026", hyphen)},
        **extra,
    }


CATALOG = {
    "source": "synthetic",
    "fetched_at": "2026-11-14T00:00:00+00:00",
    "terms": {"20261": "Spring 2026", "20263": "Fall 2026"},
    "courses": [
        course(
            "CSCI 572",
            "Information Retrieval and Web Search Engines",
            "Examines key aspects of information retrieval as they apply to search engines; "
            "web crawling, indexing, querying and quality of results are studied.",
            recommended_prep="Familiarity in programming in multiple languages",
        ),
        course(
            "CSCI 544",
            "Applied Natural Language Processing",
            "Natural language processing techniques including large language models.",
        ),
        course(
            "CSCI 103L",
            "Object Oriented Programming",
            "Fundamental concepts of object oriented programming in C++.",
            level="undergraduate",
        ),
        course(
            "ANAT 501",
            "Human Gross Anatomy",
            "Structure of the human body studied through dissection and imaging.",
        ),
    ],
}


def statement(index: int = 0, quote: str = "x") -> list[StudentStatement]:
    return [StudentStatement(message_index=index, quote=quote)]


def text(value: str) -> SupportedText:
    return SupportedText(value=value, evidence=statement(quote=value))


@pytest.fixture
def index(tmp_path: Path) -> CatalogIndex:
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps(CATALOG), encoding="utf-8")
    return CatalogIndex.load(path)


class Empty:
    async def recommend(self, request: RecommendationRequest) -> RecommendationResult:
        return RecommendationResult(exploration_options=["Computer programming"])


def request(context: RetrievalContext, limit: int = 3) -> RecommendationRequest:
    return RecommendationRequest(context=context, user_query="help", limit=limit)


def test_stemming_joins_word_forms() -> None:
    assert tokenize("retrieval") == tokenize("Retrieval")
    assert tokenize("models") == tokenize("model")
    assert tokenize("I tried YouTube videos") == []


@pytest.mark.asyncio
async def test_completed_course_title_is_used_as_background_for_next_course(
    index: CatalogIndex,
) -> None:
    context = RetrievalContext(completed_courses=[text("Information Retrieval")])
    assert query_phrases(context) == ["Information Retrieval"]
    result = await CatalogRecommendationService(Empty(), index).recommend(request(context))
    assert all(
        card.title != "CSCI 572: Information Retrieval and Web Search Engines"
        for card in result.recommendations
    )


def test_rag_and_information_retrieval_find_the_ir_course(index: CatalogIndex) -> None:
    hits = index.search(["Agentic RAGs", "Information Retrieval"], 3, frozenset())
    assert hits[0].course.code == "CSCI 572"
    assert hits[0].phrase == "Information Retrieval"


def test_non_engineering_fields_are_searchable(index: CatalogIndex) -> None:
    hits = index.search(["human anatomy"], 3, frozenset())
    assert [h.course.code for h in hits] == ["ANAT 501"]


def test_unrelated_query_returns_nothing(index: CatalogIndex) -> None:
    assert index.search(["underwater basket weaving"], 3, frozenset()) == []


async def test_fallback_cards_quote_official_text_and_cite_sources(index: CatalogIndex) -> None:
    context = RetrievalContext(
        interests=[text("Information Retrieval")],
        skills=[Skill(name="Agentic RAG", status="learning", evidence=statement())],
    )
    result = await CatalogRecommendationService(Empty(), index).recommend(request(context))

    card = result.recommendations[0]
    assert isinstance(card, Recommendation)
    assert card.title == "CSCI 572: Information Retrieval and Web Search Engines"
    assert "information retrieval" in card.why_relevant[0].casefold()
    assert str(card.sources[0].url).startswith("https://classes.usc.edu/api/Courses/Course")
    assert card.course is not None and (card.course.term or "").startswith("Fall 2026")
    assert any("Recommended preparation" in item for item in card.prerequisites_or_access)
    assert result.limitations and "Schedule of Classes" in result.limitations[0]


async def test_completed_courses_are_excluded(index: CatalogIndex) -> None:
    context = RetrievalContext(
        interests=[text("information retrieval search engines")],
        completed_courses=[text("CSCI 572")],
    )
    result = await CatalogRecommendationService(Empty(), index).recommend(request(context))
    assert "CSCI 572" not in {r.title.split(":")[0] for r in result.recommendations}


def curated(card: Recommendation) -> RecommendationService:
    class Curated:
        async def recommend(self, request: RecommendationRequest) -> RecommendationResult:
            return RecommendationResult(recommendations=[card], limitations=["curated"])

    return Curated()


async def test_specific_catalog_match_ranks_before_generic_curated_result(
    index: CatalogIndex,
) -> None:
    oop = RetrievalContext(interests=[text("object oriented programming")])
    generic = await CatalogRecommendationService(Empty(), index).recommend(request(oop))
    service = CatalogRecommendationService(curated(generic.recommendations[0]), index)

    context = RetrievalContext(
        interests=[text("Programming"), text("information retrieval")],
    )
    result = await service.recommend(request(context))
    titles = [r.title.split(":")[0] for r in result.recommendations]
    assert titles[:2] == ["CSCI 572", "CSCI 103L"]
    assert len(titles) == len(set(titles))
    assert result.limitations[0] == "curated"
    assert result.exploration_options == []


async def test_curated_clarification_without_results_is_kept(index: CatalogIndex) -> None:
    question = RecommendationResult(
        clarification=Clarification(
            text="Which area?", requested_fields=["direction"], reason="Needed to search."
        )
    )

    class Asking:
        async def recommend(self, request: RecommendationRequest) -> RecommendationResult:
            return question

    context = RetrievalContext(interests=[text("information retrieval")])
    result = await CatalogRecommendationService(Asking(), index).recommend(request(context))
    assert result is question


@pytest.mark.parametrize(
    ("quote", "ok"),
    [
        ("Agentic RAGs", True),
        ("I have tried learning...Information REtrieval", False),
        ("I have tried learning … Information REtrieval", False),
        ("Information REtrieval...I have tried", False),  # parts out of order
        ("I have studied...Information REtrieval", False),  # part not verbatim
        ("...", False),
    ],
)
def test_quotes_require_contiguous_student_words(quote: str, ok: bool) -> None:
    content = "I have tried learning normal Agentic RAGs and Information REtrieval from Yt Videos"
    assert quoted(quote, content) is ok


async def test_no_catalog_match_keeps_inner_exploration_options(index: CatalogIndex) -> None:
    context = RetrievalContext(interests=[text("underwater basket weaving")])
    result = await CatalogRecommendationService(Empty(), index).recommend(request(context))
    assert result.recommendations == []
    assert result.exploration_options == ["Computer programming"]


async def test_reason_credits_the_phrase_that_best_explains_the_match(
    index: CatalogIndex,
) -> None:
    context = RetrievalContext(
        interests=[text("Programming apps")],
        experiences=[text("tried Agentic RAGs and Information REtrieval from videos")],
    )
    result = await CatalogRecommendationService(Empty(), index).recommend(request(context))
    ir = next(r for r in result.recommendations if r.title.startswith("CSCI 572"))
    assert "Information REtrieval" in ir.why_relevant[0]


@pytest.mark.parametrize("quote", ["I ... know Python", "I … know Python"])
def test_quotation_cannot_erase_a_student_negation(quote: str) -> None:
    assert not quoted(quote, "I do not know Python")


async def test_undergraduate_catalog_search_does_not_add_graduate_courses(
    index: CatalogIndex,
) -> None:
    context = RetrievalContext(
        interests=[text("information retrieval")], study_stage=text("Undergraduate")
    )
    result = await CatalogRecommendationService(Empty(), index).recommend(request(context))
    assert result.recommendations == []


async def test_event_request_does_not_get_replaced_by_catalog_courses(index: CatalogIndex) -> None:
    req = request(RetrievalContext(interests=[text("information retrieval")]))
    req.user_query = "Find events"
    assert not (await CatalogRecommendationService(Empty(), index).recommend(req)).recommendations


async def test_catalog_missing_format_and_remaining_seats_stay_unknown(tmp_path: Path) -> None:
    raw = course(
        "TEST 101", "Information Retrieval", "Information retrieval methods.", level="undergraduate"
    )
    raw["offerings"]["20263"].update(modes=[], seats_remaining=None)
    path = tmp_path / "public.json"
    path.write_text(json.dumps({**CATALOG, "courses": [raw]}))
    result = await CatalogRecommendationService(Empty(), CatalogIndex.load(path)).recommend(
        request(RetrievalContext(interests=[text("information retrieval")]))
    )
    card = result.recommendations[0]
    assert card.course and card.course.modality is None
    assert "remaining seats unknown" in (card.course.term or "")


async def test_catalog_keeps_recorded_graph_prerequisite_blocks(index: CatalogIndex) -> None:
    from trojan_compass.contracts import Source
    from trojan_compass.graph.fake import FakeGraphRepository
    from trojan_compass.recommendations.graph import (
        CampusAction,
        CourseInfo,
        Prerequisite,
        SkillNode,
    )

    graph = FakeGraphRepository().with_action(
        CampusAction(
            id="synthetic",
            kind="course",
            title="Information Retrieval",
            summary="Synthetic",
            sources=[Source(url="https://example.org", title="Synthetic source")],
            course=CourseInfo(
                code="CSCI 572",
                prerequisites=[
                    Prerequisite(description="Python", skill=SkillNode(id="python", name="Python"))
                ],
            ),
        )
    )
    context = RetrievalContext(
        interests=[text("information retrieval")],
        skills=[Skill(name="Python", status="not_yet_learned", evidence=statement())],
    )
    result = await CatalogRecommendationService(Empty(), index, graph=graph).recommend(
        request(context)
    )
    assert all(not r.title.startswith("CSCI 572") for r in result.recommendations)


async def test_completed_public_alias_cannot_reappear_through_catalog(tmp_path: Path) -> None:
    from datetime import date

    from trojan_compass.graph.fake import FakeGraphRepository
    from trojan_compass.ingestion.loaders import decode
    from trojan_compass.public_import import UniversityBatchBuilder
    from trojan_compass.university import UniversityGraphRepository

    builder = UniversityBatchBuilder(date(2026, 11, 15))
    builder.course(
        dict(
            prefix="PSYC",
            classNumber="100",
            suffix="L",
            fullCourseName="PSYC 100",
            name="Introduction to Psychology",
        ),
        dict(prefix="DRNS", name="Dornsife"),
        dict(name="Psychology"),
        "20263",
    )
    graph = UniversityGraphRepository(FakeGraphRepository(), decode(builder.batch()))
    path = tmp_path / "synthetic-public-catalog.json"
    path.write_text(
        json.dumps(
            {
                **CATALOG,
                "courses": [
                    course(
                        "PSYC 100",
                        "Introduction to Psychology",
                        "Psychology human behavior",
                        level="undergraduate",
                    )
                ],
            }
        )
    )
    context = RetrievalContext(
        interests=[text("psychology")], completed_courses=[text("PSYC 100L")]
    )
    result = await CatalogRecommendationService(
        Empty(), CatalogIndex.load(path), graph=graph
    ).recommend(request(context))
    assert result.recommendations == []
