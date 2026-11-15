"""Generate varied MOCK Handshake events (Handshake's API is private).

Every record is synthetic and flagged ``is_mock``; employers are fictional. The shape
follows a Handshake event export (name, type, employer, start/end, medium, audience,
RSVP) so a real feed can replace this file later without code changes.

Usage: python scripts/generate_handshake_mock.py   ->   data/mock/handshake_events.json
"""

from __future__ import annotations

import json
import random
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data" / "mock" / "handshake_events.json"
TZ = ZoneInfo("America/Los_Angeles")
FIRST_DAY = datetime(2026, 11, 17, tzinfo=TZ)
HANDSHAKE_URL = "https://usc.joinhandshake.com/"

VITERBI = "Viterbi School of Engineering"
MARSHALL = "Marshall School of Business"
DORNSIFE = "Dornsife College of Letters, Arts and Sciences"
KECK = "Keck School of Medicine"
SCA = "Cinematic Arts"
ANNENBERG = "Annenberg School for Communication and Journalism"
PRICE = "Price School of Public Policy"
PHARMACY = "Alfred E. Mann School of Pharmacy and Pharmaceutical Sciences"
THORNTON = "Thornton School of Music"

AREAS: dict[str, dict[str, list[str]]] = {
    "AI and machine learning": {
        "schools": [VITERBI, DORNSIFE],
        "skills": [
            "machine learning",
            "artificial intelligence",
            "deep learning",
            "natural language processing",
            "computer vision",
            "information retrieval",
            "large language models",
            "reinforcement learning",
        ],
        "employers": ["Nimbus Labs", "Cardinal AI", "Figueroa Research", "Lumen Robotics"],
    },
    "Software engineering": {
        "schools": [VITERBI],
        "skills": [
            "software engineering",
            "python programming",
            "algorithms",
            "data structures",
            "web development",
            "cloud computing",
            "database systems",
            "operating systems",
        ],
        "employers": ["Exposition Software", "Vermont Avenue Systems", "Trousdale Cloud"],
    },
    "Data science and analytics": {
        "schools": [VITERBI, MARSHALL, DORNSIFE],
        "skills": [
            "data analysis",
            "data visualization",
            "statistics",
            "data science",
            "data mining",
            "sql",
            "data analytics",
        ],
        "employers": ["Jefferson Analytics", "Bovard Insights", "McCarthy Data Co."],
    },
    "Robotics and hardware": {
        "schools": [VITERBI],
        "skills": [
            "robotics",
            "embedded systems",
            "control systems",
            "computer architecture",
            "signal processing",
            "vlsi design",
        ],
        "employers": ["Hoover Dynamics", "Lumen Robotics", "Parkside Semiconductors"],
    },
    "Finance and consulting": {
        "schools": [MARSHALL],
        "skills": [
            "investment banking",
            "financial analysis",
            "corporate finance",
            "consulting",
            "financial accounting",
            "valuation",
        ],
        "employers": ["Adams Capital", "Hill Street Partners", "Cromwell Advisory"],
    },
    "Entrepreneurship and product": {
        "schools": [MARSHALL, VITERBI],
        "skills": [
            "entrepreneurship",
            "product management",
            "marketing",
            "business strategy",
            "leadership",
            "project management",
        ],
        "employers": ["Founders Row", "Village Ventures", "Gateway Product Studio"],
    },
    "Health and life sciences": {
        "schools": [KECK, PHARMACY, DORNSIFE],
        "skills": [
            "public health",
            "pharmacology",
            "clinical research",
            "epidemiology",
            "biostatistics",
            "health policy",
            "cell biology",
        ],
        "employers": ["Soto Health Partners", "Alcazar Biotech", "Mission Clinical Research"],
    },
    "Film, games and media": {
        "schools": [SCA, ANNENBERG],
        "skills": [
            "film production",
            "screenwriting",
            "game design",
            "film directing",
            "storytelling",
            "animation",
            "journalism",
        ],
        "employers": ["Shrine Pictures", "Leavey Interactive", "McClintock Media"],
    },
    "Policy and social impact": {
        "schools": [PRICE, DORNSIFE],
        "skills": [
            "policy analysis",
            "urban planning",
            "public policy",
            "nonprofit management",
            "research methods",
            "public administration",
        ],
        "employers": ["Civic Compass", "LA Metro Futures Lab", "Watt Way Foundation"],
    },
    "Music and performance": {
        "schools": [THORNTON],
        "skills": ["music production", "music composition", "music industry", "performance"],
        "employers": ["Ramo Records", "Bing Stage Collective"],
    },
}

