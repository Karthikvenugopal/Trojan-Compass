"""Traverse requirement skills and interest topics to campus actions."""

from dataclasses import dataclass, field

from .graph import CampusAction, GraphRepository, SkillLink, SkillNode
from .preparation import Preparation, SkillAssessment


@dataclass(frozen=True)
class SkillMatch:
    """Destination -> requirement -> skill -> this action."""

    assessment: SkillAssessment
    link: SkillLink


@dataclass(frozen=True)
class Bridge:
    """This action builds a prerequisite the student said they haven't learned yet."""

    skill: SkillNode
    blocked: CampusAction
    # The requirement the blocked course would have served, for the evidence path.
    origin: SkillAssessment | None


@dataclass
class Candidate:
    action: CampusAction
    matches: list[SkillMatch] = field(default_factory=list)
    topics: list[str] = field(default_factory=list)
    bridges: list[Bridge] = field(default_factory=list)


class ActionRetriever:
    def __init__(self, repository: GraphRepository) -> None:
        self._repository = repository

    async def retrieve(self, preparation: Preparation, topics: tuple[str, ...]) -> list[Candidate]:
        by_skill = preparation.by_skill()
        candidates: dict[str, Candidate] = {}

        if by_skill:
            for action in await self._repository.actions_for_skills(list(by_skill)):
                matches = [
                    SkillMatch(by_skill[link.skill.id], link)
                    for link in action.skills
                    if link.skill.id in by_skill
                ]
                if matches:
                    candidates.setdefault(action.id, Candidate(action)).matches.extend(matches)

        if topics:
            wanted = {t.casefold(): t for t in topics}
            for action in await self._repository.actions_for_topics(list(topics)):
                hits = [wanted[t.casefold()] for t in action.topics if t.casefold() in wanted]
                if hits:
                    candidates.setdefault(action.id, Candidate(action)).topics.extend(hits)

        return list(candidates.values())

    async def retrieve_bridges(self, bridges: list[Bridge]) -> list[Candidate]:
        """One hop back from a blocked course to actions that teach its missing prerequisite."""
        if not bridges:
            return []
        wanted = {b.skill.id for b in bridges}
        candidates: dict[str, Candidate] = {}
        for action in await self._repository.actions_for_skills(sorted(wanted)):
            taught = {
                link.skill.id
                for link in action.skills
                if link.relation == "teaches" and link.skill.id in wanted
            }
            for bridge in bridges:
                if bridge.skill.id in taught and bridge.blocked.id != action.id:
                    candidates.setdefault(action.id, Candidate(action)).bridges.append(bridge)
        return list(candidates.values())
