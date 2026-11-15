"""Build a small campus knowledge base from official USC web pages.

Fetches each seed page plus a capped number of same-site links (preferring pages
about hours, calendars, FAQs, contacts, services and deadlines), extracts readable
text and splits it into chunks. Public pages only; no login, no forms.

Usage:  python scripts/fetch_campus_kb.py [--per-site 10]
Output: data/usc/campus_kb.json
"""

from __future__ import annotations

import argparse
import json
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from html import unescape
from html.parser import HTMLParser
from pathlib import Path

import certifi

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data" / "usc" / "campus_kb.json"
# certifi keeps verification on even where the OS/Python CA store is stale.
SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())
HEADERS = {"User-Agent": "TrojanCompass-kb/0.1", "Accept": "text/html"}

SEEDS = {
    "USC Libraries": ["https://libraries.usc.edu/libraries-overview"],
    "Academic calendar": ["https://www.usc.edu/academic-calendar/"],
    "Academic Records and Registrar": ["https://arr.usc.edu/"],
    "Student Health": ["https://studenthealth.usc.edu/", "https://studenthealth.usc.edu/hours/"],
    "Hospitality and dining": ["https://hospitality.usc.edu/"],
    "Transportation": ["https://transnet.usc.edu/"],
    "Career Center": ["https://careers.usc.edu/"],
    "Viterbi Career Connections": ["https://viterbicareers.usc.edu/"],
    "International Services": ["https://ois.usc.edu/"],
    "Housing": ["https://housing.usc.edu/"],
    "IT Services": ["https://itservices.usc.edu/"],
    "Financial Aid": ["https://financialaid.usc.edu/"],
    "Public Safety": ["https://dps.usc.edu/"],
    "Recreational Sports": ["https://recsports.usc.edu/"],
    "Graduate School": ["https://graduateschool.usc.edu/"],
    "Student Life": ["https://studentlife.usc.edu/"],
    "Accessibility Services": ["https://osas.usc.edu/"],
}
PRIORITY = re.compile(
    r"hour|calendar|deadline|faq|contact|location|service|appointment|shuttle|dining|"
    r"register|registration|enroll|visa|opt|cpt|insurance|parking|transit|tutor|study|"
    r"room|reserve|print|wifi|password|counsel|emergency|housing|aid|scholarship|"
    r"job|intern|handshake|graduat|thesis|fee|tuition|map|about|resources",
    re.I,
)
SKIP = re.compile(
    r"\.(pdf|jpe?g|png|gif|svg|zip|docx?|xlsx?|pptx?|mp4|mp3|ics)$|"
    r"login|signin|sso|shibboleth|/wp-admin|/feed|mailto:|tel:|javascript:|#",
    re.I,
)
DROP_TAGS = {"script", "style", "noscript", "svg", "nav", "header", "footer", "form", "iframe"}


class Extractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.links: list[str] = []
        self._skip = 0
        self._in_title = False
        self._in_main = 0
        self.main_parts: list[str] = []
        self.all_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in DROP_TAGS:
            self._skip += 1
        if tag == "title" and not self._skip and not self.title:
            self._in_title = True
        if tag == "main" or dict(attrs).get("role") == "main":
            self._in_main += 1
        if tag == "a":
            href = dict(attrs).get("href")
            if href:
                self.links.append(href)
        if tag in ("p", "li", "h1", "h2", "h3", "h4", "tr", "br", "div", "td", "th"):
            self._emit("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in DROP_TAGS and self._skip:
            self._skip -= 1
        if tag == "title":
            self._in_title = False
        if tag == "main" and self._in_main:
            self._in_main -= 1

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data
        elif not self._skip:
            self._emit(data)

    def _emit(self, text: str) -> None:
        self.all_parts.append(text)
        if self._in_main:
            self.main_parts.append(text)

    def text(self) -> str:
        body = "".join(self.main_parts)
        if len(body.strip()) < 400:
            body = "".join(self.all_parts)
        lines = (" ".join(line.split()) for line in unescape(body).splitlines())
        return "\n".join(line for line in lines if len(line) > 2)


def fetch(url: str) -> tuple[str, str] | None:
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=25, context=SSL_CONTEXT) as resp:
            if "html" not in (resp.headers.get("Content-Type") or ""):
                return None
            return resp.geturl(), resp.read().decode("utf-8", errors="ignore")
    except (urllib.error.URLError, TimeoutError, ValueError):
        return None


def chunks(text: str, size: int = 1200, overlap: int = 150) -> list[str]:
    out, start = [], 0
    while start < len(text):
        end = min(len(text), start + size)
        if end < len(text):
            cut = text.rfind("\n", start + size // 2, end)
            end = cut if cut > 0 else end
        out.append(text[start:end].strip())
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return [c for c in out if len(c) > 80]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--per-site", type=int, default=10, help="extra linked pages per site")
    parser.add_argument("--delay", type=float, default=0.4)
    args = parser.parse_args()

    checked = datetime.now(UTC).date().isoformat()
    seen: set[str] = set()
    docs: list[dict[str, object]] = []
    for site, seeds in SEEDS.items():
        queue = list(seeds)
        host = urllib.parse.urlparse(seeds[0]).netloc
        extra: list[str] = []
        count = 0
        while queue:
            url = queue.pop(0)
            key = url.rstrip("/").casefold()
            if key in seen:
                continue
            seen.add(key)
            got = fetch(url)
            time.sleep(args.delay)
            if got is None:
                continue
            final, html = got
            page = Extractor()
            page.feed(html)
            text = page.text()
            title = " ".join(page.title.split()) or site
            for i, chunk in enumerate(chunks(text)):
                docs.append(
                    {
                        "id": f"kb-{len(docs)}",
                        "site": site,
                        "title": title,
                        "url": final,
                        "checked_at": checked,
                        "chunk": i,
                        "text": chunk,
                    }
                )
            count += 1
            if url in seeds:
                for href in page.links:
                    link = urllib.parse.urljoin(final, href).split("#")[0]
                    parsed = urllib.parse.urlparse(link)
                    if parsed.scheme != "https" or parsed.netloc != host or SKIP.search(link):
                        continue
                    if link.rstrip("/").casefold() not in seen and link not in extra:
                        extra.append(link)
                extra.sort(key=lambda u: (not PRIORITY.search(u), len(u)))
                queue += extra[: args.per_site]
        print(f"{site}: {count} pages", flush=True)

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps({"checked_at": checked, "chunks": docs}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    print(f"wrote {OUTPUT.relative_to(ROOT)}: {len(docs)} chunks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
