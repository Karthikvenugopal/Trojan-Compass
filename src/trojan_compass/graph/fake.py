"""In-memory async adapter implementing Peri's typed GraphRepository protocol."""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from trojan_compass.contracts import Source
from trojan_compass.ingestion.models import ImportBatch, NodeRecord, RelationshipRecord
from trojan_compass.recommendations.graph import (
    CampusAction,
    CourseInfo,
    Destination,
    DestinationKind,
    DirectionSuggestion,
    EventInfo,
    GraphRepository,
    Requirement,
    SkillLink,
    SkillNode,
)


@dataclass(frozen=True, slots=True)
class InterestLink:
    topic: str
    destination_id: str
    sources: tuple[Source, ...] = ()


class FakeGraphRepository(GraphRepository):
    """Deterministic, student-data-free fake used by tests and local composition."""

    def __init__(self) -> None:
        self._destinations: dict[str, Destination] = {}
        self._requirements: dict[str, list[Requirement]] = {}
        self._actions: dict[str, CampusAction] = {}
        self._interest_links: list[InterestLink] = []

    def upsert(self, batch: ImportBatch) -> None:
        """Apply an import batch by stable IDs, mirroring Neo4j MERGE updates."""
        nodes = {node.id: node for node in batch.nodes}
        edges_by_source: dict[str, list[RelationshipRecord]] = {}
        for edge in batch.relationships:
            edges_by_source.setdefault(edge.source_id, []).append(edge)

        for node in batch.nodes:
            if node.kind not in ("Company", "GeneralRole", "Team"):
                continue
            self._destinations[node.id] = self._destination(node, batch, nodes, edges_by_source)

        for edge in batch.relationships:
            if edge.kind != "HAS_REQUIREMENT":
                continue
            destination = self._destinations.get(edge.source_id)
            requirement = nodes.get(edge.target_id)
            about = next(
                (
                    relation
                    for relation in edges_by_source.get(edge.target_id, [])
                    if relation.kind == "ABOUT"
                ),
                None,
            )
            subject = nodes.get(about.target_id) if about else None
            if destination is None or requirement is None or subject is None:
                continue
            sources = [self._source(edge, batch)]
            item = Requirement(
                skill=SkillNode(id=subject.id, name=subject.name),
                scope_id=destination.id,
                importance="core" if edge.requirement_type == "required" else "preferred",
                statement=edge.excerpt,
                sources=sources,
            )
            current = self._requirements.setdefault(destination.id, [])
            current[:] = [r for r in current if r.skill.id != item.skill.id]
            current.append(item)
            if subject.kind == "Topic":
                self._interest_links.append(
                    InterestLink(subject.name, destination.id, tuple(sources))
                )

        for node in batch.nodes:
            if node.kind not in ("Course", "CourseOffering", "Event", "EventOccurrence"):
                continue
            action = self._action(node, batch, nodes, edges_by_source)
            if action is not None:
                self._actions[action.id] = action

    async def find_destinations(
        self, name: str, kind: DestinationKind | None = None, company: str | None = None
    ) -> list[Destination]:
        wanted = name.strip().casefold()
        return [
            item
            for item in self._destinations.values()
            if wanted in {item.name.casefold(), *(a.casefold() for a in item.aliases)}
            and (kind is None or item.kind == kind)
            and (company is None or (item.company or "").casefold() == company.strip().casefold())
        ]

    async def get_destination(self, destination_id: str) -> Destination | None:
        return self._destinations.get(destination_id)

    async def suggest_directions(
        self, interests: Sequence[str], limit: int
    ) -> list[DirectionSuggestion]:
        found: list[DirectionSuggestion] = []
        seen: set[str] = set()
        for interest in interests:
            for link in self._interest_links:
                if link.destination_id in seen or not _whole_word(link.topic, interest):
                    continue
                destination = self._destinations.get(link.destination_id)
                if destination is not None:
                    seen.add(destination.id)
                    found.append(
                        DirectionSuggestion(
                            destination=destination, topic=link.topic, sources=list(link.sources)
                        )
                    )
        return found[:limit]

    async def requirements_for(self, destination_id: str) -> list[Requirement]:
        return list(self._requirements.get(destination_id, ()))

    async def actions_for_skills(self, skill_ids: Sequence[str]) -> list[CampusAction]:
        wanted = set(skill_ids)
        return [
            action
            for action in self._actions.values()
            if any(link.skill.id in wanted for link in action.skills)
        ]

    async def actions_for_topics(self, topics: Sequence[str]) -> list[CampusAction]:
        wanted = {topic.casefold() for topic in topics}
        return [
            action
            for action in self._actions.values()
            if wanted.intersection(topic.casefold() for topic in action.topics)
        ]

    async def browse_actions(self, limit: int) -> list[CampusAction]:
        """Return shared actions in stable title order for broad discovery requests."""
        actions = sorted(
            self._actions.values(), key=lambda action: (action.title.casefold(), action.id)
        )
        return actions[:limit]

    async def find_courses(self, references: Sequence[str]) -> list[CampusAction]:
        wanted = {_normalize(item) for item in references}
        return [
            action
            for action in self._actions.values()
            if action.course
            and (_normalize(action.course.code) in wanted or _normalize(action.title) in wanted)
        ]

    def with_action(self, action: CampusAction) -> "FakeGraphRepository":
        """Return an independent fake after a shared action update."""
        clone = FakeGraphRepository()
        clone._destinations = dict(self._destinations)
        clone._requirements = {key: list(items) for key, items in self._requirements.items()}
        clone._actions = {**self._actions, action.id: action}
        clone._interest_links = list(self._interest_links)
        return clone

    def _destination(
        self,
        node: NodeRecord,
        batch: ImportBatch,
        nodes: dict[str, NodeRecord],
        edges: dict[str, list[RelationshipRecord]],
    ) -> Destination:
        kinds: dict[str, DestinationKind] = {
            "Company": "company",
            "GeneralRole": "role",
            "Team": "team",
        }
        company: str | None = None
        base_role: str | None = None
        related: list[str] = []
        if node.kind == "Team":
            for company_node in nodes.values():
                if company_node.kind == "Company" and any(
                    edge.kind == "HAS_TEAM" and edge.target_id == node.id
                    for edge in edges.get(company_node.id, [])
                ):
                    company = company_node.name
            base_role = next(
                (edge.target_id for edge in edges.get(node.id, []) if edge.kind == "SUPPORTS_ROLE"),
                None,
            )
        if node.kind == "Company":
            for edge in edges.get(node.id, []):
                if edge.kind != "HAS_TEAM":
                    continue
                related.extend(
                    relation.target_id
                    for relation in edges.get(edge.target_id, [])
                    if relation.kind == "SUPPORTS_ROLE"
                )
        sources = [
            self._source(edge, batch)
            for edge in edges.get(node.id, [])
            if edge.kind in ("HAS_TEAM", "SUPPORTS_ROLE")
        ]
        return Destination(
            id=node.id,
            kind=kinds[node.kind],
            name=node.name,
            aliases=_aliases(node.attributes),
            company=company,
            base_role_id=base_role,
            related_role_ids=list(dict.fromkeys(related)),
            sources=sources,
        )

    def _action(
        self,
        node: NodeRecord,
        batch: ImportBatch,
        nodes: dict[str, NodeRecord],
        edges: dict[str, list[RelationshipRecord]],
    ) -> CampusAction | None:
        kind = "course" if node.kind in ("Course", "CourseOffering") else "event"
        parent_id = node.id
        if node.kind == "CourseOffering":
            parent_id = next(
                (edge.target_id for edge in edges.get(node.id, []) if edge.kind == "INSTANCE_OF"),
                node.id,
            )
        elif node.kind == "EventOccurrence":
            parent_id = next(
                (
                    edge.source_id
                    for edge in batch.relationships
                    if edge.kind == "HAS_OCCURRENCE" and edge.target_id == node.id
                ),
                node.id,
            )
        parent = nodes.get(parent_id, node)
        action_edges = edges.get(parent_id, [])
        skills: list[SkillLink] = []
        topics: list[str] = []
        for edge in action_edges:
            target = nodes.get(edge.target_id)
            if target is None:
                continue
            if edge.kind in ("TEACHES", "PRACTICES", "INTRODUCES") and target.kind == "Skill":
                skills.append(
                    SkillLink(
                        skill=SkillNode(id=target.id, name=target.name),
                        relation={
                            "TEACHES": "teaches",
                            "PRACTICES": "practices",
                            "INTRODUCES": "exposes",
                        }[edge.kind],
                    )
                )
            if edge.kind == "COVERS" and target.kind == "Topic":
                topics.append(target.name)
        sources = [
            self._source(edge, batch)
            for edge in action_edges
            if edge.kind in ("TEACHES", "PRACTICES", "INTRODUCES", "COVERS")
        ]
        url = sources[0].url if sources else None
        verified = sources[0].checked_at if sources else None
        if kind == "course":
            parent_attributes = parent.attributes or {}
            course_code = parent_attributes.get("course_code")
            if not isinstance(course_code, str):
                course_code = parent.id
            code = course_code
            terms = None
            if node.kind == "CourseOffering":
                attrs = node.attributes or {}
                term = attrs.get("term")
                if isinstance(term, str):
                    status = attrs.get("term_status", "unknown")
                    terms = [{"term": term, "status": status}]
            return CampusAction(
                id=node.id,
                kind="course",
                title=parent.name,
                summary=parent.name,
                url=url,
                skills=skills,
                topics=topics,
                sources=sources,
                last_verified=verified,
                course=CourseInfo(code=code, offered_terms=terms),
            )
        status = "unknown"
        if node.kind == "EventOccurrence":
            status = {
                "active": "scheduled",
                "cancelled": "cancelled",
                "postponed": "postponed",
                "unknown": "unknown",
            }[node.status]
        event_attrs = node.attributes or {}
        registration_url = event_attrs.get("registration_url")
        return CampusAction(
            id=node.id,
            kind="event",
            title=node.name,
            summary=parent.name,
            url=url,
            skills=skills,
            topics=topics,
            sources=sources,
            last_verified=verified,
            event=EventInfo(
                status=status,
                registration_url=str(registration_url) if registration_url else None,
            ),
        )

    @staticmethod
    def _source(edge: RelationshipRecord, batch: ImportBatch) -> Source:
        source = next(item for item in batch.sources if item.id == edge.source_record.id)
        from datetime import UTC, datetime, time

        checked = datetime.combine(source.checked_at, time.min, tzinfo=UTC)
        return Source(url=source.url, title=source.title, checked_at=checked)


def _whole_word(topic: str, text: str) -> bool:
    return re.search(r"\b" + re.escape(topic) + r"\b", text, re.IGNORECASE) is not None


def _normalize(value: str) -> str:
    return "".join(value.split()).casefold()


def _aliases(attributes: Mapping[str, object] | None) -> list[str]:
    value = (attributes or {}).get("aliases")
    if isinstance(value, str):
        return [part.strip() for part in value.split("|") if part.strip()]
    return []
