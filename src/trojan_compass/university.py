"""Read-only projection of shared public USC metadata; no student state is retained.

The existing KG adapter remains responsible for career/skill paths. This overlay
adds indexed public campus actions without changing either owner's implementation.
"""

import gzip
import json
import re
from collections.abc import Sequence
from datetime import UTC, datetime, time
from importlib.resources import files
from pathlib import Path

from trojan_compass.contracts import CourseHistoryOption, RetrievalContext, Source
from trojan_compass.ingestion.loaders import decode
from trojan_compass.ingestion.models import ImportBatch
from trojan_compass.recommendations.graph import (
    CampusAction,
    CourseInfo,
    Destination,
    DestinationKind,
    DirectionSuggestion,
    EventInfo,
    GraphRepository,
    Requirement,
)


def normalized(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.casefold())


def public_snapshot() -> ImportBatch | None:
    """Read shared metadata once during startup, never student input or request files."""
    resource = files("trojan_compass").joinpath("data", "university.json.gz")
    path = Path(__file__).resolve().parents[2] / "data/seed/university.json.gz"
    raw = (
        resource.read_bytes()
        if resource.is_file()
        else path.read_bytes()
        if path.is_file()
        else None
    )
    return decode(json.loads(gzip.decompress(raw))) if raw is not None else None


class UniversityGraphRepository:
    """Delegate career queries; expose sourced, dated public course/event actions."""

    def __init__(
        self, delegate: GraphRepository, batch: ImportBatch, *, overlay: bool = True
    ) -> None:
        self._delegate = delegate
        self._overlay = overlay
        self._actions: dict[str, CampusAction] = {}
        self._aliases: dict[str, list[str]] = {}
        nodes = {n.id: n for n in batch.nodes}
        topics: dict[str, list[str]] = {}
        evidence: dict[str, dict[str, Source]] = {}
        parents: dict[str, str] = {}
        for edge in batch.relationships:
            if edge.kind == "HAS_OCCURRENCE":
                parents[edge.target_id] = edge.source_id
            if edge.kind == "COVERS":
                topics.setdefault(edge.source_id, []).append(nodes[edge.target_id].name)
                source = edge.source_record
                evidence.setdefault(edge.source_id, {})[source.id] = Source(
                    url=source.url,
                    title=source.title,
                    checked_at=datetime.combine(source.checked_at, time.min, tzinfo=UTC),
                )
        self._recurring_parents = frozenset(parents.values())
        for node in batch.nodes:
            if node.kind not in ("Course", "EventOccurrence"):
                continue  # Recurring parent events must never appear as undated alternatives.
            attrs = node.attributes or {}
            parent = parents.get(node.id, node.id)
            sources = list(evidence.get(parent, {}).values())
            if not sources:
                continue
            common = dict(
                id=node.id,
                title=node.name,
                summary=str(attrs.get("summary") or node.name),
                topics=topics.get(parent, []),
                sources=sources,
                last_verified=sources[0].checked_at,
            )
            if node.kind == "Course":
                code = str(attrs["course_code"])
                restrictions = []
                for key, label in (
                    ("prerequisite_rule", "Published prerequisite rule"),
                    ("corequisite_rule", "Published corequisite rule"),
                    ("restrictions", "Published restrictions"),
                ):
                    if attrs.get(key):
                        restrictions.append(
                            f"{label}: {attrs[key]}. Confirm eligibility in the source."
                        )
                action = CampusAction(
                    **common,
                    kind="course",
                    url=str(attrs.get("course_url") or sources[0].url),
                    course=CourseInfo(code=code, restrictions=restrictions),
                )
                for alias in str(attrs.get("aliases") or code).split("|") + [node.name]:
                    self._aliases.setdefault(normalized(alias), []).append(node.id)
            else:
                start = datetime.fromisoformat(str(attrs["start"]))
                end = datetime.fromisoformat(str(attrs["end"])) if attrs.get("end") else None
                # Keep the source's actual offsets. No invented midnight for date-only listings.
                action = CampusAction(
                    **common,
                    kind="event",
                    url=str(attrs.get("event_url") or sources[0].url),
                    event=EventInfo(
                        start=start,
                        end=end,
                        timezone=start.tzname(),
                        status={
                            "active": "scheduled",
                            "cancelled": "cancelled",
                            "postponed": "postponed",
                            "unknown": "unknown",
                        }[node.status],
                    ),
                )
            self._actions[node.id] = action

    def merge(self, actions: list[CampusAction], extra: list[CampusAction]) -> list[CampusAction]:
        # Preserve existing skill relations when the same course gains catalogue metadata.
        result = {a.id: a for a in actions if a.id not in self._recurring_parents}
        for item in extra:
            old = result.get(item.id)
            if old is not None:
                if old.course is not None and item.course is not None:
                    course = item.course.model_copy(
                        update={
                            "prerequisites": old.course.prerequisites,
                            "offered_terms": old.course.offered_terms,
                            "modality": old.course.modality,
                            "restrictions": list(
                                dict.fromkeys(old.course.restrictions + item.course.restrictions)
                            ),
                        }
                    )
                    item = item.model_copy(update={"course": course})
                item = item.model_copy(
                    update={
                        "skills": old.skills or item.skills,
                        "topics": list(dict.fromkeys(old.topics + item.topics)),
                        "sources": list(
                            {str(s.url): s for s in old.sources + item.sources}.values()
                        ),
                    }
                )
            result[item.id] = item
        return list(result.values())

    async def find_destinations(
        self, name: str, kind: DestinationKind | None = None, company: str | None = None
    ) -> list[Destination]:
        return await self._delegate.find_destinations(name, kind, company)

    async def get_destination(self, destination_id: str) -> Destination | None:
        return await self._delegate.get_destination(destination_id)

    async def suggest_directions(
        self, interests: Sequence[str], limit: int
    ) -> list[DirectionSuggestion]:
        return await self._delegate.suggest_directions(interests, limit)

    async def requirements_for(self, destination_id: str) -> list[Requirement]:
        return await self._delegate.requirements_for(destination_id)

    async def actions_for_skills(self, skill_ids: Sequence[str]) -> list[CampusAction]:
        actions = await self._delegate.actions_for_skills(skill_ids)
        return self.merge(actions, [self._actions[a.id] for a in actions if a.id in self._actions])

    async def actions_for_topics(self, topics: Sequence[str]) -> list[CampusAction]:
        wanted = {normalized(t) for t in topics}
        extra = [
            a
            for a in self._actions.values()
            if wanted.intersection(normalized(t) for t in a.topics)
        ]
        base = await self._delegate.actions_for_topics(topics)
        if not self._overlay:
            extra = [self._actions[a.id] for a in base if a.id in self._actions]
        return self.merge(base, extra)

    async def browse_actions(self, limit: int) -> list[CampusAction]:
        base = await self._delegate.browse_actions(limit)
        extra = (
            list(self._actions.values())
            if self._overlay
            else [self._actions[a.id] for a in base if a.id in self._actions]
        )
        actions = self.merge(base, extra)
        # Round-robin disciplines: alphabetical catalogue order must not dictate discovery.
        buckets: dict[str, list[CampusAction]] = {}
        for action in actions:
            topic = action.topics[0] if action.topics else "Other"
            buckets.setdefault(topic, []).append(action)
        result: list[CampusAction] = []
        for index in range(max((len(b) for b in buckets.values()), default=0)):
            for bucket in buckets.values():
                if index < len(bucket):
                    result.append(bucket[index])
                    if len(result) == limit:
                        return result
        return result

    async def find_courses(self, references: Sequence[str]) -> list[CampusAction]:
        ids = {i for ref in references for i in self._aliases.get(normalized(ref), [])}
        expanded = list(references)
        for identifier in ids:
            course = self._actions[identifier].course
            if course is not None:
                expanded.append(course.code)
        base = await self._delegate.find_courses(expanded)
        extra = (
            [self._actions[i] for i in ids]
            if self._overlay
            else [self._actions[a.id] for a in base if a.id in self._actions]
        )
        return self.merge(base, extra)


