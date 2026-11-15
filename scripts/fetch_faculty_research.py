"""Collect faculty research profiles from official USC Viterbi department directories.

Each department site lists faculty at /directory/faculty/ and links a public profile
page with a biography / research summary. This writes data/usc/faculty_research.json
with one record per professor: name, title, department, profile URL and the research
text. Public pages only; sequential requests with a delay.

Usage: python scripts/fetch_faculty_research.py
"""

from __future__ import annotations

import json
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from html import unescape
from pathlib import Path

import certifi

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data" / "usc" / "faculty_research.json"
CACHE = ROOT / "data" / "raw" / "faculty"
SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; TrojanCompass-kb/0.1)", "Accept": "text/html"}

DEPARTMENTS = {
    "Computer Science": "https://www.cs.usc.edu",
    "Electrical and Computer Engineering": "https://minghsiehece.usc.edu",
    "Aerospace and Mechanical Engineering": "https://ame.usc.edu",
    "Biomedical Engineering": "https://bme.usc.edu",
    "Chemical Engineering and Materials Science": "https://chems.usc.edu",
    "Civil and Environmental Engineering": "https://cee.usc.edu",
    "Industrial and Systems Engineering": "https://ise.usc.edu",
    "Astronautical Engineering": "https://aste.usc.edu",
}
ENTRY = re.compile(
    r"href\s*=\s*'(?P<href>[^']*profile/\?lname=[^']+)'.*?resultName\">(?P<name>.*?)</h5>"
    r"(?P<title>.*?)</div>",
    re.S,
)
START = ("Research Summary", "Biography", "Research Interests")
STOP = ("Awards", "Office ", "Contact Information", "Links ", "Return to Faculty Directory")


def get(url: str) -> str | None:
    key = re.sub(r"[^a-zA-Z0-9]+", "_", url)[-150:]
    cached = CACHE / f"{key}.html"
    if cached.exists():
        return cached.read_text(encoding="utf-8")
    try:
        request = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(request, timeout=30, context=SSL_CONTEXT) as response:
            html = response.read().decode("utf-8", errors="ignore")
    except (urllib.error.URLError, TimeoutError, ValueError):
        return None
    CACHE.mkdir(parents=True, exist_ok=True)
    cached.write_text(html, encoding="utf-8")
    time.sleep(0.35)
    return html


def plain(html: str) -> str:
    html = re.sub(r"<script.*?</script>|<style.*?</style>", " ", html, flags=re.S)
    text = unescape(re.sub(r"<[^>]+>", " ", html)).replace("\xa0", " ")
    return " ".join(text.replace("�", " ").split())


def research_text(page: str) -> str:
    text = plain(page)
    starts = [text.find(marker) for marker in START if text.find(marker) >= 0]
    if not starts:
        return ""
    begin = min(starts)
    stops = [text.find(marker, begin + 20) for marker in STOP]
    end = min([s for s in stops if s > 0] or [begin + 1500])
    body = text[begin:end]
    for marker in START:
        body = body.replace(marker, " ", 1) if body.startswith(marker) else body
    return " ".join(body.split())[:1500]


def main() -> int:
    people: dict[str, dict[str, object]] = {}
    for department, base in DEPARTMENTS.items():
        listing = get(f"{base}/directory/faculty/")
        if listing is None:
            print(f"{department}: directory unavailable", flush=True)
            continue
        found = 0
        for match in ENTRY.finditer(listing):
            href = unescape(match["href"])
            url = urllib.parse.urljoin(f"{base}/directory/faculty/", href)
            query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
            last = (query.get("lname") or [""])[0]
            first = (query.get("fname") or [""])[0]
            name = plain(match["name"])
            if not last or not first or not name:
                continue
            key = f"{last}|{first}".casefold()
            record = people.get(key)
            if record is None:
                page = get(url)
                text = research_text(page) if page else ""
                record = {
                    "name": name,
                    "first_name": first,
                    "last_name": last,
                    "title": plain(match["title"])[:300],
                    "departments": [],
                    "profile_url": url,
                    "research_text": text,
                }
                people[key] = record
            departments = record["departments"]
            assert isinstance(departments, list)
            if department not in departments:
                departments.append(department)
            found += 1
        print(f"{department}: {found} faculty", flush=True)

    records = sorted(people.values(), key=lambda r: (str(r["last_name"]), str(r["first_name"])))
    OUTPUT.write_text(
        json.dumps(
            {
                "source": "USC Viterbi department faculty directories",
                "fetched_at": datetime.now(UTC).isoformat(timespec="seconds"),
                "faculty": records,
            },
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )
    with_text = sum(1 for r in records if r["research_text"])
    print(
        f"wrote {OUTPUT.relative_to(ROOT)}: {len(records)} faculty, {with_text} with research text"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
