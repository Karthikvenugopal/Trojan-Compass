"""Import → extract → normalize → deduplicate → validate → upsert stages."""

from dataclasses import replace
from typing import Protocol

from trojan_compass.ingestion.models import (
    ImportBatch,
    NodeRecord,
    RelationshipRecord,
    SourceRecord,
)


class ImportWriter(Protocol):
    def upsert(self, batch: ImportBatch) -> None: ...


class IngestionPipeline:
    """Accept only validated shared facts and preserve each edge's supporting excerpt."""

    ALLOWED_KINDS = {
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
    }
    ENDPOINTS = {
        "HAS_TEAM": ({"Company"}, {"Team"}),
        "SUPPORTS_ROLE": ({"Team"}, {"GeneralRole"}),
        "HAS_REQUIREMENT": ({"Company", "GeneralRole", "Team"}, {"Requirement"}),
        "ABOUT": ({"Requirement"}, {"Skill", "Topic"}),
        "TEACHES": ({"Course"}, {"Skill"}),
        "COVERS": ({"Course", "Event"}, {"Topic"}),
        "HAS_PREREQUISITE": ({"Course"}, {"Course", "Skill"}),
        "INSTANCE_OF": ({"CourseOffering"}, {"Course"}),
        "PRACTICES": ({"Event"}, {"Skill"}),
        "INTRODUCES": ({"Event"}, {"Skill"}),
        "FEATURES": ({"Event", "EventOccurrence"}, {"Company", "Team"}),
        "HAS_OCCURRENCE": ({"Event"}, {"EventOccurrence"}),
    }

    def __init__(self, writer: ImportWriter) -> None:
        self._writer = writer

    def import_records(self, batch: ImportBatch) -> None:
        extracted = self.extract(batch)
        normalized = self.normalize(extracted)
        deduplicated = self.deduplicate(normalized)
        self.validate(deduplicated)
        self._writer.upsert(deduplicated)

    @staticmethod
    def extract(batch: ImportBatch) -> ImportBatch:
        """Structured imports are already extracted; an LLM extractor may implement this seam."""
        return batch

    @staticmethod
    def normalize(batch: ImportBatch) -> ImportBatch:
        nodes = tuple(replace(node, name=" ".join(node.name.split())) for node in batch.nodes)
        return replace(batch, nodes=nodes)

    @staticmethod
    def deduplicate(batch: ImportBatch) -> ImportBatch:
        # IDs are source-independent stable keys; last record wins within one upload.
        nodes = {item.id: item for item in batch.nodes}
        sources = {item.id: item for item in batch.sources}
        relationships = {item.id: item for item in batch.relationships}
        return ImportBatch(
            tuple(nodes.values()), tuple(relationships.values()), tuple(sources.values())
        )

    @classmethod
    def validate(cls, batch: ImportBatch) -> None:
        node_ids = {item.id for item in batch.nodes} | {item.id for item in batch.sources}
        node_index = {item.id: item for item in batch.nodes}
        if len(node_ids) != len(batch.nodes) + len(batch.sources):
            raise ValueError("Node and source IDs must be unique")
        for node in batch.nodes:
            if not node.id.strip() or not node.name.strip():
                raise ValueError("Node IDs and names must be non-empty")
            if node.kind == "CourseOffering" and not node.attributes:
                raise ValueError("CourseOffering must include term or dates in attributes")
            if node.kind == "Course" and not (node.attributes or {}).get("course_code"):
                raise ValueError("Course identity must include its explicit course_code")
            if node.kind == "EventOccurrence" and not node.attributes:
                raise ValueError("EventOccurrence must include occurrence dates or status")
            if node.status not in ("active", "cancelled", "postponed", "unknown"):
                raise ValueError(f"Unsupported status for node {node.id}: {node.status}")
        for source in batch.sources:
            if not source.url.startswith(("https://", "http://")) or not source.excerpt.strip():
                raise ValueError("Sources need an HTTP(S) URL and supporting excerpt")
        for edge in batch.relationships:
            if edge.kind not in cls.ALLOWED_KINDS:
                raise ValueError(f"Unsupported relationship type: {edge.kind}")
            if edge.source_id not in node_ids or edge.target_id not in node_ids:
                raise ValueError("Relationship endpoints must exist in this batch")
            if edge.source_id not in node_index or edge.target_id not in node_index:
                raise ValueError("Relationship endpoints must be graph nodes, not sources")
            allowed_sources, allowed_targets = cls.ENDPOINTS[edge.kind]
            if (
                node_index[edge.source_id].kind not in allowed_sources
                or node_index[edge.target_id].kind not in allowed_targets
            ):
                raise ValueError(f"Invalid endpoint kinds for relationship {edge.kind}")
            if edge.source_record.id not in {source.id for source in batch.sources}:
                raise ValueError("Relationship evidence source must be included in the batch")
            if not edge.excerpt.strip():
                raise ValueError("Every relationship requires a supporting excerpt")
            if edge.kind == "FEATURES" and edge.fact_type != "explicit":
                raise ValueError(
                    "Event/company or event/team FEATURES edges require explicit evidence"
                )
            if edge.kind == "HAS_REQUIREMENT" and edge.requirement_type is None:
                raise ValueError("Requirements must be marked required or preferred")
            if edge.kind == "HAS_PREREQUISITE" and edge.prerequisite_type is None:
                raise ValueError("Course prerequisites must be formal or helpful")


def make_batch(
    nodes: list[NodeRecord],
    relationships: list[RelationshipRecord],
    sources: list[SourceRecord],
) -> ImportBatch:
    """Convenience boundary for JSON and CSV decoders without loose dicts downstream."""
    return ImportBatch(tuple(nodes), tuple(relationships), tuple(sources))
