"""Decode JSON and row-oriented CSV into strict typed records."""

import csv
import json
from datetime import date, datetime
from pathlib import Path
from typing import Any, cast

from trojan_compass.ingestion.models import (
    ImportBatch,
    NodeKind,
    NodeRecord,
    RecordStatus,
    RelationshipKind,
    RelationshipRecord,
    SourceRecord,
)


def load_json(path: Path) -> ImportBatch:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return decode(cast(dict[str, Any], raw))


def load_csv(path: Path) -> ImportBatch:
    with path.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    batch: dict[str, Any] = {"nodes": [], "sources": [], "relationships": []}
    for row in rows:
        record_type = row["record_type"]
        if record_type == "node":
            attributes = json.loads(row["attributes"] or "{}")
            batch["nodes"].append(
                {
                    "id": row["id"],
                    "kind": row["kind"],
                    "name": row["name"],
                    "status": row["status"] or "unknown",
                    "attributes": attributes,
                }
            )
        elif record_type == "source":
            batch["sources"].append(
                {
                    "id": row["id"],
                    "url": row["url"],
                    "title": row["title"],
                    "checked_at": row["checked_at"],
                    "excerpt": row["excerpt"],
                    "valid_from": row["valid_from"] or None,
                    "valid_until": row["valid_until"] or None,
                }
            )
        elif record_type == "relationship":
            source_id = row["evidence_source_id"]
            source = next((item for item in batch["sources"] if item["id"] == source_id), None)
            if source is None:
                raise ValueError(
                    f"CSV relationship references source not yet declared: {source_id}"
                )
            batch["relationships"].append(
                {
                    "id": row["id"],
                    "kind": row["kind"],
                    "source_id": row["source_id"],
                    "target_id": row["target_id"],
                    "source_record_id": source["id"],
                    "excerpt": row["excerpt"],
                    "fact_type": row["fact_type"] or "explicit",
                    "requirement_type": row["requirement_type"] or None,
                    "prerequisite_type": row["prerequisite_type"] or None,
                }
            )
        else:
            raise ValueError(f"Unknown record_type: {record_type}")
    return decode(batch)


def decode(raw: dict[str, Any]) -> ImportBatch:
    sources = tuple(
        SourceRecord(
            item["id"],
            item["url"],
            item["title"],
            date.fromisoformat(item["checked_at"]),
            item["excerpt"],
            _date(item.get("valid_from")),
            _date(item.get("valid_until")),
        )
        for item in raw.get("sources", [])
    )
    source_index = {item.id: item for item in sources}
    nodes = tuple(
        NodeRecord(
            item["id"],
            cast(NodeKind, item["kind"]),
            item["name"],
            cast(RecordStatus, item.get("status", "unknown")),
            _attributes(item.get("attributes", {})),
        )
        for item in raw.get("nodes", [])
    )
    edges = tuple(
        RelationshipRecord(
            item["id"],
            cast(RelationshipKind, item["kind"]),
            item["source_id"],
            item["target_id"],
            source_index[item["source_record_id"]],
            item["excerpt"],
            item.get("fact_type", "explicit"),
            item.get("requirement_type"),
            item.get("prerequisite_type"),
        )
        for item in raw.get("relationships", [])
    )
    return ImportBatch(nodes, edges, sources)


def _date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


def _attributes(value: dict[str, Any]) -> dict[str, str | int | bool | date | datetime | None]:
    converted: dict[str, str | int | bool | date | datetime | None] = {}
    for key, item in value.items():
        if isinstance(item, (str, int, bool, date, datetime)) or item is None:
            converted[key] = item
        else:
            raise ValueError(f"Unsupported attribute type for {key}; use scalar values")
    return converted
