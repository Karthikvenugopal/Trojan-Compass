"""Opt-in synthetic probes. Only safe check codes, counts and timings leave this module."""

import argparse
import asyncio
import json
import os
import re
import subprocess
import time
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

import httpx
from pydantic import BaseModel, Field

from trojan_compass.contracts import ChatResponse

if TYPE_CHECKING:
    from trojan_compass.llm import StructuredLLM

DUMMY_MESSAGE = "Diagnostic response: Trojan Compass is responding. Gemini was not called."


def dummy_response() -> ChatResponse:
    return ChatResponse(
        message=DUMMY_MESSAGE,
        limitations=["Diagnostic only: no AI provider or knowledge graph was called."],
    )


class ProbeAttempt(BaseModel):
    attempt: int
    curl_exit_code: int
    http_status: int
    classification: str


class ProviderReport(BaseModel):
    provider_reached: bool = False
    successful: bool = False
    attempts: list[ProbeAttempt] = Field(default_factory=list)
    usage_tokens: dict[str, int] = Field(default_factory=dict)
    next_step: str


class CurlRunner(Protocol):
    def run(self, config: str) -> subprocess.CompletedProcess[str]: ...


class CurlProcess:
    def run(self, config: str) -> subprocess.CompletedProcess[str]:
        # Credentials enter through stdin, never argv, shell expansion or a temp file.
        return subprocess.run(
            [
                "curl",
                "--config",
                "-",
                "--silent",
                "--show-error",
                "--connect-timeout",
                "5",
                "--max-time",
                "10",
                "--write-out",
                "\n%{http_code}",
            ],
            input=config,
            text=True,
            capture_output=True,
            timeout=12,
            check=False,
        )


