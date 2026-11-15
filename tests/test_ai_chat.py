"""AI owns conversation decisions; deterministic boundaries enforce evidence/privacy.

All students/provider outputs here are synthetic. No live credentials are used.
"""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel

from trojan_compass.ai_chat import (
    AIChatService,
    ConversationDecision,
    GuidedAnswer,
    ResourceChoice,
    SkillChoice,
)
from trojan_compass.api import create_app
from trojan_compass.assistant import CampusAssistant
from trojan_compass.career_guidance import EvidenceCareerGuide, PathLibrary
from trojan_compass.catalog import CatalogIndex
from trojan_compass.composition import RuntimeSettings, create_configured_app, seed_repository
from trojan_compass.contracts import (
    ChatMessage,
    ChatRequest,
    Clarification,
    PlanStep,
    Recommendation,
    RecommendationRequest,
    RecommendationResult,
    RetrievalContext,
    Source,
    StudentAnswer,
    StudentStatement,
    SupportedText,
)
from trojan_compass.failures import FailureReason
from trojan_compass.llm import LLMFailure, Model, StructuredLLM
from trojan_compass.planner_wire import PlannerOutput, QuestionReview
from trojan_compass.services import ChatUnavailable
from trojan_compass.university import (
    AcademicCourseHistoryService,
    UniversityGraphRepository,
    public_snapshot,
)

Reply = BaseModel | LLMFailure | Callable[[dict[str, Any]], BaseModel]


def wire_fixture(decision: ConversationDecision) -> PlannerOutput:
    """Encode existing synthetic domain fixtures in the compact provider protocol."""
    if "target" in decision.required_fields:
        raise LLMFailure(FailureReason.SCHEMA)
    facts: list[dict[str, Any]] = []

    def add(field: str, value: str, status: str, proof: list[StudentStatement]) -> None:
        facts.append(
            {
                "field": field,
                "value": value,
                "status": status,
                "message_index": proof[0].message_index,
                "quote": proof[0].quote,
            }
        )

    context = decision.context
    for field, values in [
        ("interest", context.interests),
        ("experience", context.experiences),
        ("completed_course", context.completed_courses),
        ("goal", context.goals),
        ("preference", context.constraints.additional_preferences),
    ]:
        for item in values:
            add(field, item.value, "provided", item.evidence)
    for field in ("program", "study_stage"):
        item = getattr(context, field)
        if item is not None:
            add(field, item.value, "provided", item.evidence)
    for field in ("time_window", "modality"):
        item = getattr(context.constraints, field)
        if item is not None:
            add(field, item.value, "provided", item.evidence)
    for skill in context.skills:
        add("skills." + skill.name, skill.name, skill.status, skill.evidence)
    for answer in context.answers:
        if answer.status != "not_answered":
            add(answer.field, answer.value or answer.status, answer.status, answer.evidence)
    if context.target:
        add(
            "target." + context.target.kind,
            context.target.name,
            "provided",
            context.target.evidence,
        )
    question = decision.question
    route = decision.campus_route
    return PlannerOutput.model_validate(
        {
            "intent": route.intent if route else decision.intent,
            "facts": facts,
            "question": (
                {
                    "field": question.requested_fields[0],
                    "text": question.text,
                    "options": question.options,
                    "reason": question.reason,
                }
                if question
                else None
            ),
            "search_query": decision.search_query or (route.search_query if route else ""),
            "occupation_ids": decision.occupation_ids,
            "course_codes": route.course_codes if route else [],
            "needs_library_hours": route.needs_library_hours if route else False,
        }
    )


class FakeReasoner:
    def __init__(self, replies: list[Reply]) -> None:
        self.replies = replies
        self.payloads: list[dict[str, Any]] = []
        self.schemas: list[str] = []

    async def complete(self, system: str, user: str, schema: type[Model]) -> Model:
        self.schemas.append(schema.__name__)
        payload = json.loads(user)
        self.payloads.append(payload)
        if schema is QuestionReview and (
            not self.replies or not isinstance(self.replies[0], QuestionReview)
        ):
            # Existing orchestration fixtures explicitly model a confirming second
            # AI. Semantic-review behavior has dedicated patch fixtures below.
            return schema.model_validate(
                {
                    "next_step": "ask",
                    "question": payload["proposed_question"],
                }
            )
        reply = self.replies.pop(0)
        if isinstance(reply, LLMFailure):
            raise reply
        result = reply(payload) if callable(reply) else reply
        if schema is PlannerOutput and isinstance(result, ConversationDecision):
            result = wire_fixture(result)
        return schema.model_validate(result.model_dump())


