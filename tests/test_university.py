"""Default intake journeys and public-data provenance, using synthetic students only."""

from datetime import UTC, date, datetime

import pytest
from fastapi.testclient import TestClient

from trojan_compass.api import create_app
from trojan_compass.contracts import (
    ChatMessage,
    ChatRequest,
    ChatResponse,
    InformationEdit,
    RecommendationRequest,
    RecommendationResult,
    RetrievalContext,
    StudentStatement,
    SupportedText,
)
from trojan_compass.graph.fake import FakeGraphRepository
from trojan_compass.ingestion.loaders import decode
from trojan_compass.ingestion.pipeline import IngestionPipeline
from trojan_compass.public_import import UniversityBatchBuilder
from trojan_compass.readiness import DEFAULT_FIXED_FIELDS, request_information
from trojan_compass.services import ChatService
from trojan_compass.university import AcademicCourseHistoryService, UniversityGraphRepository


class EmptyExtractor:
    async def extract(self, messages: list[ChatMessage]) -> RetrievalContext:
        return RetrievalContext()


class RetrievalSpy:
    def __init__(self) -> None:
        self.calls = 0

    async def recommend(self, request: RecommendationRequest) -> RecommendationResult:
        self.calls += 1
        return RecommendationResult()


def edit(field: str, value: str | None = None, status: str | None = None) -> ChatMessage:
    update = InformationEdit.model_validate(
        dict(
            field=field,
            status=status or ("provided" if value is not None else "none"),
            value=value,
        )
    )
    return ChatMessage(
        role="user", content=f"Update {field}: {value or update.status}.", edit=update
    )


async def test_default_policy_collects_all_fixed_fields_before_recommendations() -> None:
    spy = RetrievalSpy()
    service = ChatService(EmptyExtractor(), spy)
    messages = [ChatMessage(role="user", content="Hi")]
    first = await service.chat(ChatRequest(messages=messages))
    assert first.information.missing_fields == list(DEFAULT_FIXED_FIELDS)
    assert all(f.value is None for f in first.information.fields)
    assert "completed courses" in first.message
    for index, (field, value) in enumerate(
        [
            ("direction", "Psychology"),
            ("study_stage", "Undergraduate"),
            ("program", "Psychology"),
            ("work_experience", None),
            ("completed_courses", None),
        ]
    ):
        messages.append(edit(field, value))
        response = await service.chat(ChatRequest(messages=messages))
        assert spy.calls == (1 if index == 4 else 0)
        if index < 4:
            assert response.information.missing_fields[0] == DEFAULT_FIXED_FIELDS[index + 1]
            assert not response.recommendations
    assert response.information.ready
    fields = {f.field: f for f in response.information.fields}
    assert fields["work_experience"].status == "none"
    assert fields["completed_courses"].status == "none"
    assert fields["background"].status == "not_answered"  # No invented mastery.
    fresh = await service.chat(ChatRequest(messages=[ChatMessage(role="user", content="Hi")]))
    assert not fresh.information.ready
    assert all(f.value is None for f in fresh.information.fields)


async def test_unknown_is_an_answer_and_not_started_does_not_imply_no_courses() -> None:
    spy = RetrievalSpy()
    service = ChatService(EmptyExtractor(), spy)
    messages: list[ChatMessage] = []
    responses = []
    for answer in [
        "Hi",
        "I don't know",
        "Not started at USC yet",
        "I haven't chosen a program",
        "I have no experience",
        "I don't know",
    ]:
        messages.append(ChatMessage(role="user", content=answer))
        response = await service.chat(ChatRequest(messages=messages))
        responses.append(response)
        messages.append(ChatMessage(role="assistant", content=response.message))
    assert responses[2].information.missing_fields == [
        "program",
        "work_experience",
        "completed_courses",
    ]
    assert responses[4].information.missing_fields == ["completed_courses"]
    assert responses[-1].information.ready
    assert spy.calls == 1
    fields = {f.field: f for f in responses[-1].information.fields}
    assert fields["completed_courses"].status == "unknown"
    assert fields["program"].status == "none"


def test_fixed_fields_survive_request_change_and_edits_replace_history() -> None:
    messages = [
        edit("direction", "Psychology"),
        edit("study_stage", "Graduate student"),
        edit("program", "Psychology"),
        edit("work_experience", "I volunteered at a museum"),
        edit("completed_courses", "PSYC 100"),
        edit("completed_courses"),
    ]
    info = request_information(RetrievalContext(), messages)
    assert info.context.completed_courses == []
    assert info.context.skills == []
    assert info.context.experiences[0].value == "I volunteered at a museum"
    messages.append(edit("direction", "Music"))
    changed = request_information(RetrievalContext(), messages)
    assert changed.snapshot().ready
    assert changed.context.program and changed.context.program.value == "Psychology"
    assert changed.context.interests[0].value == "Music"


