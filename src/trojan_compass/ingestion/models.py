"""Normalized import records for the campus and career graph."""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal

NodeKind = Literal[
    "Company",
    "GeneralRole",
    "Team",
    "Skill",
    "Topic",
    "Requirement",
    "Course",
    "CourseOffering",
    "Event",
    "EventOccurrence",
    "Source",
]
RelationshipKind = Literal[
    "HAS_TEAM",
    "SUPPORTS_ROLE",
    "HAS_REQUIREMENT",
    "ABOUT",
    "TEACHES",
    "COVERS",
    "HAS_PREREQUISITE",
    "INSTANCE_OF",
    "PRACTICES",
    "INTRODUCES",
    "FEATURES",
    "HAS_OCCURRENCE",
]
RecordStatus = Literal["active", "cancelled", "postponed", "unknown"]


@dataclass(frozen=True, slots=True)
class SourceRecord:
    id: str
    url: str
    title: str
    checked_at: date
    excerpt: str
    valid_from: date | None = None
    valid_until: date | None = None


@dataclass(frozen=True, slots=True)
class NodeRecord:
    id: str
    kind: NodeKind
    name: str
    status: RecordStatus = "unknown"
    attributes: dict[str, str | int | bool | date | datetime | None] | None = None


@dataclass(frozen=True, slots=True)
class RelationshipRecord:
    id: str
    kind: RelationshipKind
    source_id: str
    target_id: str
    source_record: SourceRecord
    excerpt: str
    fact_type: Literal["explicit", "inferred"] = "explicit"
    requirement_type: Literal["required", "preferred"] | None = None
    prerequisite_type: Literal["formal", "helpful"] | None = None


@dataclass(frozen=True, slots=True)
class ImportBatch:
    nodes: tuple[NodeRecord, ...]
    relationships: tuple[RelationshipRecord, ...]
    sources: tuple[SourceRecord, ...]
