"""Supplemental exploration retains source, mastery and access safeguards."""

import pytest

from trojan_compass.composition import seed_repository
from trojan_compass.contracts import (
    RecommendationRequest,
    RecommendationResult,
    RetrievalContext,
    Skill,
    Source,
    StudentStatement,
    SupportedText,
)
from trojan_compass.exploration import ExplorationRecommendationService
from trojan_compass.recommendations.fake_repository import InMemoryGraphRepository
from trojan_compass.recommendations.graph import (
    CampusAction,
    CourseInfo,
    Prerequisite,
    SkillLink,
    SkillNode,
)


class EmptyEngine:
    async def recommend(self, request: RecommendationRequest) -> RecommendationResult:
        return RecommendationResult()


def evidence(text: str) -> list[StudentStatement]:
    return [StudentStatement(message_index=0, quote=text)]


async def test_known_coding_is_not_recommended_again_through_a_query_synonym() -> None:
    context = RetrievalContext(
        interests=[SupportedText(value="programming", evidence=evidence("programming"))],
        skills=[Skill(name="coding", status="known", evidence=evidence("I know coding"))],
    )
    service = ExplorationRecommendationService(EmptyEngine(), seed_repository())
    result = await service.recommend(
        RecommendationRequest(context=context, user_query="Programming courses")
    )
    assert result.recommendations == []
    assert "Computer programming" not in result.exploration_options
    assert result.exploration_options


@pytest.mark.parametrize("status,blocked", [("not_yet_learned", True), ("unknown", False)])
async def test_skill_search_respects_recorded_prerequisites(status: str, blocked: bool) -> None:
    from typing import cast

    from trojan_compass.contracts import SkillStatus

    skill = SkillNode(id="python", name="Python")
    taught = SkillNode(id="data-structures", name="Data structures")
    action = CampusAction(
        id="synthetic-course",
        kind="course",
        title="Synthetic data course",
        summary="Synthetic fixture",
        sources=[Source(url="https://example.invalid/course", title="Synthetic course source")],
        skills=[SkillLink(skill=taught, relation="teaches")],
        course=CourseInfo(
            code="TEST 200", prerequisites=[Prerequisite(description="Python", skill=skill)]
        ),
    )
    graph = InMemoryGraphRepository(actions=(action,))
    service = ExplorationRecommendationService(EmptyEngine(), graph)
    context = RetrievalContext(
        interests=[SupportedText(value="Data structures", evidence=evidence("Data structures"))],
        skills=[
            Skill(name="Python", status=cast(SkillStatus, status), evidence=evidence("Python"))
        ],
    )
    result = await service.recommend(
        RecommendationRequest(context=context, user_query="Data structures courses")
    )
    if blocked:
        assert result.recommendations == []
        assert result.exploration_options == []
    else:
        assert result.recommendations
        assert result.clarification
        assert result.clarification.requested_fields == ["skills.python"]
        assert any(
            "Prerequisite not confirmed" in note for note in result.recommendations[0].unknowns
        )
