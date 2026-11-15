"""Refresh shared USC facts from public institutional feeds. Never accepts student data.

Only metadata is retained: no section rosters, instructor/contact objects, attendees,
creator IDs, credentials or personalized data. Output is a normal validated KG batch.
"""

import argparse
import gzip
import hashlib
import html
import json
import re
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

from trojan_compass.ingestion.loaders import decode
from trojan_compass.ingestion.pipeline import IngestionPipeline

# Public, reviewable discovery tags. Inferred associations are marked on edges.
DOMAINS: dict[str, str] = {
    "Architecture": r"architectur",
    "Design": r"\bdesign\b|roski",
    "Art": r"\bart\b|arts|roski|museum|exhibit",
    "Music": r"music|thornton|concert|recital|jazz|choir",
    "Dance": r"dance|kaufman",
    "Theatre": r"theat|dramatic|\bdrama\b",
    "Film": r"cinema|\bfilm\b|screening|screenwrit|animation",
    "Literature": r"literature|poetry|\bbooks?\b|creative writing",
    "Communication": r"communicat|annenberg",
    "Journalism": r"journalis|newsroom",
    "Business": r"business|marshall|entrepreneur|startup|finance|accounting|marketing",
    "Economics": r"economic",
    "Accounting": r"accounting|leventhal",
    "Entrepreneurship": r"entrepreneur|startup",
    "Law": r"\blaw\b|gould|legal|justice",
    "Public policy": r"public policy|\bprice\b|urban planning|public administration",
    "Political science": r"political|politics|democracy|election",
    "International relations": r"international relations|diplomacy",
    "Education": r"rossier|education|teaching|pedagogy",
    "Social work": r"social work|dworak|social welfare",
    "Psychology": r"psycholog|behavioral|behavioural",
    "Mental health": r"mental health|psychotherap|counseling|psychiatr",
    "Medicine": r"medicine|\bkeck\b|medical|clinical|patient",
    "Public health": r"public health|population health|epidemiolog",
    "Nursing": r"nursing",
    "Pharmacy": r"pharmac|pharmaceutical",
    "Dentistry": r"dental|dentist|ostrow|oral health",
    "Occupational therapy": r"occupational therap|occupational science",
    "Physical therapy": r"physical therap|biokinesiology",
    "Gerontology": r"gerontolog|aging|ageing",
    "Biology": r"biolog|biochem|\bbisc\b",
    "Neuroscience": r"neuroscien|\bbrain\b",
    "Chemistry": r"chemistry|chemical",
    "Physics": r"physics|quantum",
    "Astronomy": r"astronom|astrophys|universe",
    "Mathematics": r"mathemat|statistics|calculus",
    "Environment": r"environment|sustainab|climate|ecolog|ocean|conservation",
    "Engineering": r"engineer|viterbi",
    "Mechanical engineering": r"mechanical|aerospace|robotic",
    "Civil engineering": r"civil engineer|structural|construction",
    "Electrical engineering": r"electrical|electronics|circuits",
    "Computer science": r"computer science|computing|programming|cybersecurity",
    "Data science": r"data science|data analytics|machine learning|artificial intelligence",
    "History": r"\bhistory\b|historical",
    "Sociology": r"sociolog|social inequality",
    "Anthropology": r"anthropolog",
    "Philosophy": r"philosoph|\bethics\b",
    "Languages": r"languages|linguistic|spanish|french|arabic|chinese|japanese",
    "Religion": r"religio|spiritual",
    "Career exploration": r"career|internship|recruit|networking",
    "Community service": r"volunteer|community service|civic engagement",
}


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.casefold()).strip("-")[:120]


def plain(value: object, limit: int = 400) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", str(value or ""))).split())[:limit]


def canonical_code(row: dict[str, Any]) -> tuple[str, list[str]]:
    prefix = str(row.get("prefix", "")).upper()
    number = str(row.get("classNumber", ""))
    sequence = str(row.get("sequence") or "").upper()
    suffix = "".join(c for c in str(row.get("suffix") or "") if c.isupper())
    if not re.fullmatch(r"[A-Z]{2,6}", prefix) or not re.fullmatch(r"\d{3}", number):
        raise ValueError("Invalid official course identity")
    code = f"{prefix} {number}{sequence}{suffix}"
    names = [code, str(row.get("fullCourseName") or ""), f"{prefix} {number}{sequence}"]
    return code, list(dict.fromkeys(n for n in names if n))