class RetrievalSpy:
    def __init__(self) -> None:
        self.calls: list[RecommendationRequest] = []

    async def recommend(self, request: RecommendationRequest) -> RecommendationResult:
        self.calls.append(request)
        return RecommendationResult()


@pytest.fixture(scope="module")
def catalog() -> CatalogIndex:
    return CatalogIndex.load(Path(__file__).parents[1] / "data/usc/catalog.json")


def make_service(
    llm: StructuredLLM, spy: RetrievalSpy, catalog: CatalogIndex | None = None
) -> AIChatService:
    batch = public_snapshot()
    assert batch is not None
    graph = UniversityGraphRepository(seed_repository(), batch)
    library = PathLibrary.load()
    return AIChatService(
        llm,
        spy,
        library,
        EvidenceCareerGuide(graph, library, catalog),
        AcademicCourseHistoryService(graph),
        CampusAssistant(llm, catalog),
        "Fixture notice: campus records are a snapshot.",
    )


def quote(text: str, index: int = 0) -> list[StudentStatement]:
    return [StudentStatement(message_index=index, quote=text)]


def fact(value: str, text: str | None = None, index: int = 0) -> SupportedText:
    return SupportedText(value=value, evidence=quote(text or value, index))


STUDENT = (
    "I am an undergraduate studying CS. I like building apps and websites. "
    "I have no work experience. I completed CSCI 103L."
)


def prepared() -> RetrievalContext:
    return RetrievalContext(
        interests=[fact("Computer programming", "building apps and websites")],
        program=fact("CS"),
        study_stage=fact("Undergraduate", "undergraduate"),
        completed_courses=[fact("CSCI 103L", "I completed CSCI 103L.")],
        answers=[
            StudentAnswer(
                field="work_experience", status="none", evidence=quote("I have no work experience.")
            )
        ],
    )


def ask(
    field: str = "direction", text: str = "What would you enjoy trying, even just out of curiosity?"
) -> ConversationDecision:
    return ConversationDecision(
        context=RetrievalContext(),
        intent="ask",
        question=Clarification(
            text=text,
            options=["Make something", "Explore people", "I’m not sure"],
            requested_fields=[field],
            reason="Choose an initial area to explore.",
        ),
    )


def search() -> ConversationDecision:
    return ConversationDecision(
        context=prepared(),
        intent="search",
        search_query="software apps programming",
        occupation_ids=["software-developer"],
    )


def composed(payload: dict[str, Any]) -> GuidedAnswer:
    skills = payload["skills"]
    actions = payload["actions"]
    assert skills and actions
    assert all(skill["status"] == "unknown" for skill in skills)
    course = next(a for a in actions if a["kind"] == "course")
    return GuidedAnswer(
        message=(
            "Your interest in apps points toward software work. The course you reported "
            "gives us exposure to build on; it does not establish mastery."
        ),
        headline="Try software work before choosing a specialty.",
        mode="explore",
        occupations=[
            ResourceChoice(
                id="software-developer",
                why_relevant="Explore how software developers build and maintain applications.",
            )
        ],
        skills=[
            SkillChoice(
                id=skills[0]["id"],
                explanation=(
                    "This occupation source identifies a skill to discuss, not a confirmed gap."
                ),
            )
        ],
        actions=[
            ResourceChoice(
                id=course["id"],
                why_relevant="A sourced learning option to investigate for your app-building goal.",
            )
        ],
        steps=[
            PlanStep(
                id="try",
                title="Try a small app",
                description="Build a small feature and reflect on which part you enjoy.",
                action_ids=[course["id"]],
            )
        ],
        limitations=["An occupation baseline is not a company hiring requirement."],
    )


@pytest.mark.asyncio
async def test_first_turn_uses_ai_question_instead_of_a_canned_script() -> None:
    llm = FakeReasoner(
        [ask("program", "What are you studying or considering? We can start with uncertainty.")]
    )
    spy = RetrievalSpy()
    service = make_service(llm, spy)
    response = await service.chat(
        ChatRequest(messages=[ChatMessage(role="user", content="I'm not sure where to start.")])
    )
    assert response.message.startswith("What are you studying or considering?")
    assert llm.schemas == ["PlannerOutput", "QuestionReview"]
    assert not spy.calls and not response.recommendations
    assert all(field.value is None for field in response.information.fields)
    assert not response.information.ready
    assert set(vars(service)) == {
        "_llm",
        "_recommendations",
        "_library",
        "_evidence",
        "_course_history",
        "_assistant",
        "_data_notice",
        "_request_timeout",
    }


