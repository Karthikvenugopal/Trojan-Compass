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

from trojan_compass.ai_chat import AIChatService
from trojan_compass.api import AppMode, configured_extractor, create_app
from trojan_compass.assistant import CampusAssistant, KnowledgeBase
from trojan_compass.career_guidance import EvidenceCareerGuide, PathLibrary
from trojan_compass.catalog import CatalogIndex, CatalogRecommendationService
from trojan_compass.contracts import (
    ContextExtractor,
    RecommendationRequest,
    RecommendationResult,
    RecommendationService,
)
from trojan_compass.controlled_intake import ControlledIntakeParser
from trojan_compass.exploration import ExplorationRecommendationService
from trojan_compass.graph.fake import FakeGraphRepository
from trojan_compass.ingestion.loaders import load_json
from trojan_compass.ingestion.pipeline import IngestionPipeline
from trojan_compass.llm import StructuredLLM, configured_llm
from trojan_compass.readiness import DEFAULT_FIXED_FIELDS
from trojan_compass.recommendations import RecommendationEngine
from trojan_compass.recommendations.graph import GraphRepository
from trojan_compass.services import AskBackPolicy, DemoRecommendationService
from trojan_compass.university import (
    AcademicCourseHistoryService,
    UniversityGraphRepository,
    public_snapshot,
)

COVERAGE_NOTICE = (
    "The connected graph has limited course and event coverage. Missing matches do not mean "
    "USC has no relevant opportunities. Check linked sources for prerequisites, dates and access."
)
SEED_NOTICE = (
    "Using a reviewed USC seed snapshot, not a live database or enrollment feed. "
    "Some skill links and discipline tags are inferred from public metadata; tags do not "
    "prove learning outcomes. Event dates recorded only as dates are not shown as times."
)
CATALOG_SEED_NOTICE = (
    "Courses come from a snapshot of USC's public Schedule of Classes; events come from a "
    "reviewed public calendar snapshot. Neither is a live enrollment feed."
)