class PublicFeedClient:
    """Bounded public GET requests; no arbitrary hosts, auth or model calls."""

    def get(self, host: str, path: str, **params: object) -> Any:
        if host not in ("calendar.usc.edu", "classes.usc.edu"):
            raise ValueError("Only official public USC feeds are accepted")
        url = f"https://{host}/{path.lstrip('/')}?{urlencode(params)}"
        for attempt in range(3):
            try:
                request = Request(
                    url,
                    headers={
                        "User-Agent": "TrojanCompass-PublicDataImporter/1.0",
                        "Accept": "application/json",
                    },
                )
                with urlopen(request, timeout=35) as response:
                    if urlparse(response.url).hostname not in (host,):
                        raise ValueError("Unexpected public-feed redirect")
                    raw = response.read(35_000_001)
                    if len(raw) > 35_000_000:
                        raise ValueError("Public feed exceeds bounded response size")
                    return json.loads(raw)
            except (HTTPError, TimeoutError, OSError) as error:
                if isinstance(error, HTTPError) and error.code not in (429, 500, 502, 503, 504):
                    raise
                if attempt == 2:
                    raise
                time.sleep(attempt + 1)
        raise RuntimeError("Public GET did not complete")


class UniversityBatchBuilder:
    def __init__(self, checked: date) -> None:
        self.checked = checked
        self.nodes: dict[str, dict[str, Any]] = {}
        self.sources: dict[str, dict[str, Any]] = {}
        self.edges: dict[str, dict[str, Any]] = {}
        self.course_counts: Counter[str] = Counter()
        self.event_departments: Counter[str] = Counter()
        self.skipped: Counter[str] = Counter()
        self.event_ids: set[str] = set()
        self.instance_ids: set[str] = set()
        self.upcoming_instances = 0

    def source(self, identifier: str, url: str, title: str, excerpt: str) -> str:
        self.sources[identifier] = {
            "id": identifier,
            "url": url,
            "title": title,
            "checked_at": self.checked.isoformat(),
            "excerpt": excerpt[:1500],
        }
        return identifier

    def edge(
        self, kind: str, start: str, end: str, source: str, excerpt: str, inferred: bool = False
    ) -> None:
        key = "usc-" + hashlib.sha256(f"{kind}:{start}:{end}".encode()).hexdigest()[:24]
        self.edges[key] = {
            "id": key,
            "kind": kind,
            "source_id": start,
            "target_id": end,
            "source_record_id": source,
            "excerpt": excerpt[:1500],
            "fact_type": "inferred" if inferred else "explicit",
        }

    def topics(self, parent: str, source: str, explicit: list[str], text: str) -> None:
        tags = {plain(name, 100): False for name in explicit if plain(name, 100)}
        for name, pattern in DOMAINS.items():
            if re.search(pattern, text, re.I):
                tags.setdefault(name, True)
        for name, inferred in tags.items():
            identifier = "usc-topic-" + slug(name)
            self.nodes[identifier] = {"id": identifier, "kind": "Topic", "name": name}
            self.edge(
                "COVERS",
                parent,
                identifier,
                source,
                f"{name}: {self.sources[source]['excerpt']}",
                inferred,
            )

    def course(
        self, row: dict[str, Any], school: dict[str, Any], program: dict[str, Any], term: str
    ) -> None:
        try:
            code, aliases = canonical_code(row)
        except ValueError:
            self.skipped["invalid_course_identity"] += 1
            return
        title = plain(row.get("name"), 240)
        if not title:
            return
        identifier = "usc-course-" + slug(code)
        prefix = str(row["prefix"])
        url = f"https://classes.usc.edu/term/{term}/catalogue/school/{school['prefix']}/program/{prefix}"
        description = plain(row.get("description"), 280)
        prereq = row.get("prerequisiteCourseCodes")
        prereq_text = plain(json.dumps(prereq, ensure_ascii=False), 600) if prereq else ""
        attrs: dict[str, Any] = {
            "course_code": code,
            "aliases": "|".join(aliases),
            "subject": str(program.get("name", prefix)),
            "school": str(school["name"]),
            "course_number": int(row["classNumber"]),
            "catalog_term": term,
            "course_url": url,
            "summary": description or f"{code}: {title}.",
            "prerequisite_rule": prereq_text,
            "corequisite_rule": plain(row.get("corequisiteCourseCodes"), 400),
            "restrictions": plain(row.get("courseRestrictions"), 400),
            "major_restrictions": plain(row.get("majorRestrictions"), 400),
            "school_restrictions": plain(row.get("schoolRestrictions"), 400),
        }
        self.nodes[identifier] = {
            "id": identifier,
            "kind": "Course",
            "name": f"{code}: {title}",
            "attributes": attrs,
        }
        source = self.source(
            "source-" + identifier,
            url,
            f"USC {code}: {title}",
            f"{code}: {title}. Subject: {attrs['subject']}. School: {school['name']}. {description}"
            + (f" Published prerequisite rule: {prereq_text}." if prereq_text else ""),
        )
        self.topics(
            identifier,
            source,
            [str(program.get("name", prefix))],
            f"{title} {description} {attrs['subject']} {school['name']}",
        )
        self.course_counts[str(school["name"])] += 1

    def event(self, event: dict[str, Any], now: datetime) -> None:
        if event.get("private") or event.get("rejected"):
            self.skipped["nonpublic_event"] += 1
            return
        parent = "usc-calendar-event-" + str(event["id"])
        title = plain(event.get("title"), 300)
        url = str(event.get("localist_url") or "")
        if not url.startswith("https://calendar.usc.edu/") or not title:
            return
        departments = [
            plain(d.get("name"), 120) for d in event.get("departments", []) if isinstance(d, dict)
        ]
        types = [str(t.get("name", "")) for t in event.get("filters", {}).get("event_types", [])]
        tags = [plain(t, 100) for t in event.get("tags", []) if isinstance(t, str)]
        description = plain(event.get("description_text") or event.get("description"), 280)
        for wrapped in event.get("event_instances", []):
            instance = wrapped.get("event_instance", {})
            if instance.get("all_day"):
                self.skipped["all_day_no_time_claim"] += 1
                continue
            try:
                start = datetime.fromisoformat(instance["start"].replace("Z", "+00:00"))
                end = (
                    datetime.fromisoformat(instance["end"].replace("Z", "+00:00"))
                    if instance.get("end")
                    else None
                )
                if start.utcoffset() is None or (end and (end.utcoffset() is None or end < start)):
                    raise ValueError()
            except (ValueError, KeyError, TypeError):
                self.skipped["unverified_event_time"] += 1
                continue
            occurrence = "usc-calendar-occurrence-" + str(instance["id"])
            if occurrence in self.instance_ids:
                continue
            status = (
                "cancelled"
                if event.get("status") in ("cancelled", "canceled")
                else "postponed"
                if event.get("status") == "postponed"
                else "active"
            )
            self.nodes[parent] = {"id": parent, "kind": "Event", "name": title, "status": status}
            attrs = {
                "start": start.isoformat(),
                "end": end.isoformat() if end else None,
                "event_url": url,
                "summary": description or title,
                "departments": "|".join(departments),
                "experience": str(event.get("experience") or ""),
                "registration_url": str(event.get("ticket_url") or ""),
                "date_precision": "published timestamp",
            }
            self.nodes[occurrence] = {
                "id": occurrence,
                "kind": "EventOccurrence",
                "name": title,
                "status": status,
                "attributes": attrs,
            }
            source = self.source(
                "source-" + occurrence,
                url,
                f"USC event: {title}",
                f"{title}. Published start: {start.isoformat()}. "
                f"Departments: {', '.join(departments)}. {description}",
            )
            self.edge("HAS_OCCURRENCE", parent, occurrence, source, self.sources[source]["excerpt"])
            self.topics(
                parent,
                source,
                types + tags,
                " ".join([title, description, *departments, *types, *tags]),
            )
            self.event_ids.add(parent)
            self.instance_ids.add(occurrence)
            self.event_departments.update(departments)
            if (end or start) >= now and status == "active":
                self.upcoming_instances += 1

    def batch(self) -> dict[str, Any]:
        return {
            "sources": list(self.sources.values()),
            "nodes": list(self.nodes.values()),
            "relationships": list(self.edges.values()),
        }


