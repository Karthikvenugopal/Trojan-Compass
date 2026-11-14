"""Command line importer. Credentials are read only from environment variables."""

import argparse
import asyncio
import os
from pathlib import Path

from trojan_compass.graph.neo4j_adapter import Neo4jGraphRepository
from trojan_compass.ingestion.loaders import load_csv, load_json
from trojan_compass.ingestion.pipeline import IngestionPipeline


def main() -> None:
    parser = argparse.ArgumentParser(description="Import shared Trojan Compass campus/career data")
    parser.add_argument("file", type=Path, help="JSON or CSV import file")
    args = parser.parse_args()
    batch = load_json(args.file) if args.file.suffix.lower() == ".json" else load_csv(args.file)
    uri = os.environ["NEO4J_URI"]
    username = os.environ["NEO4J_USERNAME"]
    password = os.environ["NEO4J_PASSWORD"]
    database = os.environ.get("NEO4J_DATABASE", "neo4j")
    repository = Neo4jGraphRepository(uri, username, password, database)
    try:
        asyncio.run(repository.ensure_schema())
        IngestionPipeline(repository).import_records(batch)
    finally:
        repository.close()
    print(f"Imported {len(batch.nodes)} shared nodes, {len(batch.relationships)} evidence edges")


if __name__ == "__main__":
    main()
