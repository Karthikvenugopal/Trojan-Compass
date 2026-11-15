"""Real preflight and privacy errors; no wildcard or credentialed browser access."""

import pytest
from fastapi.testclient import TestClient

from trojan_compass.api import create_app
from trojan_compass.cors import configured_origins


@pytest.mark.parametrize("origin", ["http://localhost:5173", "http://127.0.0.1:5173"])
def test_local_browser_preflight_and_post(origin: str) -> None:
    with TestClient(create_app()) as client:
        response = client.options(
            "/api/chat",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )
        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == origin
        assert "access-control-allow-credentials" not in response.headers
        reply = client.post(
            "/api/chat",
            headers={"Origin": origin},
            json={
                "messages": [{"role": "user", "content": "Synthetic course query"}],
            },
        )
        assert reply.status_code == 200
        assert reply.headers["access-control-allow-origin"] == origin
        assert reply.headers["cache-control"] == "no-store"


def test_unknown_origins_are_not_allowed() -> None:
    with TestClient(create_app()) as client:
        response = client.options(
            "/api/chat",
            headers={
                "Origin": "https://untrusted.example",
                "Access-Control-Request-Method": "POST",
            },
        )
        assert response.status_code == 400
        assert "access-control-allow-origin" not in response.headers


@pytest.mark.parametrize("body,status", [(b"x" * 65537, 413), (b'{"PRIVATE_SENTINEL":', 422)])
def test_cors_does_not_hide_safe_validation_errors(body: bytes, status: int) -> None:
    with TestClient(create_app()) as client:
        response = client.post(
            "/api/chat",
            content=body,
            headers={
                "Origin": "http://localhost:5173",
                "Content-Type": "application/json",
            },
        )
    assert response.status_code == status
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert response.headers["cache-control"] == "no-store"
    assert "PRIVATE_SENTINEL" not in response.text


def test_explicit_production_origins_and_empty_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("COMPASS_CORS_ORIGINS", "https://compass.example/,https://compass.example")
    assert configured_origins() == ("https://compass.example",)
    with TestClient(create_app()) as client:
        response = client.options(
            "/api/chat",
            headers={
                "Origin": "https://compass.example",
                "Access-Control-Request-Method": "POST",
            },
        )
        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == "https://compass.example"
    monkeypatch.setenv("COMPASS_CORS_ORIGINS", "")
    assert configured_origins() == ()


@pytest.mark.parametrize(
    "origin",
    [
        "*",
        "null",
        "https://user:secret@example.com",
        "https://example.com/chat",
        "https://example.com?key=secret",
        "https://example.com:bad",
        "https://*.example.com",
    ],
)
def test_invalid_origin_configuration_is_sanitized(origin: str) -> None:
    with pytest.raises(ValueError) as exc:
        create_app(cors_origins=(origin,))
    assert "secret" not in str(exc.value)


def test_cors_preserves_a_sanitized_dependency_failure() -> None:
    from trojan_compass.contracts import ChatMessage, RetrievalContext

    class BrokenExtractor:
        async def extract(self, messages: list[ChatMessage]) -> RetrievalContext:
            raise RuntimeError("PRIVATE_SENTINEL")

    with TestClient(create_app(extractor=BrokenExtractor())) as client:
        reply = client.post(
            "/api/chat",
            headers={"Origin": "http://localhost:5173"},
            json={
                "messages": [{"role": "user", "content": "Synthetic query"}],
            },
        )
    assert reply.status_code == 503
    assert reply.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert "PRIVATE_SENTINEL" not in reply.text
