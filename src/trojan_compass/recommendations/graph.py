"""Typed read model the recommendation engine needs from the knowledge graph.

This module is the proposed boundary with the graph/ingestion owner (Abishek). His
adapter translates query-language results into these models; driver records, node
handles and query strings never cross this boundary.

Everything here describes shared campus/career knowledge. Nothing carries student
information, and the engine never writes to the graph.
"""

from collections.abc import Sequence
from datetime import datetime
from typing import Literal, Protocol

from pydantic import ConfigDict, Field, HttpUrl, model_validator

from trojan_compass.contracts import Contract, Source, Text

DestinationKind = Literal["company", "role", "team"]
Importance = Literal["core", "preferred"]
# How a campus action relates to a skill. Only "teaches" implies structured learning;
# "practices", "exposes" and "networking" are deliberately weaker claims.
ActionRelation = Literal["teaches", "practices", "exposes", "networking"]
SkillLevel = Literal["intro", "intermediate", "advanced"]
TermStatus = Literal["open", "scheduled", "closed", "unknown"]
EventStatus = Literal["scheduled", "cancelled", "postponed", "unknown"]


def _require_offset(*values: datetime | None) -> None:
    for value in values:
        if value is not None and value.utcoffset() is None:
            raise ValueError("Graph timestamps require a UTC offset")


class GraphModel(Contract):
    model_config = ConfigDict(frozen=True)


class SkillNode(GraphModel):
    id: Text
    name: Text
    aliases: list[Text] = Field(default_factory=list)

    def matches(self, name: str) -> bool:
        wanted = name.strip().casefold()
        return wanted in {self.name.casefold(), *(a.casefold() for a in self.aliases)}


class Destination(GraphModel):
    """A company, a general role, or a specific team."""

    id: Text
    kind: DestinationKind
    name: Text
    aliases: list[Text] = Field(default_factory=list)
    company: Text | None = None
    # Team -> the general role whose baseline requirements also apply.
    base_role_id: Text | None = None
    # Company -> roles the graph has evidence the company hires for.
    related_role_ids: list[Text] = Field(default_factory=list)
    sources: list[Source] = Field(default_factory=list)

    @property
    def label(self) -> str:
        if self.kind == "team" and self.company:
            return f"{self.name} team at {self.company}"
        return self.name


class Requirement(GraphModel):
    """A skill requirement declared on exactly one destination (its scope).

    Sources are mandatory: an unsupported requirement must never reach a student.
    """

    skill: SkillNode
    scope_id: Text
    importance: Importance
    statement: Text
    sources: list[Source] = Field(min_length=1)


class DirectionSuggestion(GraphModel):
    """A destination reachable from a student interest through a graph topic."""

    destination: Destination
    topic: Text
    sources: list[Source] = Field(default_factory=list)


class SkillLink(GraphModel):
    skill: SkillNode
    relation: ActionRelation
    level: SkillLevel | None = None


class Prerequisite(GraphModel):
    description: Text
    course_code: Text | None = None
    skill: SkillNode | None = None

    @model_validator(mode="after")
    def has_target(self) -> "Prerequisite":
        if self.course_code is None and self.skill is None:
            raise ValueError("A prerequisite needs a course code or a skill")
        return self


class TermOffering(GraphModel):
    term: Text
    status: TermStatus = "unknown"


class CourseInfo(GraphModel):
    code: Text
    prerequisites: list[Prerequisite] = Field(default_factory=list)
    restrictions: list[Text] = Field(default_factory=list)
    # None = offerings unknown. [] = the source lists no upcoming offering.
    offered_terms: list[TermOffering] | None = None
    modality: Text | None = None


class EventInfo(GraphModel):
    start: datetime | None = None
    end: datetime | None = None
    timezone: Text | None = None
    status: EventStatus = "unknown"
    # None = eligibility not published (never assume "open to all").
    eligibility: list[Text] | None = None
    registration_required: bool | None = None
    registration_url: HttpUrl | None = None
    registration_deadline: datetime | None = None

    @model_validator(mode="after")
    def aware(self) -> "EventInfo":
        _require_offset(self.start, self.end, self.registration_deadline)
        return self


class CampusAction(GraphModel):
    id: Text
    kind: Literal["course", "event"]
    title: Text
    summary: Text
    url: HttpUrl | None = None
    skills: list[SkillLink] = Field(default_factory=list)
    topics: list[Text] = Field(default_factory=list)
    sources: list[Source] = Field(default_factory=list)
    last_verified: datetime | None = None
    course: CourseInfo | None = None
    event: EventInfo | None = None

    @model_validator(mode="after")
    def consistent(self) -> "CampusAction":
        _require_offset(self.last_verified)
        if (self.kind == "course") != (self.course is not None):
            raise ValueError("Courses, and only courses, carry course details")
        if (self.kind == "event") != (self.event is not None):
            raise ValueError("Events, and only events, carry event details")
        return self


class GraphRepository(Protocol):
    """Read-only graph queries. Implementations keep query-language details private.

    Methods are async so graph I/O stays off the API event loop. Implementations must
    not log or cache the student-derived arguments they receive (interests, names).
    """

    async def find_destinations(
        self, name: str, kind: DestinationKind | None = None, company: str | None = None
    ) -> list[Destination]:
        """Destinations whose name or alias matches, case-insensitively."""
        ...

    async def get_destination(self, destination_id: str) -> Destination | None: ...

    async def suggest_directions(
        self, interests: Sequence[str], limit: int
    ) -> list[DirectionSuggestion]:
        """Destinations connected to interests through topics, best first."""
        ...

    async def requirements_for(self, destination_id: str) -> list[Requirement]:
        """Requirements declared on this destination only (no inheritance)."""
        ...

    async def actions_for_skills(self, skill_ids: Sequence[str]) -> list[CampusAction]: ...

    async def actions_for_topics(self, topics: Sequence[str]) -> list[CampusAction]: ...

    async def browse_actions(self, limit: int) -> list[CampusAction]:
        """Unfiltered shared actions; the engine picks broad starting points from them."""
        ...

    async def find_courses(self, references: Sequence[str]) -> list[CampusAction]:
        """Courses matching a course code or exact title."""
        ...
