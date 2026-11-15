"""Actual Neo4j queries in CI; public seed and clearly synthetic shared graph facts only."""

import asyncio
import os
from datetime import date
from pathlib import Path

import pytest

from trojan_compass.contracts import (
    RecommendationRequest,
    RetrievalContext,
    StudentStatement,
    Target,
)
from trojan_compass.ingestion.loaders import load_json
from trojan_compass.ingestion.models import (
    ImportBatch,
    NodeRecord,
    RelationshipRecord,
    SourceRecord,
)
from trojan_compass.ingestion.pipeline import IngestionPipeline
from trojan_compass.recommendations import RecommendationEngine

pytestmark = pytest.mark.skipif(
    os.getenv("COMPASS_TEST_NEO4J") != "1", reason="Requires CI Neo4j service"
)


@pytest.mark.asyncio
async def test_actual_seed_queries_source_dates_and_recommendations() -> None:
    from trojan_compass.graph.neo4j_adapter import Neo4jGraphRepository

    repository = Neo4jGraphRepository("bolt://127.0.0.1:7687", "neo4j", "integration-test-only")
    try:
        await repository.ensure_schema()
        batch = load_json(Path(__file__).parents[1] / "data/seed/usc.json")
        await asyncio.to_thread(IngestionPipeline(repository).import_records, batch)
        courses = await repository.find_courses(["CSCI103L"])
        assert any(course.id == "usc-course-csci-103l" for course in courses)
        assert all(source.checked_at for course in courses for source in course.sources)
        targets = await repository.find_destinations("Software developer", "role")
        assert len(targets) == 1
        result = await RecommendationEngine(repository).recommend(
            RecommendationRequest(
                context=RetrievalContext(
                    target=Target(
                        kind="role",
                        name="Software developer",
                        evidence=[StudentStatement(message_index=0, quote="Software developer")],
                    )
                ),
                user_query="Synthetic request for Software developer courses",
            )
        )
        assert any(rec.id == "usc-course-csci-103l" for rec in result.recommendations)
        assert all(rec.sources and rec.evidence_path for rec in result.recommendations)
    finally:
        await asyncio.to_thread(repository.close)


@pytest.mark.asyncio
async def test_actual_offerings_and_imported_aliases() -> None:
    from trojan_compass.graph.neo4j_adapter import Neo4jGraphRepository

    repository = Neo4jGraphRepository("bolt://127.0.0.1:7687", "neo4j", "integration-test-only")
    source = SourceRecord(
        "fixture-source",
        "https://example.org/fixture",
        "Synthetic fixture",
        date(2026, 11, 14),
        "Synthetic shared knowledge for integration testing",
    )
    nodes = (
        NodeRecord(
            "fixture-course", "Course", "Synthetic course", attributes={"course_code": "SYN 101"}
        ),
        NodeRecord(
            "fixture-offering",
            "CourseOffering",
            "Synthetic offering",
            attributes={"term": "Synthetic term", "term_status": "open"},
        ),
        NodeRecord("fixture-skill", "Skill", "Synthetic skill"),
        NodeRecord(
            "fixture-role",
            "GeneralRole",
            "Synthetic role",
            attributes={"aliases": "Synthetic alias|Other synthetic alias"},
        ),
    )
    edges = (
        RelationshipRecord(
            "fixture-teaches",
            "TEACHES",
            "fixture-course",
            "fixture-skill",
            source,
            "Synthetic teaching relation",
        ),
        RelationshipRecord(
            "fixture-instance",
            "INSTANCE_OF",
            "fixture-offering",
            "fixture-course",
            source,
            "Synthetic offering relation",
        ),
    )
    try:
        await repository.ensure_schema()
        await asyncio.to_thread(
            IngestionPipeline(repository).import_records, ImportBatch(nodes, edges, (source,))
        )
        targets = await repository.find_destinations("Synthetic alias", "role")
        assert len(targets) == 1
        assert "Synthetic alias" in targets[0].aliases
        actions = await repository.actions_for_skills(["fixture-skill"])
        offering = next(action for action in actions if action.id == "fixture-offering")
        assert offering.course and offering.course.offered_terms
        assert offering.course.offered_terms[0].term == "Synthetic term"
        assert offering.course.offered_terms[0].status == "open"
    finally:
        await asyncio.to_thread(repository.close)