class AcademicCourseHistoryService:
    """Offer real course examples as memory aids; never mark them as completed."""

    def __init__(self, graph: GraphRepository) -> None:
        self._graph = graph

    async def suggest(self, context: RetrievalContext, limit: int = 5) -> list[CourseHistoryOption]:
        actions = await self._graph.browse_actions(30_000)
        candidates = [a for a in actions if a.course and a.sources]
        query = context.program.value if context.program else ""
        terms = {
            t.casefold()
            for t in re.findall(r"[A-Za-z]{3,}", query)
            if t.casefold() not in {"major", "program", "studying", "student", "science"}
        }
        if terms:
            candidates = [
                a
                for a in candidates
                if any(t in " ".join([a.title, *a.topics]).casefold() for t in terms)
            ]
        stage = context.study_stage.value.casefold() if context.study_stage else ""
        if "undergrad" in stage or "not started" in stage:
            candidates = [
                a for a in candidates if a.course and course_number(a.course.code) < 500
            ]  # Public course numbering.
        elif "graduate" in stage:
            candidates = [a for a in candidates if a.course and course_number(a.course.code) >= 500]
        return [
            CourseHistoryOption(code=a.course.code, title=a.title, sources=a.sources[:2])
            for a in candidates[:limit]
            if a.course
        ]


def course_number(code: str) -> int:
    match = re.search(r"\d{3}", code)
    return int(match[0]) if match else 999
