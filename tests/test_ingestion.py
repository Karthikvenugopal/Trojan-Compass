from datetime import date
from pathlib import Path

import pytest

from trojan_compass.graph.fake import FakeGraphRepository
from trojan_compass.ingestion.loaders import load_csv, load_json
from trojan_compass.ingestion.models import (
    ImportBatch,
    NodeRecord,
    RelationshipRecord,
    SourceRecord,
)
from trojan_compass.ingestion.pipeline import IngestionPipeline
from trojan_compass.recommendations.graph import CampusAction

SEED = Path(__file__).parents[1] / "data" / "seed" / "usc.json"
CSV_TEMPLATE = Path(__file__).parents[1] / "data" / "templates" / "import.csv"


@pytest.mark.asyncio
async def test_import_is_idempotent_and_provenance_is_returned() -> None:
    repository = FakeGraphRepository()
    pipeline = IngestionPipeline(repository)
    batch = load_json(SEED)
    pipeline.import_records(batch)
    pipeline.import_records(batch)

    result = await repository.actions_for_skills(("skill-object-oriented-programming",))
    assert len(result) == 1
    assert result[0].id == "usc-course-csci-103l"
    assert result[0].course is not None
    assert result[0].course.offered_terms is None
    assert str(result[0].sources[0].url) == "https://www.cs.usc.edu/academic-programs/courses/"
    assert result[0].last_verified is not None


@pytest.mark.asyncio
async def test_reimport_updates_action_and_cancelled_event_status() -> None:
    repository = FakeGraphRepository()
    pipeline = IngestionPipeline(repository)
    batch = load_json(SEED)
    pipeline.import_records(batch)
    updated_nodes = tuple(
        NodeRecord(
            node.id,
            node.kind,
            "Updated course title" if node.id == "usc-course-csci-103l" else node.name,
            "cancelled" if node.id == "usc-occurrence-viterbi-career-expo-2027" else node.status,
            node.attributes,
        )
        for node in batch.nodes
    )
    pipeline.import_records(ImportBatch(updated_nodes, batch.relationships, batch.sources))

    courses = await repository.find_courses(("CSCI103L",))
    assert courses[0].title == "Updated course title"
    events = await repository.actions_for_topics(("Career networking",))
    occurrence = next(
        item for item in events if item.id == "usc-occurrence-viterbi-career-expo-2027"
    )
    assert occurrence.event is not None
    assert occurrence.event.status == "cancelled"


@pytest.mark.asyncio
async def test_scoped_requirement_import_preserves_type_and_source() -> None:
    repository = FakeGraphRepository()
    IngestionPipeline(repository).import_records(load_json(SEED))

    matches = await repository.requirements_for("role-software-developer")
    assert len(matches) == 1
    assert matches[0].importance == "core"
    assert matches[0].scope_id == "role-software-developer"
    assert matches[0].skill.id == "skill-programming"
    assert str(matches[0].sources[0].url) == (
        "https://www.bls.gov/ooh/computer-and-information-technology/software-developers.htm"
    )


def test_invalid_relationship_evidence_is_rejected_before_upsert() -> None:
    class Writer:
        called = False

        def upsert(self, batch: ImportBatch) -> None:
            self.called = True

    writer = Writer()
    source = SourceRecord(
        "source", "https://example.org", "Example", date.today(), "source excerpt"
    )
    batch = ImportBatch(
        (
            NodeRecord("course", "Course", "Example course", attributes={"course_code": "EXAM101"}),
            NodeRecord("skill", "Skill", "Programming"),
        ),
        (RelationshipRecord("edge", "TEACHES", "course", "skill", source, ""),),
        (source,),
    )
    with pytest.raises(ValueError, match="supporting excerpt"):
        IngestionPipeline(writer).import_records(batch)
    assert not writer.called


def test_csv_template_imports_typed_records() -> None:
    batch = load_csv(CSV_TEMPLATE)
    assert len(batch.nodes) == 2
    assert len(batch.relationships) == 1
    IngestionPipeline(FakeGraphRepository()).import_records(batch)


@pytest.mark.asyncio
async def test_later_reads_see_immutable_shared_action_update() -> None:
    repository = FakeGraphRepository()
    IngestionPipeline(repository).import_records(load_json(SEED))
    original = (await repository.actions_for_skills(("skill-object-oriented-programming",)))[0]
    update = CampusAction.model_validate(
        {
            **original.model_dump(),
            "title": "CSCI 103L: Revised course title",
        }
    )
    updated_repository = repository.with_action(update)

    assert (await repository.find_courses(("CSCI103L",)))[0].title == original.title
    assert (await updated_repository.find_courses(("CSCI103L",)))[0].title == update.title


@pytest.mark.asyncio
async def test_browse_actions_returns_bounded_shared_records() -> None:
    repository = FakeGraphRepository()
    IngestionPipeline(repository).import_records(load_json(SEED))

    actions = await repository.browse_actions(1)

    assert len(actions) == 1
    assert actions[0].kind == "course"