TYPES = [
    ("Employer Info Session", "{employer} info session: careers in {area}", 60),
    ("Tech Talk", "{employer} talk: {skill} in practice", 75),
    ("Workshop", "Hands-on workshop: {skill} for beginners", 90),
    ("Networking Mixer", "{area} networking mixer with alumni", 120),
    ("Alumni Panel", "Trojan alumni panel: paths into {area}", 75),
    ("Coffee Chat", "Coffee chats with {employer} ({skill})", 45),
    ("Case Competition", "{employer} student challenge: {skill}", 240),
    ("Site Visit", "{employer} site visit for {area} students", 180),
]
CAREER_SERVICES = [
    ("Resume Review", "Resume review drop-ins", ["resume writing"], 120),
    ("Workshop", "Interview practice lab", ["interviewing"], 90),
    (
        "Workshop",
        "Build your elevator pitch",
        ["professional elevator pitch", "public speaking"],
        60,
    ),
    ("Workshop", "Networking 101 for first-time job seekers", ["career networking"], 60),
    ("Career Fair", "Spring Career and Internship Fair preview night", ["career networking"], 180),
    ("Workshop", "Finding on-campus research positions", ["research methods"], 60),
    ("Workshop", "CPT and OPT basics for international students", ["career planning"], 75),
    ("Career Fair", "Graduate student career fair", ["career networking", "interviewing"], 240),
]
ROOMS = [
    "Ronald Tutor Campus Center, Room 227",
    "Epstein Family Alumni Center",
    "Ginsburg Hall auditorium",
    "Fertitta Hall, JFF 240",
    "Seeley G. Mudd, SGM 123",
    "Annenberg Wallis Hall forum",
    "Michelson Center, MCB 101",
    "Leavey Library auditorium",
]
YEARS = ["Freshman", "Sophomore", "Junior", "Senior", "Masters", "Doctorate"]


def main() -> int:
    rng = random.Random(2026)
    events: list[dict[str, object]] = []

    def add(
        name: str,
        kind: str,
        employer: str | None,
        industry: str | None,
        skills: list[str],
        schools: list[str],
        minutes: int,
        description: str,
    ) -> None:
        day = FIRST_DAY + timedelta(days=rng.randrange(0, 112))
        while day.weekday() >= 5 and kind != "Case Competition":
            day += timedelta(days=1)
        start = day.replace(hour=rng.choice([10, 12, 14, 16, 17, 18]), minute=rng.choice([0, 30]))
        medium = rng.choices(["in_person", "virtual", "hybrid"], [5, 3, 2])[0]
        number = 900000 + len(events) + 1
        events.append(
            {
                "id": f"hs-mock-{number}",
                "name": name,
                "event_type": kind,
                "employer": {"name": employer, "industry": industry} if employer else None,
                "host": employer or "USC Career Center",
                "start_date": start.isoformat(),
                "end_date": (start + timedelta(minutes=minutes)).isoformat(),
                "time_zone": "America/Los_Angeles",
                "medium": medium,
                "location": "Zoom (link after RSVP)" if medium == "virtual" else rng.choice(ROOMS),
                "description": description,
                "skills": skills,
                "audience": {
                    "schools": schools,
                    "class_years": sorted(rng.sample(YEARS, rng.randint(2, 6)), key=YEARS.index),
                },
                "registration_required": kind not in ("Resume Review", "Coffee Chat"),
                "rsvp_url": HANDSHAKE_URL,
                "is_mock": True,
            }
        )

    for area, spec in AREAS.items():
        for kind, template, minutes in TYPES:
            if rng.random() < 0.2:
                continue
            employer = rng.choice(spec["employers"])
            skills = rng.sample(spec["skills"], k=min(len(spec["skills"]), rng.randint(2, 3)))
            name = template.format(employer=employer, area=area.lower(), skill=skills[0])
            add(
                name,
                kind,
                None if kind in ("Networking Mixer", "Alumni Panel") else employer,
                area,
                skills,
                spec["schools"],
                minutes,
                f"Sample {kind.lower()} about {', '.join(skills)}. "
                "Meet people working in the field and ask how they got started.",
            )
    for kind, name, skills, minutes in CAREER_SERVICES:
        add(name, kind, None, None, skills, [], minutes, f"Sample career-center {kind.lower()}.")

    events.sort(key=lambda e: str(e["start_date"]))
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(
            {
                "notice": "MOCK DATA. Handshake's API is private; these events are synthetic "
                "samples with fictional employers, generated for the hackathon demo.",
                "source_url": HANDSHAKE_URL,
                "events": events,
            },
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )
    kinds = sorted({str(e["event_type"]) for e in events})
    print(f"wrote {OUTPUT.relative_to(ROOT)}: {len(events)} mock events, types: {kinds}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