@pytest.mark.asyncio
async def test_rich_answer_skips_script_and_ai_selects_sourced_software_plan(
    catalog: CatalogIndex,
) -> None:
    llm = FakeReasoner([search(), composed])
    spy = RetrievalSpy()
    response = await make_service(llm, spy, catalog).chat(
        ChatRequest(messages=[ChatMessage(role="user", content=STUDENT)])
    )
    assert llm.schemas == ["PlannerOutput", "GuidedAnswer"]
    assert response.information.ready and len(spy.calls) == 1
    assert response.guidance and response.guidance.suggested_paths[0].title == "Software developer"
    assert not any("Mechanical" in path.title for path in response.guidance.suggested_paths)
    assert response.guidance.goal is None  # AI's proposed role never becomes a student fact.
    assert all(skill.status == "unknown" for skill in response.guidance.skills)
    assert response.guidance.actions and all(action.sources for action in response.guidance.actions)
    assert not any("CSCI 103" in action.title for action in response.guidance.actions)
    assert llm.payloads[1]["context"]["target"] is None
    assert (
        "roles" not in llm.payloads[0]
    )  # Only shared occupation evidence, no hidden student state.


@pytest.mark.asyncio
async def test_incomplete_minimum_cannot_trigger_retrieval_even_if_ai_requests_it() -> None:
    premature = ConversationDecision(
        context=RetrievalContext(), intent="search", search_query="courses"
    )
    llm = FakeReasoner([premature, premature])
    spy = RetrievalSpy()
    with pytest.raises(ChatUnavailable):
        await make_service(llm, spy).chat(
            ChatRequest(messages=[ChatMessage(role="user", content="Hi")])
        )
    assert not spy.calls and len(llm.schemas) == 2


@pytest.mark.asyncio
async def test_answered_fields_are_not_asked_again_after_validation_repair() -> None:
    ctx = prepared()
    wrong = ask("program", "What is your major?").model_copy(update={"context": ctx})
    corrected = search()
    # Validation repair receives the original conversation, not a truncated replacement.
    llm = FakeReasoner(
        [
            wrong,
            corrected,
            lambda payload: GuidedAnswer(
                message="We can compare software work with the background you shared.",
                headline="A supported direction",
                mode="explore",
            ),
        ]
    )
    spy = RetrievalSpy()
    response = await make_service(llm, spy).chat(
        ChatRequest(messages=[ChatMessage(role="user", content=STUDENT)])
    )
    assert response.message.startswith("We can compare")
    assert llm.payloads[0]["conversation"] == llm.payloads[1]["conversation"]
    assert len(spy.calls) == 1


@pytest.mark.asyncio
async def test_unknown_and_none_resolve_minimum_without_invented_facts_or_fallback_careers() -> (
    None
):
    text = (
        "I do not know my direction, stage or major. "
        "I have no work experience and no completed courses."
    )
    ctx = RetrievalContext(
        answers=[
            StudentAnswer(
                field=field,
                status="unknown" if field in {"direction", "study_stage", "program"} else "none",
                evidence=quote(text),
            )
            for field in [
                "direction",
                "study_stage",
                "program",
                "work_experience",
                "completed_courses",
            ]
        ]
    )
    decision = ConversationDecision(
        context=ctx, intent="search", search_query="general USC exploration"
    )
    llm = FakeReasoner(
        [
            decision,
            GuidedAnswer(
                message=(
                    "Your unknowns are recorded. We can explore without assigning you a career."
                ),
                headline="An open starting point",
                mode="explore",
            ),
        ]
    )
    spy = RetrievalSpy()
    response = await make_service(llm, spy).chat(
        ChatRequest(messages=[ChatMessage(role="user", content=text)])
    )
    assert response.information.ready and len(spy.calls) == 1
    assert response.guidance and not response.guidance.suggested_paths
    assert not response.guidance.skills and not response.guidance.actions
    assert llm.payloads[1]["occupations"] == []


@pytest.mark.asyncio
async def test_assistant_suggestions_cannot_be_used_as_student_evidence() -> None:
    bad = search()
    bad.context.program = fact("CS", "You should study CS", 1)
    llm = FakeReasoner([bad, bad])
    spy = RetrievalSpy()
    with pytest.raises(ChatUnavailable) as caught:
        await make_service(llm, spy).chat(
            ChatRequest(
                messages=[
                    ChatMessage(role="user", content=STUDENT.replace("CS", "film")),
                    ChatMessage(role="assistant", content="You should study CS"),
                    ChatMessage(role="user", content="What next?"),
                ]
            )
        )
    assert caught.value.reason == FailureReason.EVIDENCE
    assert not spy.calls


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad",
    [
        GuidedAnswer(
            message="Here is a resource",
            headline="Next",
            mode="plan",
            actions=[ResourceChoice(id="invented-opening", why_relevant="Invented")],
        ),
        GuidedAnswer(message="See https://invented.invalid/private", headline="Next", mode="plan"),
        GuidedAnswer(
            message="Here is a step",
            headline="Next",
            mode="plan",
            steps=[
                PlanStep(id="one", title="Next", description="Try this", action_ids=["invented"])
            ],
        ),
    ],
)
async def test_composer_cannot_publish_invented_resources_urls_or_plan_references(
    bad: GuidedAnswer,
) -> None:
    llm = FakeReasoner([search(), bad, bad])
    spy = RetrievalSpy()
    with pytest.raises(ChatUnavailable) as caught:
        await make_service(llm, spy).chat(
            ChatRequest(messages=[ChatMessage(role="user", content=STUDENT)])
        )
    assert caught.value.reason == FailureReason.EVIDENCE
    assert llm.schemas == ["PlannerOutput", "GuidedAnswer", "GuidedAnswer"]
    assert len(spy.calls) == 1


