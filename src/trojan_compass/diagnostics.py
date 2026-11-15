"""Opt-in synthetic probes. Only status codes and token counts may leave this module."""

import argparse
import json
import os
import re
import subprocess
import time
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

import httpx
from pydantic import BaseModel, Field

from trojan_compass.contracts import ChatResponse

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


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Synthetic app/Gemini checks; no content or secrets printed"
    )
    parser.add_argument(
        "--gemini", action="store_true", help="Opt in to a small Gemini request (may consume quota)"
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
    print(json.dumps(output, indent=2))
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