def public_batch() -> UniversityGraphRepository:
    builder = UniversityBatchBuilder(date(2026, 11, 14))
    for prefix, title, subject, school in [
        ("PSYC", "Introduction to Psychology", "Psychology", "Dornsife"),
        ("MUSC", "Introduction to Music", "Music", "Thornton"),
        ("ACCT", "Financial Accounting", "Accounting", "Leventhal"),
        ("LAW", "Introduction to Law", "Law", "Gould"),
        ("HP", "Introduction to Public Health", "Health Promotion", "Keck"),
    ]:
        builder.course(
            dict(
                prefix=prefix,
                classNumber="100",
                name=title,
                description=f"Introduction to {subject}",
                fullCourseName=f"{prefix} 100",
            ),
            dict(prefix=prefix, name=school),
            dict(name=subject),
            "20263",
        )
    for identifier, start in [(1, "2026-11-13T17:00:00-08:00"), (2, "2026-12-01T17:00:00-08:00")]:
        builder.event(
            dict(
                id=identifier,
                title="Psychology and public health symposium",
                localist_url=f"https://calendar.usc.edu/event/symposium-{identifier}",
                status="live",
                departments=[dict(name="Keck School of Medicine")],
                event_instances=[
                    dict(event_instance=dict(id=identifier, start=start, end=None, all_day=False))
                ],
            ),
            datetime(2026, 11, 14, tzinfo=UTC),
        )
    batch = decode(builder.batch())
    IngestionPipeline.validate(batch)
    return UniversityGraphRepository(FakeGraphRepository(), batch)


@pytest.mark.parametrize(
    "program,prefix",
    [
        ("Psychology", "PSYC"),
        ("Music", "MUSC"),
        ("Accounting", "ACCT"),
        ("Law", "LAW"),
        ("Health Promotion", "HP"),
    ],
)
async def test_course_history_uses_real_graph_records_without_inferring_completion(
    program: str,
    prefix: str,
) -> None:
    context = RetrievalContext(
        program=SupportedText(
            value=program, evidence=[StudentStatement(message_index=0, quote=program)]
        )
    )
    courses = await AcademicCourseHistoryService(public_batch()).suggest(context)
    assert courses and all(c.code.startswith(prefix) for c in courses)
    assert all(c.sources for c in courses)
    assert not context.completed_courses and not context.skills


async def test_event_dates_and_offsets_survive_projection_and_parents_are_hidden() -> None:
    from trojan_compass.recommendations.feasibility import FeasibilityChecker

    class Clock:
        def now(self) -> datetime:
            return datetime(2026, 11, 14, 20, tzinfo=UTC)

    graph = public_batch()
    actions = await graph.actions_for_topics(["Psychology"])
    events = [a for a in actions if a.event]
    assert len(events) == 2
    assert all(a.event and a.event.start and a.event.start.utcoffset() is not None for a in events)
    checker = FeasibilityChecker(Clock())
    assert (
        sum(checker.check(a, RetrievalContext(), frozenset()).excluded is None for a in events) == 1
    )
    assert all("occurrence" in a.id for a in events)
    aliases = await graph.find_courses(["PSYC-100"])
    assert len(aliases) == 1 and aliases[0].course


async def test_course_examples_are_returned_only_when_collecting_course_history() -> None:
    app = create_app(
        extractor=EmptyExtractor(),
        recommendations=RetrievalSpy(),
        course_history=AcademicCourseHistoryService(public_batch()),
    )
    messages = [
        edit("direction", "Psychology"),
        edit("study_stage", "Undergraduate"),
        edit("program", "Psychology"),
        edit("work_experience"),
    ]
    with TestClient(app) as client:
        response = client.post("/api/chat", json={"messages": [m.model_dump() for m in messages]})
    assert response.status_code == 200
    result = ChatResponse.model_validate(response.json())
    assert result.information.missing_fields == ["completed_courses"]
    assert result.course_history_options[0].code == "PSYC 100"
    assert not result.recommendations


