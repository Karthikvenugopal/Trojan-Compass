"""Fetch the public USC Schedule of Classes for selected terms and normalize it.

Source: the read-only JSON API behind https://classes.usc.edu (no login required).
Only public GET endpoints are used: schools/programs per term and courses per
school+program. Raw responses are cached (gzip) so an interrupted run resumes
without re-requesting. Requests are sequential with a delay to stay polite.

Usage:
    python scripts/fetch_usc_catalog.py                 # default terms
    python scripts/fetch_usc_catalog.py --terms 20263 20271
Output:
    data/usc/catalog.json   normalized courses (one record per course, offerings per term)
"""

from __future__ import annotations

import argparse
import gzip
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

API = "https://classes.usc.edu/api"
ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "data" / "raw" / "usc-classes"
OUTPUT = ROOT / "data" / "usc" / "catalog.json"
DEFAULT_TERMS = ["20261", "20263", "20271"]  # Spring 2026, Fall 2026, Spring 2027
HEADERS = {"Accept": "application/json", "User-Agent": "TrojanCompass-catalog-fetch/0.1"}
SEASONS = {"1": "Spring", "2": "Summer", "3": "Fall"}


def term_label(term: str) -> str:
    return f"{SEASONS.get(term[-1], term[-1])} {term[:4]}"


def get_json(url: str, cache_file: Path, delay: float) -> object:
    if cache_file.exists():
        with gzip.open(cache_file, "rt", encoding="utf-8") as fh:
            return json.load(fh)
    last: Exception | None = None
    for attempt in range(4):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=90) as resp:
                body = resp.read().decode("utf-8")
            data = json.loads(body)
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            with gzip.open(cache_file, "wt", encoding="utf-8") as fh:
                fh.write(body)
            time.sleep(delay)
            return data
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            last = exc
            time.sleep(delay * (2 ** (attempt + 1)))
    raise RuntimeError(f"failed after retries: {url}: {last}")


def level_for(number: str) -> str:
    digits = "".join(ch for ch in number if ch.isdigit())
    if not digits:
        return "unknown"
    n = int(digits)
    if n < 500:
        return "undergraduate"
    if n < 700:
        return "graduate"
    return "doctoral/advanced graduate"


def clean(value: object) -> object:
    if isinstance(value, str):
        value = " ".join(value.split())
        return value or None
    return value


def normalize(term: str, school: dict, program: dict, raw: dict, courses: dict) -> None:
    for c in raw.get("courses") or []:
        code_info = c.get("publishedCourseCode") or c.get("scheduledCourseCode") or {}
        code = code_info.get("courseSpace") or c.get("fullCourseName")
        hyphen = code_info.get("courseHyphen") or (code or "").replace(" ", "-")
        if not code:
            continue
        sections = c.get("sections") or []
        live = [s for s in sections if not s.get("isCancelled")]
        offering = {
            "term": term,
            "term_label": term_label(term),
            "source_url": f"{API}/Courses/Course?termCode={term}&courseCode="
            + urllib.parse.quote(hyphen),
            "sections": len(sections),
            "active_sections": len(live),
            "modes": sorted({s.get("rnrMode") for s in live if s.get("rnrMode")}),
            "instructors": sorted(
                {
                    " ".join(filter(None, [i.get("firstName"), i.get("lastName")]))
                    for s in live
                    for i in (s.get("instructors") or [])
                }
                - {""}
            ),
            "seats_total": c.get("sectionSeatCount"),
            "seats_remaining": c.get("remainingSectionSeats"),
            "syllabus_urls": sorted({s["syllabus"] for s in live if s.get("syllabus")})[:5],
            "schedule": sorted(
                {
                    f"{','.join(m.get('days') or [])} {m.get('startTime')}-{m.get('endTime')}"
                    for s in live
                    for m in (s.get("schedule") or [])
                    if m.get("startTime")
                }
            )[:8],
        }
        record = courses.setdefault(
            code,
            {
                "code": code,
                "prefix": code_info.get("prefix") or c.get("prefix"),
                "number": code_info.get("number") or c.get("classNumber"),
                "suffix": code_info.get("suffix") or c.get("suffix") or "",
                "title": clean(c.get("name")),
                "level": level_for(code_info.get("number") or c.get("classNumber") or ""),
                "units": c.get("courseUnits"),
                "schools": [],
                "programs": [],
                "offerings": {},
            },
        )
        # Latest term wins for descriptive text; keep any non-empty earlier value.
        for key, src in (
            ("description", "description"),
            ("recommended_prep", "recommendedPrep"),
            ("course_notes", "courseNotes"),
            ("duplicate_credit", "duplicateCredit"),
            ("ge_code", "geCode"),
        ):
            value = clean(c.get(src))
            if value or key not in record:
                record[key] = value or record.get(key)
        for key, src in (
            ("prerequisites", "prerequisiteCourseCodes"),
            ("corequisites", "corequisiteCourseCodes"),
            ("concurrent", "concurrentCourses"),
            ("major_restrictions", "majorRestrictions"),
            ("school_restrictions", "schoolRestrictions"),
            ("course_restrictions", "courseRestrictions"),
        ):
            value = c.get(src)
            if value:
                record[key] = value
        record["is_cross_listed"] = bool(c.get("isCrossListed"))
        if school["name"] not in record["schools"]:
            record["schools"].append(school["name"])
        if program["name"] not in record["programs"]:
            record["programs"].append(program["name"])
        record["offerings"][term] = offering


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--terms", nargs="+", default=DEFAULT_TERMS)
    parser.add_argument("--delay", type=float, default=0.6, help="seconds between requests")
    args = parser.parse_args()

    courses: dict[str, dict] = {}
    failures: list[str] = []
    for term in args.terms:
        schools = get_json(
            f"{API}/Schools/TermCode?termCode={term}", CACHE / term / "schools.json.gz", args.delay
        )
        pairs = [(s, p) for s in schools for p in (s.get("programs") or [])]
        print(f"[{term_label(term)}] {len(schools)} schools, {len(pairs)} school/program pairs")
        for i, (school, program) in enumerate(pairs, 1):
            query = urllib.parse.urlencode(
                {"termCode": term, "school": school["prefix"], "program": program["prefix"]}
            )
            cache_file = CACHE / term / f"{school['prefix']}_{program['prefix']}.json.gz"
            try:
                raw = get_json(
                    f"{API}/Courses/CoursesByTermSchoolProgram?{query}", cache_file, args.delay
                )
            except RuntimeError as exc:
                failures.append(str(exc))
                print(f"  ! {school['prefix']}/{program['prefix']} failed", file=sys.stderr)
                continue
            normalize(term, school, program, raw, courses)
            if i % 25 == 0 or i == len(pairs):
                print(f"  {i}/{len(pairs)} pairs, {len(courses)} unique courses so far", flush=True)

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "source": "USC Schedule of Classes public API (https://classes.usc.edu)",
        "fetched_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "terms": {t: term_label(t) for t in args.terms},
        "course_count": len(courses),
        "failures": failures,
        "courses": sorted(courses.values(), key=lambda r: (r["prefix"] or "", r["code"])),
    }
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    size_mb = OUTPUT.stat().st_size / 1e6
    print(f"wrote {OUTPUT.relative_to(ROOT)}: {len(courses)} courses, {size_mb:.1f} MB")
    print(f"failures: {len(failures)}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
