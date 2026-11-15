"""Neo4j adapter for the actual async recommendation GraphRepository protocol."""

import asyncio
import logging
from collections.abc import Sequence
from typing import Any, cast

from neo4j import GraphDatabase

from trojan_compass.contracts import Source
from trojan_compass.graph.timestamps import source_timestamp
from trojan_compass.ingestion.models import ImportBatch, NodeRecord
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
    TermOffering,
)


class Neo4jGraphRepository(GraphRepository):
    """Parameterized, uncached adapter. Student-derived arguments are never logged."""

    def __init__(self, uri: str, username: str, password: str, database: str = "neo4j") -> None:
        # The Neo4j driver does not log parameters by default; disable its logger explicitly
        # so a deployment-wide logging configuration cannot accidentally expose them.
        driver_logger = logging.getLogger("neo4j")
        driver_logger.handlers.clear()
        driver_logger.addHandler(logging.NullHandler())
        driver_logger.propagate = False
        driver_logger.disabled = True
        self._driver = GraphDatabase.driver(uri, auth=(username, password))
        self._database = database

    def close(self) -> None:
        self._driver.close()

    async def ensure_schema(self) -> None:
        await asyncio.to_thread(self._ensure_schema_sync)

    def _ensure_schema_sync(self) -> None:
        statements = (
            "CREATE CONSTRAINT knowledge_id IF NOT EXISTS FOR (n:Knowledge) REQUIRE n.id IS UNIQUE",
            "CREATE CONSTRAINT source_id IF NOT EXISTS FOR (n:Source) REQUIRE n.id IS UNIQUE",
            "CREATE CONSTRAINT evidence_id IF NOT EXISTS FOR (n:Evidence) REQUIRE n.id IS UNIQUE",
            "CREATE INDEX knowledge_name IF NOT EXISTS FOR (n:Knowledge) ON (n.name)",
        )
        with self._driver.session(database=self._database) as session:
            for statement in statements:
                session.run(statement).consume()

    def upsert(self, batch: ImportBatch) -> None:
        """Atomic ID-based MERGE import; each typed edge has an Evidence node and source."""
        nodes = [
            {
                "id": item.id,
                "kind": item.kind,
                "name": item.name,
                "status": item.status,
                "attributes": _node_attributes(item),
            }
            for item in batch.nodes
        ]
        sources = [
            {
                "id": item.id,
                "url": item.url,
                "title": item.title,
                "checked_at": item.checked_at.isoformat(),
                "excerpt": item.excerpt,
                "valid_from": item.valid_from.isoformat() if item.valid_from else None,
                "valid_until": item.valid_until.isoformat() if item.valid_until else None,
            }
            for item in batch.sources
        ]
        edges = [
            {
                "id": edge.id,
                "kind": edge.kind,
                "source_id": edge.source_id,
                "target_id": edge.target_id,
                "evidence_id": edge.source_record.id,
                "evidence_record_id": f"evidence-{edge.id}",
                "excerpt": edge.excerpt,
                "fact_type": edge.fact_type,
                "requirement_type": edge.requirement_type,
                "prerequisite_type": edge.prerequisite_type,
            }
            for edge in batch.relationships
        ]
        statements = (
            (
                "UNWIND $rows AS row MERGE (n:Knowledge {id: row.id}) "
                "SET n:$(row.kind), n.kind=row.kind, n.name=row.name, "
                "n.status=row.status, n += row.attributes",
                nodes,
            ),
            ("UNWIND $rows AS row MERGE (n:Source {id: row.id}) SET n += row", sources),
            (
                "UNWIND $rows AS row "
                "OPTIONAL MATCH (:Knowledge)-[old]->(:Knowledge) WHERE old.id=row.id "
                "WITH row, collect(old) AS previous "
                "FOREACH (oldEdge IN previous | DELETE oldEdge) "
                "WITH row "
                "MATCH (a:Knowledge {id: row.source_id}), "
                "(b:Knowledge {id: row.target_id}), (s:Source {id: row.evidence_id}) "
                "MERGE (a)-[r:$(row.kind) {id: row.id}]->(b) "
                "SET r.excerpt=row.excerpt, r.fact_type=row.fact_type, "
                "r.requirement_type=row.requirement_type, "
                "r.prerequisite_type=row.prerequisite_type "
                "MERGE (ev:Evidence {id: row.evidence_record_id}) "
                "SET ev.excerpt=row.excerpt, ev.fact_type=row.fact_type "
                "WITH ev, s "
                "OPTIONAL MATCH (ev)-[old:SUPPORTED_BY]->(:Source) "
                "WITH ev, s, collect(old) AS previous "
                "FOREACH (oldSource IN previous | DELETE oldSource) "
                "MERGE (ev)-[:SUPPORTED_BY]->(s)",
                edges,
            ),
        )
        with self._driver.session(database=self._database) as session:
            with session.begin_transaction() as transaction:
                for statement, rows in statements:
                    if rows:
                        transaction.run(statement, rows=rows).consume()

    async def find_destinations(
        self, name: str, kind: DestinationKind | None = None, company: str | None = None
    ) -> list[Destination]:
        records = await asyncio.to_thread(
            self._find_destination_rows,
            "MATCH (n:Knowledge) "
            "WHERE n.kind IN ['Company','GeneralRole','Team'] "
            "AND (toLower(n.name)=toLower($name) OR any(alias IN "
            "CASE WHEN valueType(n.aliases) STARTS WITH 'STRING' "
            "THEN split(n.aliases,'|') ELSE coalesce(n.aliases,[]) END "
            "WHERE toLower(alias)=toLower($name))) "
            "AND ($kind IS NULL OR n.kind=$kind) "
            "AND ($company IS NULL OR toLower(coalesce(n.company,''))=toLower($company) "
            "OR EXISTS { MATCH (companyFilter:Knowledge)-[:HAS_TEAM]->(n) "
            "WHERE toLower(companyFilter.name)=toLower($company) }) "
            "OPTIONAL MATCH (n)-[:SUPPORTS_ROLE]->(base:Knowledge) "
            "OPTIONAL MATCH (companyNode:Knowledge)-[:HAS_TEAM]->(n) "
            "OPTIONAL MATCH (n)-[:HAS_TEAM]->(:Knowledge)-[:SUPPORTS_ROLE]->(related:Knowledge) "
            "RETURN n, base.id AS base_role_id, companyNode.name AS company_name, "
            "collect(DISTINCT related.id) AS related_role_ids",
            {"name": name, "kind": _destination_label(kind), "company": company},
        )
        return [_destination_from_row(row) for row in records]

    async def get_destination(self, destination_id: str) -> Destination | None:
        records = await asyncio.to_thread(
            self._find_destination_rows,
            "MATCH (n:Knowledge {id:$id}) "
            "WHERE n.kind IN ['Company','GeneralRole','Team'] "
            "OPTIONAL MATCH (n)-[:SUPPORTS_ROLE]->(base:Knowledge) "
            "OPTIONAL MATCH (companyNode:Knowledge)-[:HAS_TEAM]->(n) "
            "OPTIONAL MATCH (n)-[:HAS_TEAM]->(:Knowledge)-[:SUPPORTS_ROLE]->(related:Knowledge) "
            "RETURN n, base.id AS base_role_id, companyNode.name AS company_name, "
            "collect(DISTINCT related.id) AS related_role_ids",
            {"id": destination_id},
        )
        return _destination_from_row(records[0]) if records else None

    async def suggest_directions(
        self, interests: Sequence[str], limit: int
    ) -> list[DirectionSuggestion]:
        if not interests:
            return []
        records = await asyncio.to_thread(
            self._run,
            "MATCH (d:Knowledge)-[req:HAS_REQUIREMENT]->(r:Knowledge)-[:ABOUT]->(t:Knowledge) "
            "WHERE t.kind='Topic' AND any(interest IN $interests WHERE "
            "toLower(t.name)=toLower(interest) OR any(alias IN coalesce(t.aliases,[]) "
            "WHERE toLower(alias)=toLower(interest))) "
            "OPTIONAL MATCH (ev:Evidence {id:'evidence-'+req.id})-[:SUPPORTED_BY]->(s:Source) "
            "RETURN d.id AS destination_id, d.kind AS destination_kind, "
            "d.name AS destination_name, "
            "t.name AS topic, s AS source ORDER BY d.name LIMIT $limit",
            {"interests": list(interests), "limit": limit},
        )
        results: list[DirectionSuggestion] = []
        seen: set[tuple[str, str]] = set()
        for row in records:
            key = (row["destination_id"], row["topic"])
            if key in seen:
                continue
            seen.add(key)
            destination = await self.get_destination(row["destination_id"])
            if destination is None:
                continue
            sources = [_source_from_node(row["source"])] if row["source"] else []
            results.append(
                DirectionSuggestion(destination=destination, topic=row["topic"], sources=sources)
            )
        return results[:limit]

    async def requirements_for(self, destination_id: str) -> list[Requirement]:
        records = await asyncio.to_thread(
            self._run,
            "MATCH (d:Knowledge {id:$id})-[req:HAS_REQUIREMENT]->(r:Knowledge) "
            "-[:ABOUT]->(skill:Knowledge) WHERE skill.kind='Skill' "
            "OPTIONAL MATCH (ev:Evidence {id:'evidence-'+req.id})-[:SUPPORTED_BY]->(s:Source) "
            "RETURN skill, req.requirement_type AS requirement_type, req.excerpt AS statement, "
            "collect(DISTINCT s) AS sources",
            {"id": destination_id},
        )
        return [
            Requirement(
                skill=SkillNode(id=row["skill"]["id"], name=row["skill"]["name"]),
                scope_id=destination_id,
                importance=("core" if row["requirement_type"] == "required" else "preferred"),
                statement=row["statement"],
                sources=[_source_from_node(source) for source in row["sources"] if source],
            )
            for row in records
        ]

    async def actions_for_skills(self, skill_ids: Sequence[str]) -> list[CampusAction]:
        if not skill_ids:
            return []
        return await self._actions({"skill_ids": list(skill_ids), "topic_names": None})

    async def actions_for_topics(self, topics: Sequence[str]) -> list[CampusAction]:
        if not topics:
            return []
        return await self._actions({"skill_ids": None, "topic_names": list(topics)})

    async def browse_actions(self, limit: int) -> list[CampusAction]:
        """Return a stable, bounded selection of shared actions for broad requests."""
        if limit <= 0:
            return []
        actions = await self._actions({"skill_ids": None, "topic_names": None, "references": None})
        return sorted(actions, key=lambda action: (action.title.casefold(), action.id))[:limit]

    async def find_courses(self, references: Sequence[str]) -> list[CampusAction]:
        if not references:
            return []
        return await self._actions({"references": list(references)})

    async def _actions(self, parameters: dict[str, object]) -> list[CampusAction]:
        records = await asyncio.to_thread(
            self._run,
            "MATCH (a:Knowledge) WHERE a.kind IN "
            "['Course','CourseOffering','Event','EventOccurrence'] "
            "OPTIONAL MATCH (a)-[:INSTANCE_OF]->(course:Knowledge) "
            "OPTIONAL MATCH (parentEvent:Knowledge)-[:HAS_OCCURRENCE]->(a) "
            "CALL { WITH a, course, parentEvent "
            "MATCH (a)-[edge]->(target:Knowledge) "
            "WHERE type(edge) IN ['TEACHES','COVERS','PRACTICES','INTRODUCES'] "
            "RETURN edge, target "
            "UNION WITH a, course, parentEvent "
            "MATCH (a)-[:INSTANCE_OF]->(course)-[edge]->(target:Knowledge) "
            "WHERE a.kind='CourseOffering' "
            "AND type(edge) IN ['TEACHES','COVERS','PRACTICES','INTRODUCES'] "
            "RETURN edge, target "
            "UNION WITH a, course, parentEvent "
            "MATCH (parentEvent)-[edge]->(target:Knowledge) "
            "WHERE a.kind='EventOccurrence' "
            "AND type(edge) IN ['COVERS','PRACTICES','INTRODUCES'] "
            "RETURN edge, target } "
            "WITH a, course, parentEvent, edge, target "
            "WHERE ($skill_ids IS NULL OR target.id IN $skill_ids) "
            "AND ($topic_names IS NULL OR (target.kind='Topic' AND any(topic IN $topic_names "
            "WHERE toLower(topic)=toLower(target.name)))) "
            "AND ($references IS NULL OR (a.kind IN ['Course','CourseOffering'] AND "
            "any(ref IN $references WHERE replace(toLower(ref),' ','')="
            "replace(toLower(coalesce(course.name,a.name)),' ','') "
            "OR replace(toLower(ref),' ','')="
            "replace(toLower(coalesce(course.course_code,course.code,"
            "a.course_code,a.code,'')),' ',''))) ) "
            "OPTIONAL MATCH (ev:Evidence {id:'evidence-'+edge.id})-[:SUPPORTED_BY]->(s:Source) "
            "RETURN a, course, parentEvent, edge, target, s "
            "ORDER BY a.name",
            {"skill_ids": None, "topic_names": None, "references": None} | parameters,
        )
        grouped: dict[str, dict[str, Any]] = {}
        for row in records:
            action = row["a"]
            key = action["id"]
            entry = grouped.setdefault(
                key,
                {
                    "action": action,
                    "course": row["course"],
                    "parent_event": row["parentEvent"],
                    "skills": {},
                    "topics": set(),
                    "sources": {},
                },
            )
            target = row["target"]
            if target["kind"] == "Skill":
                relation = {
                    "TEACHES": "teaches",
                    "PRACTICES": "practices",
                    "INTRODUCES": "exposes",
                }.get(row["edge"].type)
                if relation:
                    link = SkillLink(
                        skill=SkillNode(id=target["id"], name=target["name"]),
                        relation=relation,
                    )
                    entry["skills"][link.skill.id] = link
            elif target["kind"] == "Topic" and row["edge"].type == "COVERS":
                entry["topics"].add(target["name"])
            if row["s"] is not None:
                source = _source_from_node(row["s"])
                entry["sources"][str(source.url)] = source
        return [_action_from_entry(entry) for entry in grouped.values()]

    def _find_destination_rows(self, query: str, parameters: dict[str, object]) -> list[Any]:
        return self._run(query, parameters)

    def _run(self, query: str, parameters: dict[str, object]) -> list[Any]:
        with self._driver.session(database=self._database) as session:
            return list(session.run(query, parameters))


