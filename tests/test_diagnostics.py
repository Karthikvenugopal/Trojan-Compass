"""Synthetic diagnostics never disclose credentials, prompts, responses or student facts."""

import json
import subprocess

import pytest
from fastapi.testclient import TestClient

from trojan_compass.api import create_app
from trojan_compass.composition import RuntimeSettings, create_configured_app
from trojan_compass.contracts import ChatMessage, RetrievalContext
from trojan_compass.diagnostics import (
    DUMMY_MESSAGE,
    GeminiCurlProbe,
    ProviderReport,
    dummy_probe,
)


class NeverExtract:
    async def extract(self, messages: list[ChatMessage]) -> RetrievalContext:
        pytest.fail("Diagnostic called the extractor")


class ScriptedCurl:
    def __init__(self, results: list[subprocess.CompletedProcess[str]]) -> None:
        self.results = iter(results)
        self.calls = 0

    def run(self, config: str) -> subprocess.CompletedProcess[str]:
        self.calls += 1
        assert "x-goog-api-key: synthetic-key" in config
        assert "Reply with OK." in config
        return next(self.results)


def reply(
    status: int = 200, exit_code: int = 0, body: str = "{}"
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        ["curl"], exit_code, stdout=f"{body}\n{status:03}", stderr="PRIVATE_PROVIDER_DETAILS"
    )


def test_diagnostic_mode_returns_dummy_through_normal_chat_without_extraction() -> None:
    app = create_app(mode="diagnostic", extractor=NeverExtract())
    with TestClient(app) as client:
        for _ in range(2):
            response = client.post(
                "/api/chat",
                json={
                    "messages": [
                        {"role": "user", "content": "PRIVATE_SYNTHETIC_STATEMENT"},
                    ]
                },
            )
            assert response.status_code == 200
            assert response.json()["message"] == DUMMY_MESSAGE
            assert response.json()["recommendations"] == []
            assert "PRIVATE_SYNTHETIC_STATEMENT" not in response.text
            assert response.headers["cache-control"] == "no-store"
        assert client.get("/health").json()["mode"] == "diagnostic"


def test_dummy_endpoint_works_in_normal_mode_and_through_cors() -> None:
    with TestClient(create_app(extractor=NeverExtract())) as client:
        response = client.get("/api/diagnostics/dummy", headers={"Origin": "http://localhost:5173"})
        assert response.status_code == 200
        assert response.json()["message"] == DUMMY_MESSAGE
        assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_factory_needs_no_provider_credentials_for_diagnostic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("COMPASS_MODE", "diagnostic")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(
        "trojan_compass.composition.configured_extractor", lambda: pytest.fail("Provider selected")
    )
    monkeypatch.setattr(
        "trojan_compass.composition.seed_repository", lambda _: pytest.fail("Graph loaded")
    )
    settings = RuntimeSettings.from_environment()
    with TestClient(create_configured_app(settings)) as client:
        assert client.get("/api/diagnostics/dummy").json()["message"] == DUMMY_MESSAGE


def test_diagnostic_chat_still_validates_conversation() -> None:
    with TestClient(create_app(mode="diagnostic")) as client:
        response = client.post(
            "/api/chat", json={"messages": [{"role": "system", "content": "test"}]}
        )
    assert response.status_code == 422


def test_in_process_dummy_probe_is_explicit_about_transport() -> None:
    assert dummy_probe() == {
        "transport": "in_process",
        "passed": True,
        "http_status": 200,
        "gemini_called": False,
    }


def test_curl_retries_transient_failure_then_records_only_safe_metadata() -> None:
    body = json.dumps(
        {
            "candidates": [{"text": "PRIVATE_PROVIDER_DETAILS"}],
            "usageMetadata": {
                "promptTokenCount": 3,
                "candidatesTokenCount": 1,
                "totalTokenCount": 4,
                "PRIVATE_PROVIDER_DETAILS": 8,
            },
        }
    )
    runner = ScriptedCurl([reply(503), reply(body=body)])
    delays: list[float] = []
    report = GeminiCurlProbe(runner, delays.append).check("synthetic-key", "gemini-test")
    assert report.successful and report.provider_reached
    assert runner.calls == 2 and delays == [1.0]
    assert report.usage_tokens == {
        "promptTokenCount": 3,
        "candidatesTokenCount": 1,
        "totalTokenCount": 4,
    }
    assert "PRIVATE_PROVIDER_DETAILS" not in report.model_dump_json()
    assert "synthetic-key" not in report.model_dump_json()


