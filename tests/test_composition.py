"""Owner integration with real USC seed/engine and a mocked external provider only."""

import builtins
import json
from pathlib import Path

import httpx
import pytest
from compact_checklist import create_configured_app
from fastapi.testclient import TestClient
from pydantic import SecretStr

from trojan_compass.api import app_from_environment
from trojan_compass.composition import RuntimeSettings, seed_repository
from trojan_compass.contracts import (
    ChatMessage,
    ChatResponse,
    RetrievalContext,
    Skill,
    StudentStatement,
    Target,
)
from trojan_compass.extraction import OpenAIContextExtractor


def extraction_response(request: httpx.Request) -> httpx.Response:
    payload = json.loads(request.content)
    messages = json.loads(payload["messages"][1]["content"])
    assert payload["store"] is False
    last = messages[-1]["content"]
    context = RetrievalContext()
    if "Software developer" in messages[0]["content"]:
        context.target = Target(
            kind="role",
            name="Software developer",
            evidence=[
                StudentStatement(message_index=0, quote="Software developer"),
            ],
        )
        corrected = "Correction:" in last
        context.skills = [
            Skill(
                name="Computer programming",
                status="known" if corrected else "not_yet_learned",
                evidence=[
                    StudentStatement(
                        message_index=len(messages) - 1,
                        quote="I know Computer programming"
                        if corrected
                        else "I haven't learned Computer programming yet",
                    )
                ],
            )
        ]
    return httpx.Response(
        200,
        json={
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {
                        "content": context.model_dump_json(),
                    },
                }
            ]
        },
    )


def extractor() -> OpenAIContextExtractor:
    return OpenAIContextExtractor(
        "synthetic-test-key", "synthetic-model", httpx.MockTransport(extraction_response)
    )


def test_campus_full_path_reextracts_corrections_without_persisting() -> None:
    app = create_configured_app(RuntimeSettings(mode="campus"), extractor=extractor())
    with TestClient(app) as client:
        messages = [
            {
                "role": "user",
                "content": (
                    "I want to be a Software developer. I haven't learned Computer programming yet."
                ),
            }
        ]
        first = client.post("/api/chat", json={"messages": messages})
        assert first.status_code == 200
        response = ChatResponse.model_validate(first.json())
        assert any(r.id == "usc-course-csci-103l" for r in response.recommendations)
        assert response.recommendations[0].sources
        assert response.recommendations[0].evidence_path
        assert all(
            "example." not in str(s.url) for r in response.recommendations for s in r.sources
        )
        assert any("seed snapshot" in note for note in response.limitations)
        messages += [
            {"role": "assistant", "content": response.message},
            {"role": "user", "content": "Correction: I know Computer programming already."},
        ]
        second = client.post("/api/chat", json={"messages": messages})
        assert second.status_code == 200
        corrected = ChatResponse.model_validate(second.json())
        assert "usc-course-csci-103l" not in {r.id for r in corrected.recommendations}
        # An independent new request must not inherit the prior career/skill facts.
        third = client.post(
            "/api/chat",
            json={
                "messages": [
                    {"role": "user", "content": "Help me get started"},
                ]
            },
        )
        broad = ChatResponse.model_validate(third.json())
        assert broad.suggested_replies
        assert broad.recommendations == []
        assert third.headers["cache-control"] == "no-store"
        assert "set-cookie" not in third.headers


def test_campus_beginner_unsure_still_gets_sourced_options() -> None:
    app = create_configured_app(RuntimeSettings(mode="campus"), extractor=extractor())
    with TestClient(app) as client:
        messages = [{"role": "user", "content": "Help me get started"}]
        first = ChatResponse.model_validate(
            client.post("/api/chat", json={"messages": messages}).json()
        )
        messages += [
            {"role": "assistant", "content": first.message},
            {"role": "user", "content": "I'm not sure"},
        ]
        second = ChatResponse.model_validate(
            client.post("/api/chat", json={"messages": messages}).json()
        )
        assert second.information.missing_fields == ["background"]
        messages += [
            {"role": "assistant", "content": second.message},
            {"role": "user", "content": "I have no experience"},
        ]
        second = ChatResponse.model_validate(
            client.post("/api/chat", json={"messages": messages}).json()
        )
        assert second.recommendations
        assert not second.suggested_replies
        assert all(r.sources and r.unknowns for r in second.recommendations)
        assert all(r.event is None or r.event.start is None for r in second.recommendations)


def test_runtime_configuration_fails_closed_and_masks_secrets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("COMPASS_MODE", "unknown")
    with pytest.raises(ValueError, match="COMPASS_MODE"):
        app_from_environment()
    monkeypatch.setenv("COMPASS_MODE", "campus")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        app_from_environment()
    with pytest.raises(ValueError, match="NEO4J_URI"):
        create_configured_app(RuntimeSettings(mode="production"), extractor=extractor())
    assert "private-password" not in repr(
        RuntimeSettings(neo4j_password=SecretStr("private-password"))
    )


