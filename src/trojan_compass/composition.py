"""Compose the owners' existing implementations without retaining student state."""

import asyncio
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from importlib.resources import as_file, files
from pathlib import Path
from typing import cast

from fastapi import FastAPI
from pydantic import SecretStr

from trojan_compass.api import AppMode, configured_extractor, create_app
from trojan_compass.catalog import CatalogIndex, CatalogRecommendationService
from trojan_compass.contracts import (
    ContextExtractor,
    RecommendationRequest,
    RecommendationResult,
    RecommendationService,
)
from trojan_compass.exploration import ExplorationRecommendationService
from trojan_compass.graph.fake import FakeGraphRepository
from trojan_compass.ingestion.loaders import load_json
from trojan_compass.ingestion.pipeline import IngestionPipeline
from trojan_compass.recommendations import RecommendationEngine
from trojan_compass.recommendations.graph import GraphRepository

COVERAGE_NOTICE = (
    "The connected graph has limited course and event coverage. Missing matches do not mean "
    "USC has no relevant opportunities. Check linked sources for prerequisites, dates and access."
)
SEED_NOTICE = (
    "Using a reviewed USC seed snapshot, not a live database or enrollment feed. "
    "Some skill links are inferred. Event dates recorded only as dates are not shown as times."
)
CATALOG_SEED_NOTICE = (
    "Courses come from a snapshot of USC's public Schedule of Classes; events come from a "
    "small reviewed seed. Neither is a live enrollment feed."
)


@dataclass(frozen=True)
class RuntimeSettings:
    """Server configuration only. Secrets are masked even in accidental repr output."""

    mode: AppMode = "demo"
    seed_path: Path | None = None
    neo4j_uri: str = ""
    neo4j_username: str = ""
    neo4j_password: SecretStr = SecretStr("")
    neo4j_database: str = "neo4j"
    catalog_path: Path | None = None

    @classmethod
    def from_environment(cls) -> "RuntimeSettings":
        mode = os.getenv("COMPASS_MODE", "demo")
        if mode not in ("demo", "diagnostic", "campus", "production"):
            raise ValueError("COMPASS_MODE must be demo, diagnostic, campus or production")
        seed_path = os.getenv("COMPASS_SEED_PATH")
        catalog = os.getenv("COMPASS_CATALOG_PATH")
        default_catalog = Path(__file__).resolve().parents[2] / "data" / "usc" / "catalog.json"
        catalog_path = Path(catalog) if catalog else default_catalog
        return cls(
            catalog_path=catalog_path if catalog_path.is_file() else None,
            mode=cast(AppMode, mode),
            seed_path=Path(seed_path) if seed_path else None,
            neo4j_uri=os.getenv("NEO4J_URI", ""),
            neo4j_username=os.getenv("NEO4J_USERNAME", ""),
            neo4j_password=SecretStr(os.getenv("NEO4J_PASSWORD", "")),
            neo4j_database=os.getenv("NEO4J_DATABASE", "neo4j"),
        )


def seed_repository(path: Path | None = None) -> FakeGraphRepository:
    """Load only shared public graph data at startup, never on a student request."""
    repository = FakeGraphRepository()
    pipeline = IngestionPipeline(repository)
    if path is not None:
        pipeline.import_records(load_json(path))
    else:
        packaged = files("trojan_compass").joinpath("data", "usc.json")
        if packaged.is_file():
            with as_file(packaged) as seed:
                pipeline.import_records(load_json(seed))
        else:
            # Source checkout; the wheel ships this same reviewed shared-data file.
            seed = Path(__file__).resolve().parents[2] / "data" / "seed" / "usc.json"
            pipeline.import_records(load_json(seed))
    return repository


class CoverageRecommendationService:
    """Attach truthful deployment limitations; only collaborators/config survive calls."""

    def __init__(self, engine: RecommendationService, notices: tuple[str, ...]) -> None:
        self._engine = engine
        self._notices = notices

    async def recommend(self, request: RecommendationRequest) -> RecommendationResult:
        result = await self._engine.recommend(request)
        return result.model_copy(update={"limitations": [*self._notices, *result.limitations]})


def create_configured_app(
    settings: RuntimeSettings | None = None,
    *,
    extractor: ContextExtractor | None = None,
    graph: GraphRepository | None = None,
) -> FastAPI:
    """Wire extraction → Peri's engine → Abishek's adapter. No automatic imports/writes.

    Injected dependencies remain caller-owned. Only a Neo4j driver opened by this
    factory is closed here. Production never silently falls back to fake/seed data.
    """
    settings = settings or RuntimeSettings.from_environment()
    if settings.mode in ("demo", "diagnostic"):
        if extractor is not None or graph is not None:
            raise ValueError(
                "Choose campus or production mode for injected integration dependencies"
            )
        return create_app(mode=settings.mode)
    extractor = extractor if extractor is not None else configured_extractor()
    lifespan = None
    if graph is None and settings.mode == "campus":
        graph = seed_repository(settings.seed_path)
    elif graph is None:
        if not all(
            (
                settings.neo4j_uri,
                settings.neo4j_username,
                settings.neo4j_password.get_secret_value(),
            )
        ):
            raise ValueError("Production requires NEO4J_URI, NEO4J_USERNAME and NEO4J_PASSWORD")
        # Lazy import keeps the explicit demo and seed modes independent of Neo4j.
        from trojan_compass.graph.neo4j_adapter import Neo4jGraphRepository

        owned_graph = Neo4jGraphRepository(
            settings.neo4j_uri,
            settings.neo4j_username,
            settings.neo4j_password.get_secret_value(),
            settings.neo4j_database,
        )
        graph = owned_graph

        @asynccontextmanager
        async def close_graph(app: FastAPI) -> AsyncIterator[None]:
            try:
                yield
            finally:
                await asyncio.to_thread(owned_graph.close)

        lifespan = close_graph
    notices = (SEED_NOTICE, COVERAGE_NOTICE) if settings.mode == "campus" else (COVERAGE_NOTICE,)
    service: RecommendationService = ExplorationRecommendationService(
        RecommendationEngine(graph), graph
    )
    if settings.mode == "campus" and settings.catalog_path is not None:
        # Shared public catalog, loaded once at startup (never per student request).
        service = CatalogRecommendationService(service, CatalogIndex.load(settings.catalog_path))
        notices = (CATALOG_SEED_NOTICE,)
    return create_app(
        mode=settings.mode,
        extractor=extractor,
        recommendations=CoverageRecommendationService(service, notices),
        lifespan=lifespan,
    )