def test_import_retains_only_public_metadata_and_never_attendee_or_creator_records() -> None:
    builder = UniversityBatchBuilder(date(2026, 11, 14))
    builder.event(
        dict(
            id=1,
            title="Public music recital",
            localist_url="https://calendar.usc.edu/event/music",
            user_id="synthetic-secret",
            created_by="synthetic-secret",
            attendees=["synthetic-secret"],
            event_instances=[
                dict(event_instance=dict(id=1, start="2026-12-01T12:00:00-08:00", all_day=True))
            ],
        ),
        datetime(2026, 11, 14, tzinfo=UTC),
    )
    assert builder.skipped["all_day_no_time_claim"] == 1
    assert "synthetic-secret" not in str(builder.batch())
    assert not builder.instance_ids


async def test_explicit_full_context_skips_all_questions_without_assuming_mastery() -> None:
    text = (
        "I study Psychology as an undergraduate. I volunteered. I completed PSYC 100. I like Music."
    )
    evidence = [StudentStatement(message_index=0, quote=text)]

    class FullExtractor:
        async def extract(self, messages: list[ChatMessage]) -> RetrievalContext:
            return RetrievalContext(
                interests=[SupportedText(value="Music", evidence=evidence)],
                study_stage=SupportedText(value="Undergraduate", evidence=evidence),
                program=SupportedText(value="Psychology", evidence=evidence),
                experiences=[SupportedText(value="Volunteered", evidence=evidence)],
                completed_courses=[SupportedText(value="PSYC 100", evidence=evidence)],
            )

    spy = RetrievalSpy()
    response = await ChatService(FullExtractor(), spy).chat(
        ChatRequest(messages=[ChatMessage(role="user", content=text)])
    )
    assert response.information.ready
    assert spy.calls == 1
    assert response.suggested_replies == []
    assert "current data" in response.message


async def test_production_overlay_does_not_invent_records_absent_from_live_graph() -> None:
    graph = public_batch()
    # Recover the same synthetic shared batch with no live records behind it.
    builder = UniversityBatchBuilder(date(2026, 11, 14))
    builder.course(
        dict(prefix="PSYC", classNumber="100", name="Introduction to Psychology"),
        dict(prefix="DRNS", name="Dornsife"),
        dict(name="Psychology"),
        "20263",
    )
    live = UniversityGraphRepository(FakeGraphRepository(), decode(builder.batch()), overlay=False)
    assert await graph.find_courses(["PSYC 100"])
    assert await live.browse_actions(10) == []
    assert await live.find_courses(["PSYC 100"]) == []
    assert await live.actions_for_topics(["Psychology"]) == []


@pytest.mark.parametrize(
    "interest", ["Psychology or behavior", "Music or performance", "Law or justice"]
)
async def test_non_cs_discovery_choices_reach_actual_topic_edges(interest: str) -> None:
    from trojan_compass.exploration import ExplorationRecommendationService
    from trojan_compass.recommendations import RecommendationEngine

    graph = public_batch()
    evidence = [StudentStatement(message_index=0, quote=interest)]
    result = await ExplorationRecommendationService(RecommendationEngine(graph), graph).recommend(
        RecommendationRequest(
            context=RetrievalContext(interests=[SupportedText(value=interest, evidence=evidence)]),
            user_query="Show a course",
        )
    )
    assert result.recommendations
    assert all(r.sources for r in result.recommendations)
    assert all("CSCI" not in r.title for r in result.recommendations)


def test_intake_answers_do_not_erase_explicit_event_request() -> None:
    from trojan_compass.services import latest_search_query

    messages = [
        ChatMessage(role="user", content="Find psychology events"),
        edit("program", "Psychology"),
        edit("completed_courses"),
    ]
    assert latest_search_query(messages) == "Find psychology events"
    messages.append(ChatMessage(role="user", content="Actually show me music courses"))
    assert latest_search_query(messages) == "Actually show me music courses"


@pytest.mark.parametrize(
    "topic", ["Psychology", "Music", "Law", "Business", "Architecture", "Social work", "Chemistry"]
)
async def test_real_snapshot_has_sourced_undergraduate_paths_across_fields(topic: str) -> None:
    """Real feed coverage catches plausible-looking choices that a tiny fake misses."""
    from trojan_compass.composition import seed_repository
    from trojan_compass.exploration import ExplorationRecommendationService
    from trojan_compass.recommendations import RecommendationEngine
    from trojan_compass.university import course_number, public_snapshot

    batch = public_snapshot()
    assert batch is not None, "The reviewed public snapshot must ship with campus mode"
    graph = UniversityGraphRepository(seed_repository(), batch)
    fact = SupportedText(value=topic, evidence=[StudentStatement(message_index=0, quote=topic)])
    context = RetrievalContext(
        interests=[fact],
        program=fact,
        study_stage=SupportedText(value="Undergraduate", evidence=fact.evidence),
    )
    result = await ExplorationRecommendationService(
        RecommendationEngine(graph), graph, subjects=graph.course_subjects
    ).recommend(RecommendationRequest(context=context, user_query="Find courses"))
    assert result.recommendations
    assert any(r.kind == "course" for r in result.recommendations)
    for card in result.recommendations:
        assert card.sources and card.action_url and card.evidence_path
        if card.kind == "course":
            assert course_number(card.title) < 500
        if card.event and card.event.start:
            assert (card.event.end or card.event.start) >= datetime.now(UTC)
    events = [r for r in result.recommendations if r.kind == "event"]
    assert len({str(r.action_url) for r in events}) == len(events)