@pytest.mark.parametrize(
    "status,classification",
    [
        (400, "request_rejected"),
        (401, "authentication_or_permissions"),
        (403, "authentication_or_permissions"),
        (404, "model_not_found"),
        (429, "quota_or_rate_limit"),
        (503, "provider_server_error"),
    ],
)
def test_http_failures_are_classified_without_response_content(
    status: int, classification: str
) -> None:
    count = 3 if status in (429, 503) else 1
    runner = ScriptedCurl([reply(status)] * count)
    report = GeminiCurlProbe(runner, lambda _: None).check("synthetic-key", "gemini-test")
    assert not report.successful and report.provider_reached
    assert len(report.attempts) == count
    assert report.attempts[-1].classification == classification


def test_three_dns_failures_do_not_become_a_claim_of_gemini_outage() -> None:
    runner = ScriptedCurl([reply(0, 6)] * 3)
    report = GeminiCurlProbe(runner, lambda _: None).check("synthetic-key", "gemini-test")
    assert not report.provider_reached and not report.successful
    assert len(report.attempts) == 3
    assert {attempt.classification for attempt in report.attempts} == {"dns_failure"}
    assert "does not establish a Gemini outage" in report.next_step


def test_missing_configuration_does_not_call_curl() -> None:
    runner = ScriptedCurl([])
    report = GeminiCurlProbe(runner).check("", "gemini-test")
    assert not report.attempts and not report.successful
    assert runner.calls == 0


def test_curl_key_stays_out_of_process_arguments(monkeypatch: pytest.MonkeyPatch) -> None:
    from trojan_compass.diagnostics import CurlProcess

    def run(
        args: list[str], *, input: str, text: bool, capture_output: bool, timeout: int, check: bool
    ) -> subprocess.CompletedProcess[str]:
        assert "synthetic-key" not in " ".join(args)
        assert "synthetic-key" in input
        assert capture_output
        return reply()

    monkeypatch.setattr(subprocess, "run", run)
    report: ProviderReport = GeminiCurlProbe(CurlProcess()).check("synthetic-key", "gemini-test")
    assert report.successful


@pytest.mark.asyncio
async def test_local_semantic_probe_checks_real_semantic_outputs_without_printing_content() -> None:
    from pydantic import BaseModel

    from trojan_compass.diagnostics import local_semantic_probe
    from trojan_compass.llm import Model
    from trojan_compass.planner_wire import QuestionReview, StudentFact

    class SemanticModel:
        async def complete(self, system: str, user: str, schema: type[Model]) -> Model:
            assert schema is QuestionReview
            facts = [
                ("study_stage", "Undergraduate", 2, "UG"),
                ("program", "Electrical Engineering", 2, "EE"),
                ("completed_course", "EE 109", 4, "I completed EE 109."),
                ("target.role", "Software engineer", 6, "swe"),
                ("experience", "Theatre volunteering", 0, "I volunteer at a theatre."),
                ("experience", "No related software work experience", 8, "No"),
            ]
            answer: BaseModel = QuestionReview(
                next_step="search",
                search_query="software development",
                occupation_ids=["software-developer"],
                add_facts=[
                    StudentFact(
                        field=field,
                        status="provided",
                        value=value,
                        message_index=index,
                        quote=quote,
                    )
                    for field, value, index, quote in facts
                ],
            )
            return schema.model_validate(answer.model_dump())

    report = await local_semantic_probe(SemanticModel())
    assert report["passed"] is True
    encoded = json.dumps(report)
    assert "elapsed_seconds" in encoded
    assert "volunteer at a theatre" not in encoded and "swe" not in encoded
    assert "conversation" not in report and "response" not in report
