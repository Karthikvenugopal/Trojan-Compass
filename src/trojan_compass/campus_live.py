"""Live, public campus facts fetched at question time (shared data, never student data)."""

from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from html import unescape
from zoneinfo import ZoneInfo

import httpx

LIBRARY_HOURS_URL = "https://libraries.usc.edu/hours"
CAMPUS_TZ = ZoneInfo("America/Los_Angeles")
ROW = re.compile(
    r'data-hours="(?P<hours>[^"]*)".*?library-name">\s*(?:<a[^>]*>)?\s*(?P<name>[^<]+?)\s*<'
    r'.*?library-status__hours[^"]*">(?P<label>[^<]*)<',
    re.S,
)


@dataclass(frozen=True)
class LibraryStatus:
    name: str
    today: str
    open_now: bool
    next_change: str | None


@dataclass(frozen=True)
class LibrarySnapshot:
    fetched_at: datetime
    libraries: tuple[LibraryStatus, ...]

    def as_text(self) -> str:
        local = self.fetched_at.astimezone(CAMPUS_TZ)
        lines = [f"Live USC Libraries hours as of {local:%A %B %d, %Y %I:%M %p} Pacific time:"]
        for lib in self.libraries:
            state = "OPEN now" if lib.open_now else "closed now"
            nxt = f"; {lib.next_change}" if lib.next_change else ""
            lines.append(f"- {lib.name}: {state} (today: {lib.today}{nxt})")
        return "\n".join(lines)


def parse_library_hours(html: str, now: datetime) -> LibrarySnapshot:
    """Each row lists timestamped transitions: 'epoch|label|open-or-closed,...'."""
    stamp = now.timestamp()
    seen: dict[str, LibraryStatus] = {}
    for match in ROW.finditer(html):
        name = " ".join(unescape(match["name"]).split())
        if not name or name in seen:
            continue
        transitions = []
        for item in match["hours"].split(","):
            parts = item.split("|")
            if len(parts) == 3 and parts[0].isdigit():
                transitions.append((int(parts[0]), parts[1], parts[2]))
        transitions.sort()
        current = [t for t in transitions if t[0] <= stamp]
        upcoming = [t for t in transitions if t[0] > stamp]
        open_now = bool(current) and current[-1][2] == "open"
        next_change = None
        if upcoming:
            when = datetime.fromtimestamp(upcoming[0][0], UTC).astimezone(CAMPUS_TZ)
            next_change = f"{'closes' if open_now else 'opens'} at {when:%I:%M %p}".replace(
                " 0", " "
            )
            if not open_now and upcoming[0][2] != "open":
                next_change = None
        seen[name] = LibraryStatus(
            name=name,
            today=" ".join(unescape(match["label"]).split()) or "unknown",
            open_now=open_now,
            next_change=next_change,
        )
    return LibrarySnapshot(fetched_at=now, libraries=tuple(seen.values()))


class LibraryHours:
    """Fetch the public hours page with a short shared cache (no student data involved)."""

    TTL_SECONDS = 600

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._transport = transport
        self._cached: tuple[float, str] | None = None
        self._lock = asyncio.Lock()

    async def snapshot(self) -> LibrarySnapshot | None:
        async with self._lock:
            if self._cached is None or time.monotonic() - self._cached[0] > self.TTL_SECONDS:
                try:
                    async with httpx.AsyncClient(
                        timeout=httpx.Timeout(10.0),
                        transport=self._transport,
                        trust_env=False,
                        follow_redirects=True,
                    ) as client:
                        response = await client.get(
                            LIBRARY_HOURS_URL, headers={"User-Agent": "TrojanCompass/0.2"}
                        )
                        response.raise_for_status()
                    self._cached = (time.monotonic(), response.text)
                except httpx.HTTPError:
                    return None
            html = self._cached[1]
        snapshot = parse_library_hours(html, datetime.now(UTC))
        return snapshot if snapshot.libraries else None