def _destination_label(kind: DestinationKind | None) -> str | None:
    if kind is None:
        return None
    return {"company": "Company", "role": "GeneralRole", "team": "Team"}[kind]


def _destination_from_row(row: Any) -> Destination:
    node = row["n"]
    kind = {"Company": "company", "GeneralRole": "role", "Team": "team"}[node["kind"]]
    aliases = node.get("aliases", [])
    return Destination(
        id=node["id"],
        kind=cast(DestinationKind, kind),
        name=node["name"],
        aliases=[part.strip() for part in aliases.split("|") if part.strip()]
        if isinstance(aliases, str)
        else list(aliases)
        if isinstance(aliases, list)
        else [],
        company=row["company_name"],
        base_role_id=row["base_role_id"],
        related_role_ids=[item for item in row["related_role_ids"] if item],
    )


def _source_from_node(node: Any) -> Source:
    checked = source_timestamp(node.get("checked_at"))
    return Source(url=node["url"], title=node["title"], checked_at=checked)


def _action_from_entry(entry: dict[str, Any]) -> CampusAction:
    action = entry["action"]
    course = entry["course"]
    event_parent = entry["parent_event"]
    attrs = dict(action)
    if course is not None:
        attrs = dict(course)
    elif event_parent is not None:
        attrs = dict(event_parent)

    skills = list(entry["skills"].values())
    topics = sorted(entry["topics"])
    sources = list(entry["sources"].values())
    url = sources[0].url if sources else None
    verified = max((source.checked_at for source in sources if source.checked_at), default=None)
    if action["kind"] in ("Course", "CourseOffering"):
        code = attrs.get("course_code") or attrs.get("code") or attrs.get("id")
        if not isinstance(code, str):
            code = action["id"]
        offered_terms: list[TermOffering] | None = None
        term = action.get("term")
        if term:
            status = action.get("term_status", "unknown")
            if status not in ("open", "scheduled", "closed", "unknown"):
                status = "unknown"
            offered_terms = [TermOffering(term=str(term), status=status)]
        return CampusAction(
            id=action["id"],
            kind="course",
            title=attrs.get("name", action["name"]),
            summary=attrs.get("summary", attrs.get("name", action["name"])),
            url=url,
            skills=skills,
            topics=topics,
            sources=sources,
            last_verified=verified,
            course=CourseInfo(code=code, offered_terms=offered_terms),
        )
    event_status = action.get("status", "unknown")
    event_status = {
        "active": "scheduled",
        "scheduled": "scheduled",
        "cancelled": "cancelled",
        "postponed": "postponed",
        "unknown": "unknown",
    }.get(event_status, "unknown")
    event = EventInfo(
        status=event_status,
        registration_url=action.get("registration_url"),
    )
    return CampusAction(
        id=action["id"],
        kind="event",
        title=action["name"],
        summary=attrs.get("summary", attrs.get("name", action["name"])),
        url=url,
        skills=skills,
        topics=topics,
        sources=sources,
        last_verified=verified,
        event=event,
    )


def _node_attributes(node: NodeRecord) -> dict[str, object]:
    attributes: dict[str, object] = dict(node.attributes or {})
    aliases = attributes.get("aliases")
    if isinstance(aliases, str):
        attributes["aliases"] = [part.strip() for part in aliases.split("|") if part.strip()]
    return attributes
