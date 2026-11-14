"""Compare scoped requirements with what the student has actually said.

Rules:
- A skill the student never mentioned is ``unknown``. Unknown is not a gap.
- Completed coursework records exposure only; it never upgrades a skill to ``known``.
- Team-specific and role-baseline requirements stay separate so explanations can say
  which one a recommendation addresses.
"""

from dataclasses import dataclass, field

from trojan_compass.contracts import SkillStatus, StudentProfile

from .destination import Direction, DirectionResolution
from .graph import CampusAction, Destination, GraphRepository, Requirement, SkillNode

SCOPE_LABELS = {"team": "team-specific", "role": "role baseline", "company": "company-wide"}
# Order used when a skill is required by several scopes: most specific first.
SCOPE_ORDER = {"team": 0, "company": 1, "role": 2}


def normalize_code(value: str) -> str:
    return "".join(value.split()).casefold()


@dataclass(frozen=True)
class ScopedRequirement:
    requirement: Requirement
    destination: Destination
    via_interest: str | None = None

    @property
    def scope_label(self) -> str:
        return SCOPE_LABELS[self.destination.kind]


@dataclass(frozen=True)
class SkillAssessment:
    skill: SkillNode
    requirements: tuple[ScopedRequirement, ...]
    status: SkillStatus
    # Completed courses (as the student named them) that cover this skill.
    exposure: tuple[str, ...] = ()

    @property
    def primary(self) -> ScopedRequirement:
        return self.requirements[0]

    @property
    def is_core(self) -> bool:
        return any(r.requirement.importance == "core" for r in self.requirements)


@dataclass(frozen=True)
class Preparation:
    assessments: tuple[SkillAssessment, ...] = ()
    completed_codes: frozenset[str] = frozenset()
    limitations: tuple[str, ...] = field(default_factory=tuple)

    def by_skill(self) -> dict[str, SkillAssessment]:
        return {a.skill.id: a for a in self.assessments}


def skill_status(profile: StudentProfile, skill: SkillNode) -> SkillStatus:
    """Status the student stated for this skill (name or alias), else unknown."""
    for stated in profile.skills:
        if skill.matches(stated.name):
            return stated.status
    return "unknown"


class PreparationAnalyzer:
    def __init__(self, repository: GraphRepository) -> None:
        self._repository = repository

    async def analyze(
        self,
        resolution: DirectionResolution,
        profile: StudentProfile,
        completed_courses: list[CampusAction],
    ) -> Preparation:
        scoped: dict[str, list[ScopedRequirement]] = {}
        skills: dict[str, SkillNode] = {}
        limitations: list[str] = []

        for direction in resolution.directions:
            found = await self._collect(direction, scoped, skills, limitations)
            if not found:
                limitations.append(
                    f"The graph has no sourced requirements for {direction.label} yet, so I "
                    "can't connect it to specific campus actions."
                )

        assessments = []
        for skill_id, requirements in scoped.items():
            skill = skills[skill_id]
            requirements.sort(key=lambda r: SCOPE_ORDER[r.destination.kind])
            exposure = tuple(
                course.course.code
                for course in completed_courses
                if course.course
                and any(
                    link.skill.id == skill_id and link.relation == "teaches"
                    for link in course.skills
                )
            )
            assessments.append(
                SkillAssessment(skill, tuple(requirements), skill_status(profile, skill), exposure)
            )

        completed_codes = frozenset(normalize_code(c) for c in profile.completed_courses) | {
            normalize_code(c.course.code) for c in completed_courses if c.course
        }
        return Preparation(tuple(assessments), completed_codes, tuple(limitations))

    async def _collect(
        self,
        direction: Direction,
        scoped: dict[str, list[ScopedRequirement]],
        skills: dict[str, SkillNode],
        limitations: list[str],
    ) -> bool:
        found = False
        for destination in direction.scopes:
            requirements = await self._repository.requirements_for(destination.id)
            if destination.kind == "team" and not requirements and len(direction.scopes) > 1:
                limitations.append(
                    f"No team-specific requirements are recorded for the {destination.label}, "
                    f"so these use the {direction.scopes[1].label} baseline only. I won't "
                    "invent team requirements."
                )
            for requirement in requirements:
                found = True
                skills[requirement.skill.id] = requirement.skill
                entries = scoped.setdefault(requirement.skill.id, [])
                if all(e.destination.id != destination.id for e in entries):
                    entries.append(
                        ScopedRequirement(requirement, destination, direction.via_interest)
                    )
        return found