def test_real_campus_default_journey_collects_history_then_finds_intro_psychology() -> None:
    from trojan_compass.composition import RuntimeSettings, create_configured_app

    app = create_configured_app(RuntimeSettings(mode="campus"), extractor=EmptyExtractor())
    messages: list[ChatMessage] = []
    with TestClient(app) as client:
        for field, value in [
            ("direction", "Psychology"),
            ("study_stage", "Undergraduate"),
            ("program", "Psychology"),
            ("work_experience", None),
            ("completed_courses", None),
        ]:
            messages.append(edit(field, value))
            response = client.post(
                "/api/chat", json={"messages": [m.model_dump() for m in messages]}
            )
            assert response.status_code == 200
            body = ChatResponse.model_validate(response.json())
            if field != "completed_courses":
                assert not body.recommendations
            if field == "work_experience":
                assert body.course_history_options
                assert body.course_history_options[0].code.startswith("PSYC 100")
        assert body.information.ready
        assert any(r.title.startswith("PSYC 100") for r in body.recommendations)
        assert all(r.sources for r in body.recommendations)
        assert not any("CSCI" in r.title for r in body.recommendations)


@pytest.mark.parametrize("program", ["CS", "CSCI", "Computer Science", "I am studying CS"])
async def test_cs_course_history_never_falls_back_to_unrelated_departments(program: str) -> None:
    from trojan_compass.university import public_snapshot

    batch = public_snapshot()
    assert batch is not None
    graph = UniversityGraphRepository(FakeGraphRepository(), batch)
    context = RetrievalContext(
        program=SupportedText(
            value=program, evidence=[StudentStatement(message_index=0, quote=program)]
        ),
        study_stage=SupportedText(
            value="Undergraduate",
            evidence=[StudentStatement(message_index=0, quote="Undergraduate")],
        ),
    )
    choices = await AcademicCourseHistoryService(graph).suggest(context)
    assert choices
    assert all(choice.code.startswith("CSCI ") for choice in choices)
    assert len({choice.code for choice in choices}) == len(choices)
    assert all(choice.sources for choice in choices)
    assert not context.completed_courses and not context.skills


@pytest.mark.parametrize("program", [None, "", "XY", "Unmatched program", "program"])
async def test_unresolved_program_has_no_random_course_memory_aids(program: str | None) -> None:
    context = RetrievalContext(
        program=SupportedText(
            value=program, evidence=[StudentStatement(message_index=0, quote=program)]
        )
        if program
        else None
    )
    assert await AcademicCourseHistoryService(public_batch()).suggest(context) == []


async def test_short_official_department_and_study_level_are_respected() -> None:
    builder = UniversityBatchBuilder(date(2026, 11, 14))
    for prefix, number, subject in [
        ("EE", "101", "Electrical and Computer Engineering"),
        ("EE", "501", "Electrical and Computer Engineering"),
        ("ITAL", "012", "Italian"),
    ]:
        builder.course(
            dict(
                prefix=prefix,
                classNumber=number,
                name=f"{subject} example",
                fullCourseName=f"{prefix} {number}",
            ),
            dict(prefix=prefix, name="Synthetic school"),
            dict(name=subject),
            "20263",
        )
    graph = UniversityGraphRepository(FakeGraphRepository(), decode(builder.batch()))
    context = RetrievalContext(
        program=SupportedText(value="EE", evidence=[StudentStatement(message_index=0, quote="EE")]),
        study_stage=SupportedText(
            value="Undergraduate",
            evidence=[StudentStatement(message_index=0, quote="Undergraduate")],
        ),
    )
    choices = await AcademicCourseHistoryService(graph).suggest(context)
    assert [c.code for c in choices] == ["EE 101"]