def shared_data_path(name: str) -> Path:
    """Locate the same public snapshot in a checkout and an installed wheel."""
    source = Path(__file__).resolve().parents[2] / "data" / "usc" / name
    return source if source.is_file() else Path(__file__).resolve().parent / "data" / name


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
    kb_path: Path | None = None

    @classmethod
    def from_environment(cls) -> "RuntimeSettings":
        mode = os.getenv("COMPASS_MODE", "demo")
        if mode not in ("demo", "diagnostic", "campus", "production"):
            raise ValueError("COMPASS_MODE must be demo, diagnostic, campus or production")
        seed_path = os.getenv("COMPASS_SEED_PATH")
        catalog = os.getenv("COMPASS_CATALOG_PATH")
        default_catalog = shared_data_path("catalog.json")
        catalog_path = Path(catalog) if catalog else default_catalog
        kb = os.getenv("COMPASS_KB_PATH")
        kb_path = Path(kb) if kb else shared_data_path("campus_kb.json")
        return cls(
            kb_path=kb_path if kb_path.is_file() else None,
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

    def __init__(
        self,
        engine: RecommendationService,
        notices: tuple[str, ...],
        graph: GraphRepository | None = None,
    ) -> None:
        self._engine = engine
        self._notices = notices
        self._graph = graph

    async def recommend(self, request: RecommendationRequest) -> RecommendationResult:
        completed = []
        if self._graph is not None and request.context.completed_courses:
            completed = await self._graph.find_courses(
                [v.value for v in request.context.completed_courses]
            )
        completed_ids = {a.id for a in completed}
        expanded = request.model_copy(update={"limit": 10}) if completed_ids else request
        result = await self._engine.recommend(expanded)
        result = result.model_copy(
            update={
                "recommendations": [r for r in result.recommendations if r.id not in completed_ids][
                    : request.limit
                ]
            }
        )
        return result.model_copy(update={"limitations": [*self._notices, *result.limitations]})


def create_configured_app(
    settings: RuntimeSettings | None = None,
    *,
    extractor: ContextExtractor | None = None,
    graph: GraphRepository | None = None,
    policy: AskBackPolicy | None = None,
    assistant: CampusAssistant | None = None,
    llm: StructuredLLM | None = None,
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
        recommendations: RecommendationService | None = None
        if settings.mode == "demo" and settings.catalog_path is not None:
            # Demo stays offline, but can use the bundled public USC catalog snapshot
            # for real course facts instead of pretending the fixed example is live.
            demo_catalog = CatalogIndex.load(settings.catalog_path)
            recommendations = CatalogRecommendationService(
                DemoRecommendationService(), demo_catalog
            )
        return create_app(
            mode=settings.mode,
            recommendations=recommendations,
            local_intake=ControlledIntakeParser() if settings.mode == "demo" else None,
        )
    # The question assistant uses the same server-configured provider as extraction;
    # injected (test) extractors get no assistant unless one is injected too.
    # Live apps use AI orchestration. Explicit legacy dependency injection remains
    # available for existing focused tests; provider failure never selects it.
    use_ai = llm is not None or (extractor is None and assistant is None)
    use_local_intake = extractor is None and not use_ai
    build_assistant = extractor is None and assistant is None
    extractor = extractor if extractor is not None else configured_extractor()
    lifespan = None
    if graph is None and settings.mode == "campus":
        graph = seed_repository(settings.seed_path)
        if settings.seed_path is None and (snapshot := public_snapshot()) is not None:
            graph = UniversityGraphRepository(graph, snapshot)
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
    if settings.mode == "production" and (snapshot := public_snapshot()) is not None:
        # Enrich only records actually returned by the live adapter, never add seed fallback.
        graph = UniversityGraphRepository(graph, snapshot, overlay=False)
    notices = (SEED_NOTICE, COVERAGE_NOTICE) if settings.mode == "campus" else (COVERAGE_NOTICE,)
    service: RecommendationService = ExplorationRecommendationService(
        RecommendationEngine(graph),
        graph,
        subjects=graph.course_subjects if isinstance(graph, UniversityGraphRepository) else None,
    )
    catalog = None
    if settings.mode == "campus" and settings.catalog_path is not None:
        # Shared public catalog, loaded once at startup (never per student request).
        catalog = CatalogIndex.load(settings.catalog_path)
        service = CatalogRecommendationService(service, catalog, graph=graph)
        notices = (CATALOG_SEED_NOTICE,)
    agent_llm = (
        llm if llm is not None else (configured_llm(max_output_tokens=8192) if use_ai else None)
    )
    if build_assistant or (use_ai and assistant is None):
        knowledge = KnowledgeBase.load(settings.kb_path) if settings.kb_path else None
        assistant = CampusAssistant(agent_llm or configured_llm(), catalog, knowledge)
    covered = CoverageRecommendationService(service, notices, graph)
    history = AcademicCourseHistoryService(graph)
    library = PathLibrary.load()
    evidence = EvidenceCareerGuide(graph, library, catalog)
    ai_service = None
    if use_ai:
        assert agent_llm is not None and assistant is not None
        ai_service = AIChatService(
            agent_llm,
            covered,
            library,
            evidence,
            history,
            assistant,
            notices[0],
            request_timeout=180 if os.getenv("LLM_PROVIDER") == "ollama" else 75,
        )
    return create_app(
        mode=settings.mode,
        extractor=extractor,
        recommendations=covered,
        lifespan=lifespan,
        policy=policy,
        course_history=history,
        assistant=assistant,
        local_intake=ControlledIntakeParser() if use_local_intake else None,
        chat_service=ai_service,
        guidance=evidence
        if policy is None or policy.fixed_fields == DEFAULT_FIXED_FIELDS
        else None,
    )