def collect(
    client: PublicFeedClient, term: str, history_days: int = 365
) -> tuple[dict[str, Any], dict[str, Any]]:
    now = datetime.now(UTC)
    builder = UniversityBatchBuilder(now.date())
    schools = client.get("classes.usc.edu", "api/Schools/TermCode", termCode=term)
    if not isinstance(schools, list):
        raise ValueError("USC school feed is not a list")
    failures: list[str] = []

    def school_courses(school: dict[str, Any]) -> list[tuple[dict[str, Any], dict[str, Any]]]:
        programs = {p["prefix"]: p for p in school.get("programs", [])}
        for extra in ({"program": "ANY"}, {}):
            data = client.get(
                "classes.usc.edu",
                "api/Courses/CoursesByTermSchoolProgram",
                termCode=term,
                school=school["prefix"],
                **extra,
            )
            rows = data.get("courses") if isinstance(data, dict) else None
            if isinstance(rows, list) and rows:
                return [
                    (row, programs.get(row.get("prefix"), {"name": row.get("prefix")}))
                    for row in rows
                ]
        result: list[tuple[dict[str, Any], dict[str, Any]]] = []
        for prefix, program in programs.items():
            data = client.get(
                "classes.usc.edu",
                "api/Courses/CoursesByTermSchoolProgram",
                termCode=term,
                school=school["prefix"],
                program=prefix,
            )
            if isinstance(data, dict) and isinstance(data.get("courses"), list):
                result.extend((row, program) for row in data["courses"])
        return result

    with ThreadPoolExecutor(max_workers=4) as pool:
        pending = {pool.submit(school_courses, school): school for school in schools}
        for future in as_completed(pending):
            school = pending[future]
            try:
                for row, program in future.result():
                    builder.course(row, school, program, term)
            except Exception:
                failures.append(str(school["prefix"]))
            print(
                f"Public courses: {school['name']} "
                f"({builder.course_counts[str(school['name'])]} records)",
                flush=True,
            )
    # Upcoming first; archive is distinct, dated evidence and never called upcoming.
    for start in (now.date() - timedelta(days=1), now.date() - timedelta(days=history_days)):
        page = 1
        while page <= 60:
            data = client.get(
                "calendar.usc.edu",
                "api/2/events",
                pp=100,
                page=page,
                start=start.isoformat(),
                days=366,
            )
            for item in data.get("events", []):
                builder.event(item["event"], now)
            info = data.get("page", {})
            print(
                f"Public calendar page {page}: {len(builder.event_ids)} events, "
                f"{len(builder.instance_ids)} dated occurrences",
                flush=True,
            )
            if not info.get("next_page"):
                break
            page += 1
    batch = builder.batch()
    IngestionPipeline.validate(decode(batch))
    report = {
        "checked_at": now.isoformat(),
        "term": term,
        "school_feed_count": len(schools),
        "subject_feed_count": sum(len(s.get("programs", [])) for s in schools),
        "course_count": sum(n["kind"] == "Course" for n in batch["nodes"]),
        "unique_events": len(builder.event_ids),
        "dated_occurrences": len(builder.instance_ids),
        "upcoming_or_ongoing_occurrences": builder.upcoming_instances,
        "courses_by_school": dict(sorted(builder.course_counts.items())),
        "events_by_department": dict(sorted(builder.event_departments.items())),
        "skipped": dict(builder.skipped),
        "failed_schools": failures,
        "inferred_topic_edges": sum(e["fact_type"] == "inferred" for e in batch["relationships"]),
        "limitations": [
            "Timed public listings only; all-day/naive times are skipped rather than invented.",
            "Archived occurrences are dated; recommendation feasibility must exclude expired ones.",
            "No seat availability, degree audit, attendance or student records are imported.",
            "Discipline tags inferred from public metadata are marked inferred.",
        ],
    }
    if (
        report["course_count"] < 500
        or len(builder.course_counts) < 15
        or report["unique_events"] < 100
    ):
        raise ValueError("Public coverage below minimum; refusing to replace the shared snapshot")
    return batch, report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--term", default="20263")
    parser.add_argument("--output", type=Path, default=Path("data/seed/university.json.gz"))
    parser.add_argument("--report", type=Path, default=Path("data/seed/university_report.json"))
    args = parser.parse_args()
    if not re.fullmatch(r"\d{4}[123]", args.term):
        raise SystemExit("Use a public USC term code, e.g. 20263")
    batch, report = collect(PublicFeedClient(), args.term)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(batch, ensure_ascii=False, separators=(",", ":")).encode()
    args.output.write_bytes(gzip.compress(payload, mtime=0))
    args.report.write_text(json.dumps(report, indent=2) + "\n")
    print(
        json.dumps(
            {
                k: report[k]
                for k in (
                    "course_count",
                    "unique_events",
                    "dated_occurrences",
                    "upcoming_or_ongoing_occurrences",
                    "failed_schools",
                )
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
