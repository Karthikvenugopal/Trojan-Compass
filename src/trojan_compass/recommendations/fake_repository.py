"""In-memory ``GraphRepository`` used until the real graph adapter is ready.

It holds shared graph records only, never student data. Updates return a new repository
instead of mutating this one, which keeps concurrent requests isolated.
"""

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from trojan_compass.contracts import Source

from .graph import (
    CampusAction,
    Destination,
    DestinationKind,
    DirectionSuggestion,
    Requirement,
)


@dataclass(frozen=True)
class InterestLink:
    """Graph edge: interest topic -> destination, with the evidence for it."""

    topic: str
    destination_id: str
    aliases: tuple[str, ...] = ()
    sources: tuple[Source, ...] = ()

    def matches(self, interest: str) -> bool:
        """Whole-word match, so "ai" matches "AI ethics" but not "email"."""
        return any(
            re.search(r"\b" + re.escape(term) + r"\b", interest, re.IGNORECASE)
            for term in (self.topic, *self.aliases)
        )


@dataclass(frozen=True)
class InMemoryGraphRepository:
    destinations: tuple[Destination, ...] = ()
    requirements: tuple[Requirement, ...] = ()
    actions: tuple[CampusAction, ...] = ()
    interest_links: tuple[InterestLink, ...] = field(default_factory=tuple)

    def with_action(self, action: CampusAction) -> "InMemoryGraphRepository":
        """A copy with one action record added or replaced (simulates a graph update)."""
        kept = tuple(a for a in self.actions if a.id != action.id)
        return InMemoryGraphRepository(
            self.destinations, self.requirements, (*kept, action), self.interest_links
        )

    async def find_destinations(
        self, name: str, kind: DestinationKind | None = None, company: str | None = None
    ) -> list[Destination]:
        wanted = name.strip().casefold()
        found = [
            d
            for d in self.destinations
            if wanted in {d.name.casefold(), *(a.casefold() for a in d.aliases)}
            and (kind is None or d.kind == kind)
            and (company is None or (d.company or "").casefold() == company.strip().casefold())
        ]
        return found

    async def get_destination(self, destination_id: str) -> Destination | None:
        return next((d for d in self.destinations if d.id == destination_id), None)

    async def suggest_directions(
        self, interests: Sequence[str], limit: int
    ) -> list[DirectionSuggestion]:
        suggestions: list[DirectionSuggestion] = []
        seen: set[str] = set()
        for interest in interests:
            for link in self.interest_links:
                if link.destination_id in seen or not link.matches(interest):
                    continue
                destination = await self.get_destination(link.destination_id)
                if destination is not None:
                    seen.add(destination.id)
                    suggestions.append(
                        DirectionSuggestion(
                            destination=destination, topic=interest, sources=list(link.sources)
                        )
                    )
        return suggestions[:limit]

    async def requirements_for(self, destination_id: str) -> list[Requirement]:
        return [r for r in self.requirements if r.scope_id == destination_id]

    async def actions_for_skills(self, skill_ids: Sequence[str]) -> list[CampusAction]:
        wanted = set(skill_ids)
        return [a for a in self.actions if any(link.skill.id in wanted for link in a.skills)]

    async def actions_for_topics(self, topics: Sequence[str]) -> list[CampusAction]:
        wanted = {t.casefold() for t in topics}
        return [a for a in self.actions if wanted & {t.casefold() for t in a.topics}]

    async def browse_actions(self, limit: int) -> list[CampusAction]:
        return list(self.actions[:limit])

    async def find_courses(self, references: Sequence[str]) -> list[CampusAction]:
        wanted = {_norm(r) for r in references}
        return [
            a
            for a in self.actions
            if a.course and (_norm(a.course.code) in wanted or _norm(a.title) in wanted)
        ]


def _norm(value: str) -> str:
    return "".join(value.split()).casefold()


def build_repository(
    destinations: Iterable[Destination],
    requirements: Iterable[Requirement],
    actions: Iterable[CampusAction],
    interest_links: Iterable[InterestLink] = (),
) -> InMemoryGraphRepository:
    return InMemoryGraphRepository(
        tuple(destinations), tuple(requirements), tuple(actions), tuple(interest_links)
    )
