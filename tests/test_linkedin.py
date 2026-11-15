"""Synthetic public profiles only. No real student profile requests."""

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from trojan_compass.api import create_app
from trojan_compass.contracts import ChatMessage, ChatRequest
from trojan_compass.linkedin import LinkedInRequest, LinkedInUnavailable, PublicLinkedInReader


@pytest.mark.parametrize(
    "url",
    [
        "http://linkedin.com/in/example",
        "https://localhost/in/example",
        "https://www.linkedin.com.evil.test/in/example",
        "https://linkedin.com@evil.test/in/example",
        "https://linkedin.com:443/in/example",
        "https://linkedin.com/in/example?redirect=evil",
        "https://linkedin.com/feed/",
    ],
)
def test_only_public_profile_urls(url: str) -> None:
    with pytest.raises(ValidationError):
        LinkedInRequest(url=url)


@pytest.mark.asyncio
async def test_reads_public_background_and_never_follows_redirects() -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        assert "authorization" not in request.headers and "cookie" not in request.headers
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            text=(
                '<script type="application/ld+json">{'
                '"@type":"Person","name":"Synthetic person",'
                '"description":"Volunteer with theatre experience",'
                '"email":"private@example.invalid"}</script>'
            ),
        )

    result = await PublicLinkedInReader(httpx.MockTransport(handler)).read(
        LinkedInRequest(url="https://www.linkedin.com/in/synthetic")
    )
    assert "theatre" in result.text and "email" not in result.text and "@" not in result.text
    assert len(calls) == 1
    for status in [302, 403, 429, 999]:
        reader = PublicLinkedInReader(
            httpx.MockTransport(
                lambda request, status=status: httpx.Response(
                    status, headers={"location": "http://127.0.0.1/secret"}
                )
            )
        )
        with pytest.raises(LinkedInUnavailable):
            await reader.read(LinkedInRequest(url="https://linkedin.com/in/synthetic"))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "html",
    [
        "<main>Sign in</main>",
        '<script type="application/ld+json">{"@type":"Person","name":"Only a name"}</script>',
        "x" * 1_000_001,
    ],
    ids=["login", "name-only", "oversized"],
)
async def test_blocked_or_excessive_profile_has_no_fabricated_background(html: str) -> None:
    reader = PublicLinkedInReader(
        httpx.MockTransport(
            lambda request: httpx.Response(200, headers={"content-type": "text/html"}, text=html)
        )
    )
    with pytest.raises(LinkedInUnavailable):
        await reader.read(LinkedInRequest(url="https://linkedin.com/in/synthetic"))


def test_import_is_full_conversation_text_and_limits_remain_enforced() -> None:
    text = "Use my resume as background.\n" + "x" * 20000
    request = ChatRequest(messages=[ChatMessage(role="user", content=text)])
    assert request.messages[0].content == text
    with pytest.raises(ValidationError):
        ChatMessage(role="assistant", content=text)
    with pytest.raises(ValidationError):
        ChatMessage(role="user", content="x" * 4001)
    with pytest.raises(ValidationError):
        ChatRequest(messages=[request.messages[0], ChatMessage(role="user", content="x" * 4000)])
    with TestClient(create_app()) as client:
        response = client.post(
            "/api/import-linkedin", json={"url": "https://private.invalid/sensitive"}
        )
        assert response.status_code == 422
        assert "sensitive" not in response.text
        assert response.headers["cache-control"] == "no-store"