@pytest.mark.asyncio
async def test_composer_repairs_resource_ids_without_reretrieving_or_exposing_bad_output() -> None:
    invalid = GuidedAnswer(
        message="Synthetic invalid draft",
        headline="Next",
        mode="plan",
        actions=[ResourceChoice(id="invented-opening", why_relevant="Synthetic")],
    )

    def repair(payload: dict[str, Any]) -> GuidedAnswer:
        assert payload["validation_feedback"]["issue"] == "invalid_or_duplicate_resource_ids"
        assert "invented-opening" not in json.dumps(payload)
        assert payload["selection_ids"]["actions"] == [a["id"] for a in payload["actions"]]
        return composed(payload)

    llm = FakeReasoner([search(), invalid, repair])
    spy = RetrievalSpy()
    response = await make_service(llm, spy, CatalogIndex.load(Path("data/usc/catalog.json"))).chat(
        ChatRequest(messages=[ChatMessage(role="user", content=STUDENT)])
    )
    assert response.guidance and response.guidance.actions
    assert "invented-opening" not in response.model_dump_json()
    assert len(spy.calls) == 1


@pytest.mark.asyncio
async def test_unknown_optional_timeframe_survives_and_composer_cannot_reask_it() -> None:
    context = prepared()
    messages = [
        ChatMessage(role="user", content=STUDENT),
        ChatMessage(
            role="assistant", content="When would you like to start?", asked_field="time_window"
        ),
        ChatMessage(role="user", content="Unsure"),
    ]
    context.answers.append(
        StudentAnswer(
            field="time_window",
            status="unknown",
            evidence=quote("Unsure", 2),
        )
    )
    decision = search().model_copy(update={"context": context})
    repeat = GuidedAnswer(
        message="Another timing question",
        headline="Next",
        mode="plan",
        question=Clarification(
            text="When do you want an internship?",
            options=[],
            requested_fields=["time_window"],
            reason="Synthetic",
        ),
    )

    def repair(payload: dict[str, Any]) -> GuidedAnswer:
        assert payload["validation_feedback"]["issue"] == "asked_answered_field"
        field = next(f for f in payload["information"]["fields"] if f["field"] == "time_window")
        assert field["status"] == "unknown"
        return GuidedAnswer(
            message="We can explore without a fixed start date.", headline="Explore", mode="explore"
        )

    llm = FakeReasoner([decision, repeat, repair])
    spy = RetrievalSpy()
    response = await make_service(llm, spy).chat(ChatRequest(messages=messages))
    assert response.asked_field is None
    assert (
        next(f for f in response.information.fields if f.field == "time_window").status == "unknown"
    )
    assert len(spy.calls) == 1


@pytest.mark.asyncio
async def test_composition_transport_failure_is_not_retried() -> None:
    llm = FakeReasoner([search(), LLMFailure(FailureReason.NETWORK)])
    with pytest.raises(ChatUnavailable) as caught:
        await make_service(llm, RetrievalSpy()).chat(
            ChatRequest(messages=[ChatMessage(role="user", content=STUDENT)])
        )
    assert caught.value.reason == FailureReason.NETWORK
    assert llm.schemas == ["PlannerOutput", "GuidedAnswer"]


