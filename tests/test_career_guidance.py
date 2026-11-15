"""Synthetic students against real reviewed baselines and public campus snapshots."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from trojan_compass.career_guidance import EvidenceCareerGuide, PathLibrary
from trojan_compass.catalog import CatalogIndex
from trojan_compass.composition import RuntimeSettings, create_configured_app, seed_repository
from trojan_compass.contracts import (
    ChatMessage,
    ChatResponse,
    InformationEdit,
    RetrievalContext,
    Skill,
    StudentStatement,
    SupportedText,
    Target,
)
from trojan_compass.readiness import request_information
from trojan_compass.university import UniversityGraphRepository, public_snapshot


def evidence(quote: str = "Synthetic student statement", index: int = 0) -> list[StudentStatement]:
    return [StudentStatement(message_index=index, quote=quote)]


def context(role: str = "Data scientist") -> RetrievalContext:
    return RetrievalContext(
        target=Target(kind="role", name=role, evidence=evidence()),
        study_stage=SupportedText(value="Undergraduate", evidence=evidence()),
    )


@pytest.fixture(scope="module")
def guide() -> EvidenceCareerGuide:
    batch = public_snapshot()
    assert batch
    graph = UniversityGraphRepository(seed_repository(), batch)
    return EvidenceCareerGuide(
        graph,
        PathLibrary.load(),
        CatalogIndex.load(Path(__file__).resolve().parents[1] / "data/usc/catalog.json"),
    )


async def test_unknown_is_not_a_gap_and_courses_do_not_establish_mastery(
    guide: EvidenceCareerGuide,
) -> None:
    student = context()
    student.completed_courses = [SupportedText(value="MATH 125", evidence=evidence())]
    plan = await guide.guide(student, [])
    assert plan.mode == "plan"
    assert all(s.status == "unknown" for s in plan.skills)
    assert plan.next_question and len(plan.next_question.requested_fields) == 1
    assert plan.steps and any(a.kind == "research" for a in plan.actions)
    assert all(a.sources for a in plan.actions)
    assert all(
        a.availability == "unknown" for a in plan.actions if a.kind in ("research", "faculty")
    )
    assert any(a.kind == "faculty" for a in plan.actions)
    assert not student.skills


async def test_declared_gaps_learning_and_strengths_stay_distinct(
    guide: EvidenceCareerGuide,
) -> None:
    student = context()
    student.skills = [
        Skill(name="Mathematics", status="known", evidence=evidence()),
        Skill(name="Programming", status="not_yet_learned", evidence=evidence()),
        Skill(name="Critical Thinking", status="learning", evidence=evidence()),
    ]
    plan = await guide.guide(student, [])
    assert plan.skills[0].name == "Programming"
    assert plan.skills[0].status == "not_yet_learned"
    assert plan.skills[-1].status == "known"
    assert plan.next_question is None
    assert plan.steps[1].skill_names == ["Programming"]


async def test_evidence_builder_never_invents_unrelated_occupation_fallback(
    guide: EvidenceCareerGuide,
) -> None:
    plan = await guide.guide(RetrievalContext(), [])
    assert plan.mode == "explore" and plan.goal is None
    assert not plan.skills
    assert plan.suggested_paths == []


@pytest.mark.parametrize(
    "role",
    [
        "Graphic designer",
        "Mechanical engineer",
        "Journalist",
        "Film and video editor",
        "Environmental scientist",
        "Social science research assistant",
    ],
)
async def test_non_cs_careers_have_sourced_skill_baselines(
    guide: EvidenceCareerGuide, role: str
) -> None:
    plan = await guide.guide(context(role), [])
    assert plan.mode == "plan" and plan.skills
    assert all(s.sources for s in plan.skills)
    assert not any(s.name == "Programming" for s in plan.skills)


async def test_unknown_company_or_team_does_not_get_invented_requirements(
    guide: EvidenceCareerGuide,
) -> None:
    student = context("Synthetic company")
    assert student.target
    student.target.kind = "company"
    plan = await guide.guide(student, [])
    assert plan.mode == "coverage_gap" and not plan.skills
    assert not plan.suggested_paths


async def test_graduate_research_plan_does_not_present_undergraduate_program_as_eligible(
    guide: EvidenceCareerGuide,
) -> None:
    student = context("Journalist")
    student.study_stage = SupportedText(value="Graduate student", evidence=evidence())
    plan = await guide.guide(student, [])
    ids = {a.id for a in plan.actions if a.kind == "research"}
    assert "annenberg-masters-research" in ids
    assert "annenberg-ug-research" not in ids
    assert "dornsife-soar" not in ids


def message(field: str, value: str | None = None, status: str | None = None) -> ChatMessage:
    return ChatMessage(
        role="user",
        content=f"Update {field}: {value or status or 'None'}",
        edit=InformationEdit.model_validate(
            dict(field=field, status=status or ("provided" if value else "none"), value=value)
        ),
    )


async def test_skill_controls_are_explicit_student_facts_and_later_corrections_win(
    guide: EvidenceCareerGuide,
) -> None:
    messages = [
        message("target", "Data scientist"),
        message("skills.mathematics", "I am comfortable with Mathematics."),
    ]
    first = request_information(RetrievalContext(), messages)
    assert first.context.skills[0].status == "known"
    messages.append(message("skills.mathematics", status="unknown"))
    updated = request_information(RetrievalContext(), messages)
    assert not updated.context.skills
    plan = await guide.guide(updated.context, [])
    assert next(s for s in plan.skills if s.name == "Mathematics").status == "unknown"
    assert plan.next_question and plan.next_question.requested_fields != ["skills.mathematics"]
    messages.append(message("skills.programming", "I have not learned Programming yet."))
    final = request_information(RetrievalContext(), messages)
    plan = await guide.guide(final.context, [])
    assert plan.skills[0].status == "not_yet_learned"
    assert final.context.skills[0].evidence[0].message_index == 3


async def test_request_isolation_and_changed_direction_rebuild_the_plan(
    guide: EvidenceCareerGuide,
) -> None:
    first = await guide.guide(context(), [])
    second = await guide.guide(context("Graphic designer"), [])
    assert {s.name for s in first.skills} != {s.name for s in second.skills}
    fresh = await guide.guide(RetrievalContext(), [])
    assert fresh.mode == "explore" and not fresh.skills
    assert set(vars(guide)) == {"_graph", "_library", "_catalog"}


def test_default_http_flow_collects_minimum_then_returns_a_working_roadmap() -> None:
    class EmptyExtractor:
        async def extract(self, messages: list[ChatMessage]) -> RetrievalContext:
            return RetrievalContext()

    root = Path(__file__).resolve().parents[1]
    app = create_configured_app(
        RuntimeSettings(mode="campus", catalog_path=root / "data/usc/catalog.json"),
        extractor=EmptyExtractor(),
    )
    messages = [
        message("direction", "Data science"),
        message("study_stage", "Undergraduate"),
        message("program", "Mathematics"),
        message("work_experience"),
        message("completed_courses"),
    ]
    with TestClient(app) as client:
        before = ChatResponse.model_validate(
            client.post(
                "/api/chat", json={"messages": [m.model_dump() for m in messages[:-1]]}
            ).json()
        )
        assert not before.guidance and not before.recommendations
        messages.append(message("target", "Data scientist"))
        response = client.post("/api/chat", json={"messages": [m.model_dump() for m in messages]})
        assert response.status_code == 200
        body = ChatResponse.model_validate(response.json())
        assert body.guidance and body.guidance.mode == "plan"
        assert body.guidance.skills and body.guidance.steps
        messages.append(message("skills.mathematics", "I am learning Mathematics."))
        updated = ChatResponse.model_validate(
            client.post("/api/chat", json={"messages": [m.model_dump() for m in messages]}).json()
        )
        assert updated.guidance
        assert any(
            s.name == "Mathematics" and s.status == "learning" for s in updated.guidance.skills
        )


async def test_existing_programming_statement_is_not_reasked_as_an_unknown_alias(
    guide: EvidenceCareerGuide,
) -> None:
    student = context("Software developer")
    student.skills = [Skill(name="Programming", status="known", evidence=evidence())]
    plan = await guide.guide(student, [])
    programming = [s for s in plan.skills if "programming" in s.name.casefold()]
    assert len(programming) == 1 and programming[0].status == "known"
    assert plan.next_question
    assert "programming" not in plan.next_question.requested_fields[0]


@pytest.mark.parametrize("role", ["Architect", "Biochemist", "Musician", "Financial analyst"])
async def test_additional_disciplines_have_verified_baselines(
    guide: EvidenceCareerGuide, role: str
) -> None:
    plan = await guide.guide(context(role), [])
    assert plan.mode == "plan" and plan.skills
    assert all(s.sources for s in plan.skills)