def test_environment_factory_uses_real_campus_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COMPASS_MODE", "campus")
    monkeypatch.setattr("trojan_compass.composition.configured_extractor", extractor)
    with TestClient(app_from_environment()) as client:
        assert client.get("/health").json()["mode"] == "campus"
        response = client.post(
            "/api/chat",
            json={
                "messages": [
                    {
                        "role": "user",
                        "content": (
                            "Show me campus events; I want to be a Software developer. "
                            "I haven't learned Computer programming yet."
                        ),
                    },
                ]
            },
        )
    assert response.status_code == 200
    assert not response.json()["recommendations"]
    assert response.json()["information"]["missing_fields"] == [
        "study_stage",
        "program",
        "work_experience",
        "completed_courses",
    ]


def test_public_seed_loaded_at_startup_only(monkeypatch: pytest.MonkeyPatch) -> None:
    app = create_configured_app(RuntimeSettings(mode="campus"), extractor=extractor())
    with TestClient(app) as client:

        def forbid(*args: object, **kwargs: object) -> None:
            raise AssertionError("No file I/O during chat")

        with monkeypatch.context() as patch:
            patch.setattr(builtins, "open", forbid)
            patch.setattr(Path, "open", forbid)
            patch.setattr(Path, "read_text", forbid)
            patch.setattr(Path, "write_text", forbid)
            response = client.post(
                "/api/chat",
                json={
                    "messages": [
                        {"role": "user", "content": "Help me get started"},
                    ]
                },
            )
        assert response.status_code == 200


@pytest.mark.asyncio
async def test_shared_seed_repository_unchanged_after_requests() -> None:
    graph = seed_repository()
    before = [a.model_dump() for a in await graph.browse_actions(50)]
    app = create_configured_app(RuntimeSettings(mode="campus"), extractor=extractor(), graph=graph)
    with TestClient(app) as client:
        for text in ["Help me", "I'm not sure", "Show campus events"]:
            assert (
                client.post(
                    "/api/chat",
                    json={
                        "messages": [
                            {"role": "user", "content": text},
                        ]
                    },
                ).status_code
                == 200
            )
    assert [a.model_dump() for a in await graph.browse_actions(50)] == before


def test_missing_public_seed_does_not_fall_back_to_demo(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        create_configured_app(
            RuntimeSettings(mode="campus", seed_path=tmp_path / "missing.json"),
            extractor=extractor(),
        )


def test_owned_database_adapter_closes_and_never_imports_during_chat(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sys
    from types import ModuleType

    from trojan_compass.graph.fake import FakeGraphRepository
    from trojan_compass.ingestion.loaders import load_json
    from trojan_compass.ingestion.pipeline import IngestionPipeline

    instances: list[FakeGraphRepository] = []
    closed: list[bool] = []

    class OwnedGraph(FakeGraphRepository):
        def __init__(self, uri: str, username: str, password: str, database: str) -> None:
            super().__init__()
            assert (uri, username, password, database) == (
                "neo4j://test",
                "test-user",
                "test-password",
                "test-database",
            )
            instances.append(self)
            # Simulate existing shared data; production composition must never import.
            IngestionPipeline(self).import_records(
                load_json(
                    Path(__file__).parents[1] / "data" / "seed" / "usc.json",
                )
            )

        def close(self) -> None:
            closed.append(True)

    module = ModuleType("trojan_compass.graph.neo4j_adapter")
    monkeypatch.setattr(module, "Neo4jGraphRepository", OwnedGraph, raising=False)
    monkeypatch.setitem(sys.modules, "trojan_compass.graph.neo4j_adapter", module)
    app = create_configured_app(
        RuntimeSettings(
            mode="production",
            neo4j_uri="neo4j://test",
            neo4j_username="test-user",
            neo4j_password=SecretStr("test-password"),
            neo4j_database="test-database",
        ),
        extractor=extractor(),
    )
    assert len(instances) == 1
    assert not closed
    with TestClient(app) as client:
        assert client.get("/health").json()["mode"] == "production"
        response = client.post(
            "/api/chat",
            json={
                "messages": [
                    {
                        "role": "user",
                        "content": (
                            "Show me campus events; I want to be a Software developer. "
                            "I haven't learned Computer programming yet."
                        ),
                    },
                ]
            },
        )
        assert response.status_code == 200
        assert response.json()["recommendations"]
        assert not closed
    assert closed == [True]


def test_target_refinement_is_material_even_when_a_target_exists() -> None:
    from compact_checklist import AskBackPolicy

    from trojan_compass.contracts import Clarification

    context = RetrievalContext(
        target=Target(
            kind="company",
            name="Synthetic company",
            evidence=[StudentStatement(message_index=0, quote="Synthetic company")],
        )
    )
    question = Clarification(
        text="Which kind of work there interests you?",
        requested_fields=["target"],
        reason="Different roles require different preparation.",
        options=["Software", "Research", "I'm not sure"],
    )
    messages = [ChatMessage(role="user", content="Synthetic company")]
    assert AskBackPolicy().choose(question, context, messages) == question
    messages += [
        ChatMessage(role="assistant", content=question.text),
        ChatMessage(role="user", content="I'm not sure"),
    ]
    assert AskBackPolicy().choose(question, context, messages) is None