@pytest.mark.asyncio
async def test_retrieved_course_can_be_planned_without_an_occupation_and_handles_stay_local() -> (
    None
):
    rec = Recommendation(
        id="synthetic-course-101",
        kind="course",
        title="Synthetic course",
        summary="A test-only retrieved course.",
        action_url="https://example.org/course",
        sources=[Source(url="https://example.org/course", title="Synthetic source")],
        prerequisites_or_access=["Verify eligibility"],
        unknowns=["Seats unknown"],
        evidence_path=["synthetic interest", "synthetic course"],
    )

    class CourseService(RetrievalSpy):
        async def recommend(self, request: RecommendationRequest) -> RecommendationResult:
            self.calls.append(request)
            return RecommendationResult(recommendations=[rec])

    def compose_course(payload: dict[str, Any]) -> GuidedAnswer:
        assert not payload["occupations"]
        assert len(payload["actions"]) == 1
        action = payload["actions"][0]
        assert action["id"] == "a1"
        assert action["checks"] == ["Verify eligibility", "Seats unknown"]
        return GuidedAnswer(
            message="Consider the sourced course.",
            headline="Explore",
            mode="explore",
            actions=[ResourceChoice(id=action["id"], why_relevant="A sourced learning option")],
            steps=[
                PlanStep(
                    id="try",
                    title="Review",
                    description="Check the official source.",
                    action_ids=[action["id"]],
                )
            ],
        )

    decision = search().model_copy(update={"occupation_ids": []})
    llm = FakeReasoner([decision, compose_course])
    spy = CourseService()
    response = await make_service(llm, spy).chat(
        ChatRequest(messages=[ChatMessage(role="user", content=STUDENT)])
    )
    assert response.guidance
    assert response.guidance.actions[0].id == rec.id
    assert response.guidance.steps[0].action_ids == [rec.id]
    assert response.guidance.actions[0].sources == rec.sources
    assert response.guidance.actions[0].checks == ["Verify eligibility", "Seats unknown"]
    assert len(spy.calls) == 1


@pytest.mark.asyncio
async def test_request_isolation_rederives_context_for_a_fresh_student() -> None:
    llm = FakeReasoner(
        [search(), GuidedAnswer(message="Explore software", headline="Next", mode="explore"), ask()]
    )
    spy = RetrievalSpy()
    service = make_service(llm, spy)
    await service.chat(ChatRequest(messages=[ChatMessage(role="user", content=STUDENT)]))
    fresh = await service.chat(ChatRequest(messages=[ChatMessage(role="user", content="Hi")]))
    assert not fresh.information.ready and not fresh.guidance
    assert len(spy.calls) == 1
    assert llm.payloads[-1]["conversation"] == [
        {"role": "user", "content": "Hi", "edit": None, "asked_field": None, "message_index": 0}
    ]
    assert "context" not in llm.payloads[-1]


@pytest.mark.parametrize("reason", [FailureReason.AUTH, FailureReason.QUOTA, FailureReason.TIMEOUT])
def test_provider_failure_has_no_scripted_fallback_or_content_logging(
    reason: FailureReason, caplog: pytest.LogCaptureFixture
) -> None:
    llm = FakeReasoner([LLMFailure(reason)])
    spy = RetrievalSpy()
    service = make_service(llm, spy)
    app = create_app(chat_service=service)
    with TestClient(app) as client:
        response = client.post(
            "/api/chat", json={"messages": [{"role": "user", "content": "Synthetic private input"}]}
        )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == reason.value
    assert "Synthetic private input" not in response.text + caplog.text
    assert len(llm.schemas) == 1 and not spy.calls


