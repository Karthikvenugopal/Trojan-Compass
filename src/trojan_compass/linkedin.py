"""Read a public profile once, in memory. Never authenticate, cache or bypass access controls."""

import asyncio
import json
import re
from collections.abc import AsyncGenerator
from contextlib import aclosing
from html.parser import HTMLParser
from typing import Any, cast

import httpx
from pydantic import Field, field_validator

from trojan_compass.contracts import Contract


class LinkedInRequest(Contract):
    url: str = Field(max_length=300)

    @field_validator("url")
    @classmethod
    def public_profile(cls, value: str) -> str:
        # Exact public host/path only: no credentials, ports, queries or arbitrary URLs.
        if not re.fullmatch(r"https://(?:www\.)?linkedin\.com/in/[A-Za-z0-9_-]{1,150}/?", value):
            raise ValueError("Use a public LinkedIn profile URL")
        return value


class LinkedInText(Contract):
    text: str = Field(min_length=1, max_length=20000)


class LinkedInUnavailable(Exception):
    """Static error, with no URL, response body or student information."""


class PublicProfileHTML(HTMLParser):
    """Read only public structured profile text; scripts are never executed."""

    def __init__(self) -> None:
        super().__init__()
        self.active = False
        self.parts: list[str] = []
        self.records: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "script":
            self.active = dict(attrs).get("type") == "application/ld+json"
            self.parts = []

    def handle_data(self, data: str) -> None:
        if self.active:
            self.parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self.active:
            self.records.append("".join(self.parts))
            self.parts = []
            self.active = False


def profile_text(records: list[str]) -> str:
    # Ignore tracking, contact data, images, URLs and unrelated navigation entities.
    fields = {
        "name",
        "description",
        "jobTitle",
        "alumniOf",
        "worksFor",
        "knowsAbout",
        "hasOccupation",
        "memberOf",
        "award",
        "educationalCredentialAwarded",
    }

    def sentences(value: Any) -> list[str]:
        if isinstance(value, str):
            return [value]
        if isinstance(value, list):
            return [part for item in value for part in sentences(item)]
        if isinstance(value, dict):
            return [
                part for key, item in value.items() if key in fields for part in sentences(item)
            ]
        return []

    def people(value: Any) -> list[dict[str, Any]]:
        if isinstance(value, list):
            return [person for item in value for person in people(item)]
        if isinstance(value, dict):
            kind = value.get("@type")
            if kind == "Person" or isinstance(kind, list) and "Person" in kind:
                return [value]
            return people(value.get("@graph", []))
        return []

    for raw in records:
        try:
            for person in people(json.loads(raw)):
                # Name alone is not useful career background (e.g. a sign-in teaser).
                background = {key: value for key, value in person.items() if key != "name"}
                if not sentences(background):
                    continue
                text = "\n".join(dict.fromkeys(sentences(person))).strip()
                if 1 <= len(text) <= 20000:
                    return text
        except (ValueError, TypeError, RecursionError):
            continue
    raise LinkedInUnavailable()


class PublicLinkedInReader:
    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._transport = transport

    async def read(self, request: LinkedInRequest) -> LinkedInText:
        try:
            async with (
                asyncio.timeout(12),
                httpx.AsyncClient(
                    timeout=10, trust_env=False, follow_redirects=False, transport=self._transport
                ) as client,
            ):
                async with client.stream(
                    "GET",
                    request.url,
                    headers={
                        "Accept": "text/html",
                        "User-Agent": "TrojanCompass/0.2 public-profile-reader",
                    },
                ) as response:
                    if response.status_code != 200 or "text/html" not in response.headers.get(
                        "content-type", ""
                    ):
                        raise LinkedInUnavailable()
                    content = bytearray()
                    async with aclosing(
                        cast(AsyncGenerator[bytes, None], response.aiter_bytes(chunk_size=65536))
                    ) as chunks:
                        async for chunk in chunks:
                            content.extend(chunk)
                            if len(content) > 1_000_000:
                                raise LinkedInUnavailable()
            parser = PublicProfileHTML()
            parser.feed(content.decode("utf-8", errors="replace"))
            return LinkedInText(text=profile_text(parser.records))
        except Exception:
            # Redirects/login/captcha/rate limits fail closed. No retries or circumvention.
            raise LinkedInUnavailable() from None
