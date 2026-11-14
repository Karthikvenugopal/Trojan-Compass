"""Resolve where the student is heading: a named target, or directions grounded in interests."""

import re
from dataclasses import dataclass

from trojan_compass.contracts import Clarification, RetrievalContext

from .graph import Destination, GraphRepository

MAX_SUGGESTED_DIRECTIONS = 3
MAX_COMPANY_ROLES = 3
NOT_SURE = "I'm not sure"


def slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-") or "item"


@dataclass(frozen=True)
class Direction:
    """Destinations whose requirements apply together, most specific first.

    A team direction is (team, base role) so team-specific and role-baseline requirements
    stay distinguishable. ``via_interest`` is set when the direction was inferred from a
    stated interest rather than chosen by the student.
    """

    scopes: tuple[Destination, ...]
    via_interest: str | None = None

    @property
    def label(self) -> str:
        return self.scopes[0].label


@dataclass(frozen=True)
class DirectionResolution:
    directions: tuple[Direction, ...] = ()
    # Interests to explore directly when no grounded direction exists.
    topics: tuple[str, ...] = ()
    clarification: Clarification | None = None
    limitations: tuple[str, ...] = ()
    # No target and no interests: offer broad, clearly-labeled starting points instead of
    # gating every result behind a question (the student may answer "I'm not sure").
    broad: bool = False


class DestinationResolver:
    def __init__(self, repository: GraphRepository) -> None:
        self._repository = repository

    async def resolve(self, context: RetrievalContext) -> DirectionResolution:
        target = context.target
        if target is None:
            return await self._explore(context)

        matches = await self._repository.find_destinations(
            target.name, target.kind, target.company_name
        )
        if len(matches) == 1:
            return await self._expand(matches[0])

        # Unknown target: fall back to interests and ask as usual. Ambiguous target: the
        # target question below takes priority, so the fallback doesn't ask its own.
        fallback = await self._explore(context, ask=not matches)
        if not matches:
            note = (
                f'"{target.name}" isn\'t in the career graph yet, so its requirements '
                "can't be checked. I won't guess them."
            )
            return DirectionResolution(
                fallback.directions,
                fallback.topics,
                fallback.clarification,
                (note, *fallback.limitations),
                fallback.broad,
            )

        # Ambiguous: different destinations have different requirements, so the answer
        # materially changes recommendations. Interests still drive provisional results.
        options = [_option_label(m) for m in matches[:4]]
        clarification = Clarification(
            text=f'A few things in the graph match "{target.name}". Which one did you mean?',
            options=[*options, NOT_SURE],
            requested_fields=["target"],
            reason="They list different requirements, so the answer changes what I recommend.",
        )
        return DirectionResolution(
            fallback.directions,
            fallback.topics,
            clarification,
            fallback.limitations,
            fallback.broad,
        )

    async def _expand(self, destination: Destination) -> DirectionResolution:
        if destination.kind == "team":
            base = (
                await self._repository.get_destination(destination.base_role_id)
                if destination.base_role_id
                else None
            )
            scopes = (destination, base) if base else (destination,)
            return DirectionResolution((Direction(scopes),))

        if destination.kind == "role":
            return DirectionResolution((Direction((destination,)),))

        roles = [
            role
            for role_id in destination.related_role_ids[:MAX_COMPANY_ROLES]
            if (role := await self._repository.get_destination(role_id)) is not None
        ]
        if not roles:
            return DirectionResolution((Direction((destination,)),))
        directions = tuple(Direction((destination, role)) for role in roles)
        if len(roles) == 1:
            return DirectionResolution(directions)
        # Several roles at one company: show provisional results across them, and ask once.
        clarification = Clarification(
            text=f"What kind of work at {destination.name} interests you most?",
            options=[*(role.name for role in roles), NOT_SURE],
            requested_fields=["target"],
            reason="Each role needs different preparation, so this narrows the list.",
        )
        return DirectionResolution(directions, clarification=clarification)

    async def _explore(self, context: RetrievalContext, ask: bool = True) -> DirectionResolution:
        """Beginners don't need a job title: map stated interests to grounded directions."""
        interests = [interest.value for interest in context.interests]
        if not interests:
            if not ask:
                return DirectionResolution(broad=True)
            return DirectionResolution(
                broad=True,
                clarification=Clarification(
                    text=(
                        "What do you enjoy learning about or building? A subject, a hobby or "
                        "a problem you care about is enough. No job title needed."
                    ),
                    requested_fields=["interests"],
                    reason="Interests are how I find relevant courses and events.",
                ),
            )

        suggestions = await self._repository.suggest_directions(interests, MAX_SUGGESTED_DIRECTIONS)
        if not suggestions:
            return DirectionResolution(
                topics=tuple(interests),
                limitations=(
                    "No career direction in the graph connects to these interests yet, so "
                    "these are campus actions tagged with the interests themselves.",
                ),
            )

        directions = []
        for suggestion in suggestions:
            expanded = await self._expand(suggestion.destination)
            if expanded.directions:
                first = expanded.directions[0]
                directions.append(Direction(first.scopes, via_interest=suggestion.topic))

        clarification = None
        if ask and len(directions) > 1:
            names = [d.label for d in directions]
            clarification = Clarification(
                text=(
                    f"Your interests connect to a few directions: {', '.join(names)}. "
                    "Want me to focus on one? Exploring all of them is fine too."
                ),
                options=[*names, f"{NOT_SURE}, keep exploring"],
                requested_fields=["target"],
                reason="Focusing on one direction makes the next steps more specific.",
            )
        return DirectionResolution(tuple(directions), clarification=clarification)


def _option_label(destination: Destination) -> str:
    return f"{destination.label} ({destination.kind})"