def test_default_live_factory_uses_ai_even_for_welcome_buttons(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    llm = FakeReasoner([ask()])

    class UnusedExtractor:
        async def extract(self, messages: list[ChatMessage]) -> RetrievalContext:
            raise AssertionError("Legacy extractor must not run")

    monkeypatch.setattr(
        "trojan_compass.composition.configured_extractor", lambda: UnusedExtractor()
    )
    monkeypatch.setattr("trojan_compass.composition.configured_llm", lambda **kwargs: llm)
    app = create_configured_app(RuntimeSettings(mode="campus"), graph=seed_repository())
    with TestClient(app) as client:
        response = client.post(
            "/api/chat",
            json={"messages": [{"role": "user", "content": "I'm not sure where to start."}]},
        )
    assert response.status_code == 200 and llm.schemas == ["PlannerOutput", "QuestionReview"]
    assert response.json()["message"].startswith("What would you enjoy trying")


@pytest.mark.asyncio
async def test_reported_multiturn_programming_journey_uses_ai_selected_software(
    catalog: CatalogIndex,
) -> None:
    turns = [
        ("user", "I'm not sure where to start."),
        ("assistant", "What interests you?"),
        ("user", "Building things"),
        ("assistant", "What would you like to build?"),
        ("user", "Programming (apps or websites)"),
        ("assistant", "Tell me your study stage."),
        ("user", "Undergraduate"),
        ("assistant", "Which major are you in?"),
        ("user", "CS"),
        ("assistant", "Any work experience?"),
        ("user", "I have no experience"),
        ("assistant", "Which courses have you completed?"),
        ("user", "I have completed these courses: CSCI 102L."),
    ]
    messages = [ChatMessage.model_validate({"role": role, "content": text}) for role, text in turns]
    context = RetrievalContext(
        interests=[fact("Computer programming", "Programming (apps or websites)", 4)],
        program=fact("CS", index=8),
        study_stage=fact("Undergraduate", index=6),
        completed_courses=[fact("CSCI 102L", "I have completed these courses: CSCI 102L.", 12)],
        answers=[
            StudentAnswer(
                field="work_experience", status="none", evidence=quote("I have no experience", 10)
            )
        ],
    )
    decision = search().model_copy(update={"context": context})
    llm = FakeReasoner([decision, composed])
    spy = RetrievalSpy()
    response = await make_service(llm, spy, catalog).chat(ChatRequest(messages=messages))
    assert response.guidance and response.guidance.suggested_paths[0].id == "software-developer"
    assert llm.schemas == ["PlannerOutput", "GuidedAnswer"]
    assert len(llm.payloads[0]["conversation"]) == len(turns)
    assert spy.calls[0].context.completed_courses[0].value == "CSCI 102L"
    assert spy.calls[0].context.interests[0].value == "Computer programming"
    assert spy.calls[0].context.skills == []
    assert response.information.ready


@pytest.mark.asyncio
async def test_later_student_corrections_keep_other_constraints_and_course_history() -> None:
    from trojan_compass.contracts import Constraints, Skill

    first = STUDENT + " I know Python. I cannot attend evenings."
    correction = "Correction: I am learning Python, not proficient. I study Film now."
    context = prepared()
    context.program = fact("Film", "I study Film now.", 2)
    context.skills = [
        Skill(
            name="Python",
            status="learning",
            evidence=quote("I am learning Python, not proficient.", 2),
        )
    ]
    context.constraints = Constraints(
        additional_preferences=[fact("No evenings", "I cannot attend evenings.")]
    )
    llm = FakeReasoner(
        [
            search().model_copy(update={"context": context}),
            GuidedAnswer(
                message=(
                    "We can explore app building alongside Film "
                    "while respecting your evening constraint."
                ),
                headline="Keep your direction, revise the starting point",
                mode="explore",
            ),
        ]
    )
    spy = RetrievalSpy()
    await make_service(llm, spy).chat(
        ChatRequest(
            messages=[
                ChatMessage(role="user", content=first),
                ChatMessage(role="assistant", content="What changed?"),
                ChatMessage(role="user", content=correction),
            ]
        )
    )
    actual = spy.calls[0].context
    assert actual.program and actual.program.value == "Film"
    assert actual.skills[0].status == "learning"
    assert actual.completed_courses[0].value == "CSCI 103L"
    assert actual.constraints.additional_preferences[0].value == "No evenings"


@pytest.mark.asyncio
async def test_career_target_cannot_be_made_a_required_intake_field() -> None:
    wrong = ask().model_copy(update={"required_fields": ["target"]})
    llm = FakeReasoner([wrong, wrong])
    spy = RetrievalSpy()
    with pytest.raises(ChatUnavailable):
        await make_service(llm, spy).chat(
            ChatRequest(messages=[ChatMessage(role="user", content="Hi")])
        )
    assert not spy.calls


@pytest.mark.asyncio
async def test_ai_can_select_non_cs_direction_from_the_same_evidence_library() -> None:
    text = (
        "I am an undergraduate studying Music. I like music. "
        "I have no experience. I completed MUSC 100."
    )
    ctx = RetrievalContext(
        interests=[fact("Music", "music")],
        program=fact("Music"),
        study_stage=fact("Undergraduate", "undergraduate"),
        completed_courses=[fact("MUSC 100", "I completed MUSC 100.")],
        answers=[
            StudentAnswer(
                field="work_experience", status="none", evidence=quote("I have no experience.")
            )
        ],
    )
    decision = ConversationDecision(
        context=ctx, intent="search", search_query="music performance", occupation_ids=["musician"]
    )
    answer = GuidedAnswer(
        message="Music performance is one direction to explore with your interests.",
        headline="Explore music work",
        mode="explore",
        occupations=[
            ResourceChoice(
                id="musician",
                why_relevant="Compare this sourced occupation with the music work you enjoy.",
            )
        ],
    )
    llm = FakeReasoner([decision, answer])
    spy = RetrievalSpy()
    response = await make_service(llm, spy).chat(
        ChatRequest(messages=[ChatMessage(role="user", content=text)])
    )
    assert response.guidance and response.guidance.suggested_paths[0].id == "musician"
    assert [role["id"] for role in llm.payloads[1]["occupations"]] == ["musician"]


@pytest.mark.asyncio
async def test_factual_campus_question_uses_ai_without_requiring_career_checklist(
    catalog: CatalogIndex,
) -> None:
    from trojan_compass.assistant import CampusAnswer, RouteDecision

    decision = ConversationDecision(
        context=RetrievalContext(),
        intent="campus_question",
        campus_route=RouteDecision(
            intent="course_question",
            course_codes=["CSCI 103L"],
            search_query="What does CSCI 103L cover?",
            needs_library_hours=False,
        ),
    )

    def respond(payload: dict[str, Any]) -> CampusAnswer:
        assert payload["evidence"]
        return CampusAnswer(
            answer="The catalog lists the course as Object Oriented Programming.",
            source_ids=[payload["evidence"][0]["id"]],
            follow_ups=[],
        )

    llm = FakeReasoner([decision, respond])
    spy = RetrievalSpy()
    response = await make_service(llm, spy, catalog).chat(
        ChatRequest(messages=[ChatMessage(role="user", content="What does CSCI 103L cover?")])
    )
    assert response.sources and not spy.calls
    assert llm.schemas == ["PlannerOutput", "CampusAnswer"]


@pytest.mark.asyncio
async def test_native_local_transport_drives_both_ai_stages(catalog: CatalogIndex) -> None:
    import httpx

    from trojan_compass.ollama import OllamaStructuredLLM

    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "127.0.0.1"
        if request.url.path == "/api/show":
            return httpx.Response(200, json={"model_info": {"qwen3.context_length": 40960}})
        payload = json.loads(request.content)
        calls.append(payload["format"]["title"])
        generated = (
            wire_fixture(search())
            if payload["format"]["title"] == "PlannerOutput"
            else composed(json.loads(payload["messages"][1]["content"]))
        )
        return httpx.Response(
            200,
            json={
                "message": {"role": "assistant", "content": generated.model_dump_json()},
                "done": True,
                "done_reason": "stop",
            },
        )

    llm = OllamaStructuredLLM("qwen3:4b", transport=httpx.MockTransport(handler))
    response = await make_service(llm, RetrievalSpy(), catalog).chat(
        ChatRequest(messages=[ChatMessage(role="user", content=STUDENT)])
    )
    assert calls == ["PlannerOutput", "GuidedAnswer"]
    assert response.guidance and response.guidance.suggested_paths[0].id == "software-developer"


@pytest.mark.asyncio
async def test_ai_skill_question_and_choices_are_in_active_conversation() -> None:
    question = Clarification(
        text="Which part of writing code feels comfortable to you?",
        options=["I have tried small programs", "I am still learning", "I’m not sure"],
        requested_fields=["skills.programming"],
        reason="Prioritize a useful learning step.",
    )
    llm = FakeReasoner(
        [
            search(),
            GuidedAnswer(
                message="We can build on your course without assuming mastery.",
                headline="Check your starting point",
                mode="explore",
                question=question,
            ),
        ]
    )
    response = await make_service(llm, RetrievalSpy()).chat(
        ChatRequest(messages=[ChatMessage(role="user", content=STUDENT)])
    )
    assert question.text in response.message  # Frontend transmits message text on the next turn.
    assert response.suggested_replies == question.options


@pytest.mark.asyncio
async def test_material_graph_clarification_is_ai_written_before_showing_resources() -> None:
    class ClarifyingService(RetrievalSpy):
        async def recommend(self, request: RecommendationRequest) -> RecommendationResult:
            self.calls.append(request)
            return RecommendationResult(
                clarification=Clarification(
                    text="Graph hint about background",
                    options=[],
                    requested_fields=["background"],
                    reason="Material for this graph path.",
                )
            )

    question = Clarification(
        text="Before narrowing this path, what have you tried outside class?",
        options=["A small project", "Nothing yet", "I’m not sure"],
        requested_fields=["background"],
        reason="Preparation affects this search.",
    )
    llm = FakeReasoner(
        [
            search(),
            GuidedAnswer(
                message="I need one material detail.",
                headline="Clarify the next search",
                mode="explore",
                question=question,
            ),
        ]
    )
    response = await make_service(llm, ClarifyingService()).chat(
        ChatRequest(messages=[ChatMessage(role="user", content=STUDENT)])
    )
    assert response.message == question.text and response.suggested_replies == question.options
    assert response.guidance is None and not response.recommendations


@pytest.mark.asyncio
async def test_semantic_next_step_failure_is_not_reported_as_invalid_json_structure() -> None:
    from trojan_compass.failures import DecisionIssue

    premature = ConversationDecision(
        context=RetrievalContext(), intent="search", search_query="courses"
    )
    llm = FakeReasoner([premature, premature])
    spy = RetrievalSpy()
    with pytest.raises(ChatUnavailable) as caught:
        await make_service(llm, spy).chat(
            ChatRequest(messages=[ChatMessage(role="user", content="Hi")])
        )
    assert caught.value.reason == FailureReason.DECISION
    assert caught.value.issue == DecisionIssue.EARLY_SEARCH
    assert llm.payloads[1]["validation_feedback"]["issue"] == "minimum_not_answered"
    assert "program" in llm.payloads[1]["validation_feedback"]["unanswered_fields"]
    assert not spy.calls


@pytest.mark.asyncio
async def test_llm_review_finds_second_fact_in_a_combined_answer_without_code_aliases() -> None:
    from trojan_compass.planner_wire import PlannerQuestion, StudentFact

    # A synthetic EE example, not an abbreviation table in application code.
    messages = [
        ChatMessage(role="user", content="Help me plan"),
        ChatMessage(
            role="assistant", content="What academic level are you at?", asked_field="study_stage"
        ),
        ChatMessage(role="user", content="UG EE at USC"),
    ]
    missed = ask("program", "What is your program?")
    missed.context.study_stage = fact("Undergraduate", "UG", 2)
    reviewed = QuestionReview(
        next_step="ask",
        add_facts=[
            StudentFact(
                field="program",
                status="provided",
                value="Electrical Engineering",
                message_index=2,
                quote="EE",
            )
        ],
        question=PlannerQuestion(
            field="work_experience",
            text=(
                "You’re an undergraduate in electrical engineering. "
                "What work or project experience would you like me to consider?"
            ),
            options=["A project", "None yet", "I’m not sure"],
            reason="Understand preparation.",
        ),
    )
    llm = FakeReasoner([missed, reviewed])
    spy = RetrievalSpy()
    response = await make_service(llm, spy).chat(ChatRequest(messages=messages))
    assert llm.schemas == ["PlannerOutput", "QuestionReview"]
    assert response.asked_field == "work_experience"
    fields = {field.field: field for field in response.information.fields}
    assert fields["program"].value == "Electrical Engineering"
    assert fields["study_stage"].status == "provided"
    assert not spy.calls
    assert llm.payloads[1]["question_answer_turns"][0]["reply"] == "UG EE at USC"


@pytest.mark.asyncio
async def test_llm_review_resolves_goal_abbreviation_and_scoped_no_then_searches() -> None:
    from trojan_compass.planner_wire import StudentFact

    messages = [
        ChatMessage(role="user", content="Undergraduate in Physics. I completed PHYS 151."),
        ChatMessage(
            role="assistant",
            content="Which career would you like to explore?",
            asked_field="target",
        ),
        ChatMessage(role="user", content="swe"),
        ChatMessage(
            role="assistant",
            content="Any related software work experience?",
            asked_field="work_experience",
        ),
        ChatMessage(role="user", content="No"),
    ]
    missed = ask("target", "What is your career goal?")
    missed.context = RetrievalContext(
        program=fact("Physics", index=0),
        study_stage=fact("Undergraduate", index=0),
        completed_courses=[fact("PHYS 151", index=0)],
    )
    reviewed = QuestionReview(
        next_step="search",
        search_query="software development",
        occupation_ids=["software-developer"],
        add_facts=[
            StudentFact(
                field="target.role",
                status="provided",
                value="Software engineer",
                message_index=2,
                quote="swe",
            ),
            StudentFact(
                field="experience",
                status="provided",
                value="No related software work experience",
                message_index=4,
                quote="No",
            ),
        ],
    )
    llm = FakeReasoner(
        [
            missed,
            reviewed,
            GuidedAnswer(
                message=(
                    "Your software goal is clear. We can explore a first project "
                    "without assuming skill mastery."
                ),
                headline="A software starting point",
                mode="plan",
            ),
        ]
    )
    spy = RetrievalSpy()
    response = await make_service(llm, spy).chat(ChatRequest(messages=messages))
    assert llm.schemas == ["PlannerOutput", "QuestionReview", "GuidedAnswer"]
    assert response.information.ready and response.asked_field is None
    assert len(spy.calls) == 1
    assert spy.calls[0].context.target and spy.calls[0].context.target.name == "Software engineer"
    assert spy.calls[0].context.skills == []
    assert "related software" in spy.calls[0].context.experiences[0].value


def test_ai_extracted_target_counts_as_answered_without_reinterpreting_its_text() -> None:
    from trojan_compass.contracts import Target
    from trojan_compass.readiness import request_information

    ctx = RetrievalContext(
        target=Target(
            kind="role", name="Synthetic research role", evidence=quote("Synthetic research role")
        )
    )
    info = request_information(ctx, [ChatMessage(role="user", content="Synthetic research role")])
    assert info.answer("target").status == "provided"
    assert info.answer("direction").status == "provided"
