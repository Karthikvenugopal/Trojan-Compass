"""Regression cases found while auditing the full stateless integration."""

import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from trojan_compass.graph.timestamps import source_timestamp
from trojan_compass.ingestion.loaders import decode
from trojan_compass.ingestion.models import ImportBatch, NodeRecord
from trojan_compass.ingestion.pipeline import IngestionPipeline


class NoWrite:
    def upsert(self, batch: ImportBatch) -> None:
        pytest.fail("Invalid import reached the graph writer")


def test_student_nodes_are_rejected_before_any_graph_write() -> None:
    batch = decode({"nodes": [{"id": "synthetic", "kind": "Student", "name": "Synthetic record"}]})
    with pytest.raises(ValueError, match="only shared knowledge"):
        IngestionPipeline(NoWrite()).import_records(batch)


@pytest.mark.parametrize(
    "field,value",
    [
        ("fact_type", "made-up"),
        ("requirement_type", "made-up"),
        ("prerequisite_type", "made-up"),
    ],
)
def test_invalid_fact_classification_never_reaches_writer(field: str, value: str) -> None:
    raw = json.loads((Path(__file__).parents[1] / "data/seed/usc.json").read_text())
    raw["relationships"][0][field] = value
    with pytest.raises(ValueError):
        IngestionPipeline(NoWrite()).import_records(decode(raw))


@pytest.mark.parametrize("reserved", ["id", "kind", "name", "status"])
def test_attributes_cannot_override_graph_identity(reserved: str) -> None:
    batch = ImportBatch(
        (NodeRecord("topic", "Topic", "Synthetic", attributes={reserved: "changed"}),), (), ()
    )
    with pytest.raises(ValueError, match="reserved"):
        IngestionPipeline(NoWrite()).import_records(batch)


@pytest.mark.parametrize("value", ["2026-11-14", date(2026, 11, 14)])
def test_imported_source_date_survives_adapter_conversion(value: object) -> None:
    assert source_timestamp(value) == datetime(2026, 11, 14, tzinfo=UTC)


@pytest.mark.parametrize("value", ["not a date", "2026-11-14T12:00:00", None, 42])
def test_uncertain_source_timestamps_do_not_get_invented_timezones(value: object) -> None:
    assert source_timestamp(value) is None


def test_aware_source_timestamp_preserves_its_instant() -> None:
    stamp = datetime.fromisoformat("2026-11-14T12:00:00-08:00")
    assert source_timestamp(stamp) == stamp
    assert source_timestamp(stamp.isoformat()) == stamp