class GeminiCurlProbe:
    """Retry transient failures only. Never print provider bodies, stderr or credentials."""

    def __init__(
        self,
        runner: CurlRunner | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._runner = runner or CurlProcess()
        self._sleep = sleep

    def check(self, api_key: str, model: str, attempts: int = 3) -> ProviderReport:
        if not api_key or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", model):
            return ProviderReport(
                next_step="Set GEMINI_API_KEY and a plain GEMINI_MODEL in server .env."
            )
        if not 1 <= attempts <= 3:
            raise ValueError("Use 1 to 3 probe attempts")
        payload = {
            "contents": [{"parts": [{"text": "Reply with OK."}]}],
            "generationConfig": {"maxOutputTokens": 32},
        }
        config = (
            "\n".join(
                [
                    "url = "
                    + json.dumps(
                        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
                    ),
                    "header = " + json.dumps("x-goog-api-key: " + api_key),
                    'header = "Content-Type: application/json"',
                    "data = " + json.dumps(json.dumps(payload)),
                ]
            )
            + "\n"
        )
        report = ProviderReport(next_step="Run the probe from a network-enabled terminal.")
        for number in range(1, attempts + 1):
            try:
                response = self._runner.run(config)
                body, _, status = response.stdout.rpartition("\n")
                code = int(status) if status.isdigit() else 0
                exit_code = response.returncode
            except subprocess.TimeoutExpired:
                body, code, exit_code = "", 0, 28
            except OSError:
                body, code, exit_code = "", 0, 127
            reason, advice = classify(exit_code, code)
            report.attempts.append(
                ProbeAttempt(
                    attempt=number,
                    curl_exit_code=exit_code,
                    http_status=code,
                    classification=reason,
                )
            )
            report.provider_reached |= code > 0
            report.next_step = advice
            if exit_code == 0 and 200 <= code < 300:
                report.successful = True
                report.usage_tokens = token_counts(body)
                break
            transient = exit_code in (5, 6, 7, 18, 28, 52, 55, 56) or code in (
                408,
                429,
                500,
                502,
                503,
                504,
            )
            if not transient or number == attempts:
                break
            self._sleep(float(number))
        return report


def classify(exit_code: int, http_status: int) -> tuple[str, str]:
    if exit_code:
        if exit_code in (5, 6):
            return (
                "dns_failure",
                "Google was not reached. Fix DNS/network access; "
                "this does not establish a Gemini outage.",
            )
        if exit_code == 7:
            return "connection_failure", "Google was not reached. Check the network or proxy."
        if exit_code == 28:
            return "timeout", "The request timed out; retry on a working connection."
        if exit_code in (35, 60):
            return "tls_failure", "Check the local TLS/certificate configuration."
        if exit_code == 127:
            return "curl_unavailable", "Install curl or allow it to run in this environment."
        return (
            "network_failure",
            "The local request failed; Gemini availability is not established.",
        )
    if http_status == 0:
        return "invalid_http_response", "No HTTP response was received; Gemini is not verified."
    if 200 <= http_status < 300:
        return (
            "reachable",
            "Gemini accepted this synthetic probe. If real chat fails, "
            "check structured extraction or retrieval.",
        )
    if http_status in (401, 403):
        return (
            "authentication_or_permissions",
            "Google rejected access. Check/replace the key and verify project permissions.",
        )
    if http_status == 429:
        return (
            "quota_or_rate_limit",
            "Google was reached. Check Gemini quota/billing and retry later.",
        )
    if http_status == 404:
        return (
            "model_not_found",
            "Google was reached. Check GEMINI_MODEL availability for this project.",
        )
    if http_status >= 500:
        return (
            "provider_server_error",
            "Google returned server errors after bounded retries. Retry later.",
        )
    return "request_rejected", "Google rejected the request. Check model/API configuration."


def token_counts(body: str) -> dict[str, int]:
    try:
        response = json.loads(body)
        usage = response.get("usageMetadata", {}) if isinstance(response, dict) else {}
        if not isinstance(usage, dict):
            return {}
        return {
            key: usage[key]
            for key in (
                "promptTokenCount",
                "candidatesTokenCount",
                "totalTokenCount",
            )
            if type(usage.get(key)) is int and usage[key] >= 0
        }
    except (ValueError, TypeError):
        return {}


def dummy_probe(base_url: str | None = None) -> dict[str, object]:
    """In-process checks prove app wiring, not that local network ports are listening."""
    status = 0
    try:
        if base_url is None:
            from fastapi.testclient import TestClient

            from trojan_compass.api import create_app

            with TestClient(create_app(mode="diagnostic")) as client:
                response = client.get("/api/diagnostics/dummy")
        else:
            with httpx.Client(timeout=5, trust_env=False) as http:
                response = http.get(base_url.rstrip("/") + "/api/diagnostics/dummy")
        status = response.status_code
        data = response.json()
        passed = status == 200 and isinstance(data, dict) and data.get("message") == DUMMY_MESSAGE
        return {
            "transport": "in_process" if base_url is None else "http",
            "passed": passed,
            "http_status": response.status_code,
            "gemini_called": False,
        }
    except Exception:
        return {
            "transport": "in_process" if base_url is None else "http",
            "passed": False,
            "http_status": status,
            "gemini_called": False,
        }


async def local_semantic_probe(llm: "StructuredLLM") -> dict[str, object]:
    """Opt-in real local inference on synthetic dialogue; return booleans/timing only."""
    from trojan_compass.contracts import ChatMessage
    from trojan_compass.extraction import ExtractionFailure, grounded_context
    from trojan_compass.llm import LLMFailure
    from trojan_compass.planner_wire import (
        QUESTION_REVIEW_PROMPT,
        PlannerOutput,
        QuestionReview,
        apply_question_review,
    )
    from trojan_compass.readiness import request_information

    started = time.monotonic()
    messages = [
        ChatMessage(role="user", content="I volunteer at a theatre."),
        ChatMessage(
            role="assistant", content="What academic level and major?", asked_field="study_stage"
        ),
        ChatMessage(role="user", content="UG EE at USC"),
        ChatMessage(
            role="assistant",
            content="Which courses have you completed?",
            asked_field="completed_courses",
        ),
        ChatMessage(role="user", content="I completed EE 109."),
        ChatMessage(
            role="assistant",
            content="Which career would you like to explore?",
            asked_field="target",
        ),
        ChatMessage(role="user", content="swe"),
        ChatMessage(
            role="assistant",
            content="Any related software work experience?",
            asked_field="work_experience",
        ),
        ChatMessage(role="user", content="No"),
    ]
    payload = {
        "conversation": [{**m.model_dump(), "message_index": i} for i, m in enumerate(messages)],
        "candidate_facts": [],
        "proposed_question": {"field": "target", "text": "What is your career goal?"},
        "occupations": {"software-developer": "Software developer"},
        "question_answer_turns": [
            {
                "question": messages[i - 1].content,
                "asked_field": messages[i - 1].asked_field,
                "reply": message.content,
                "reply_index": i,
            }
            for i, message in enumerate(messages)
            if i > 0 and message.role == "user"
        ],
    }
    try:
        review = await llm.complete(QUESTION_REVIEW_PROMPT, json.dumps(payload), QuestionReview)
        wire = apply_question_review(PlannerOutput(intent="ask"), review)
        context = grounded_context(wire.context(messages).model_dump_json(), messages)
        info = request_information(context, messages, ai_owned=True)
        checks = {
            "combined_stage": bool(
                context.study_stage and "undergrad" in context.study_stage.value.casefold()
            ),
            "combined_program": bool(
                context.program and "electrical" in context.program.value.casefold()
            ),
            "goal_interpreted": bool(
                context.target and "software" in context.target.name.casefold()
            ),
            "unrelated_experience_preserved": any(
                "theatre" in item.value.casefold() for item in context.experiences
            ),
            "negative_reply_scoped": any(
                f.message_index == 8 and f.field in {"experience", "work_experience"}
                for f in wire.facts
            ),
            "course_preserved": any(
                "EE109" in re.sub(r"[^A-Z0-9]", "", item.value.upper())
                for item in context.completed_courses
            ),
            "no_inferred_skill_mastery": not context.skills,
            "no_repeated_question": review.next_step == "search"
            and review.question is None
            and info.snapshot().ready,
        }
        return {
            "passed": all(checks.values()),
            "checks": checks,
            "elapsed_seconds": round(time.monotonic() - started, 2),
        }
    except (LLMFailure, ExtractionFailure) as error:
        return {
            "passed": False,
            "error_code": error.reason.value,
            "elapsed_seconds": round(time.monotonic() - started, 2),
        }
    except Exception:
        return {
            "passed": False,
            "error_code": "semantic_probe_failed",
            "elapsed_seconds": round(time.monotonic() - started, 2),
        }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Synthetic application/provider checks; no content or secrets printed"
    )
    parser.add_argument(
        "--gemini", action="store_true", help="Opt in to a small Gemini request (may consume quota)"
    )
    parser.add_argument(
        "--ollama",
        action="store_true",
        help="Opt in to a synthetic local semantic test; prints no conversation/model output",
    )
    parser.add_argument("--attempts", type=int, default=3, choices=range(1, 4))
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument(
        "--base-url", help="Also test the running backend or frontend proxy over HTTP"
    )
    arguments = parser.parse_args()
    application = dummy_probe()
    passed = application["passed"] is True
    output: dict[str, object] = {"application": application}
    if arguments.base_url:
        running = dummy_probe(arguments.base_url)
        output["running_server"] = running
        passed = passed and running["passed"] is True
    if arguments.gemini:
        from dotenv import dotenv_values

        values = dotenv_values(arguments.env_file)
        key = os.getenv("GEMINI_API_KEY") or values.get("GEMINI_API_KEY") or ""
        model = os.getenv("GEMINI_MODEL") or values.get("GEMINI_MODEL") or ""
        report = GeminiCurlProbe().check(key, model, arguments.attempts)
        output["gemini"] = report.model_dump()
        passed = passed and report.successful
    if arguments.ollama:
        from dotenv import dotenv_values

        from trojan_compass.ollama import OllamaStructuredLLM

        values = dotenv_values(arguments.env_file)
        try:
            local = OllamaStructuredLLM(
                os.getenv("OLLAMA_MODEL") or values.get("OLLAMA_MODEL") or "qwen3:4b",
                os.getenv("OLLAMA_BASE_URL")
                or values.get("OLLAMA_BASE_URL")
                or "http://127.0.0.1:11434",
                context_length=int(
                    os.getenv("OLLAMA_CONTEXT_LENGTH")
                    or values.get("OLLAMA_CONTEXT_LENGTH")
                    or "32768"
                ),
            )
            semantic = asyncio.run(local_semantic_probe(local))
        except Exception:
            semantic = {"passed": False, "error_code": "local_configuration"}
        output["ollama_semantics"] = semantic
        passed = passed and semantic["passed"] is True
    print(json.dumps(output, indent=2))
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
