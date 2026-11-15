"""In-memory campus knowledge graph built from public USC data at startup.

Nodes and edges (all shared public data; nothing about a student is stored):

    Skill  <-TEACHES-  Course  -HAS_PREREQUISITE->  Course
    Course -TAUGHT_BY-> Professor -RESEARCHES-> Skill
    Event  -COVERS->   Skill

Sources: courses, prerequisites and instructors come from the USC Schedule of Classes
snapshot; TEACHES links are inferred from official course descriptions
(``scripts/tag_course_skills.py``); professor research comes from USC Viterbi faculty
directories; events are MOCK Handshake samples because Handshake's API is private.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from trojan_compass.catalog import EXPANSIONS, CatalogCourse, CatalogIndex, tokenize
from trojan_compass.recommendations.preparation import normalize_code


def skill_id(name: str) -> str:
    return "skill:" + re.sub(r"[^a-z0-9]+", "-", name.casefold()).strip("-")


ACRONYMS = frozenset(
    "ai ml nlp it sql ux ui vlsi ct mri 3d 2d usc cpt opt api apis gpu gpus iot ar vr xr "
    "cad dna rna hiv aids llm llms rag gis seo crm erp hr pr tv c++ css html r".split()
)


def display_name(name: str) -> str:
    """'ai applications' -> 'AI applications'; the first letter is capitalized."""
    words = [w.upper() if w in ACRONYMS else w for w in name.strip().casefold().split()]
    text = " ".join(words)
    return text[:1].upper() + text[1:]


def person_key(name: str) -> str:
    return re.sub(r"[^a-z ]+", "", name.casefold().replace("-", " ")).strip()


@dataclass
class Skill:
    id: str
    name: str
    courses: list[str] = field(default_factory=list)  # course codes; central skill first
    professors: list[str] = field(default_factory=list)
    events: list[str] = field(default_factory=list)


@dataclass
class Professor:
    id: str
    name: str
    title: str | None = None
    departments: tuple[str, ...] = ()
    profile_url: str | None = None
    research_text: str | None = None
    areas: list[str] = field(default_factory=list)  # skill ids
    courses: dict[str, list[str]] = field(default_factory=dict)  # code -> term labels


@dataclass(frozen=True)
class CampusEvent:
    id: str
    title: str
    event_type: str
    host: str
    start: datetime
    end: datetime
    timezone: str
    medium: str
    location: str
    description: str
    skills: tuple[str, ...]  # skill ids
    schools: tuple[str, ...]
    url: str
    is_mock: bool


@dataclass(frozen=True)
class SkillCandidate:
    skill: Skill
    score: float


class KnowledgeGraph:
    def __init__(
        self,
        catalog: CatalogIndex,
        course_skills: dict[str, list[str]],
        prerequisites: dict[str, list[list[str]]],
        faculty: list[dict[str, Any]],
        events: list[dict[str, Any]],
    ) -> None:
        self.catalog = catalog
        self.skills: dict[str, Skill] = {}
        self.course_skills: dict[str, list[str]] = {}
        self.prerequisites = prerequisites
        self.professors: dict[str, Professor] = {}
        self.course_professors: dict[str, list[str]] = defaultdict(list)
        self.events: dict[str, CampusEvent] = {}
        self._courses = {normalize_code(c.code): c for c in catalog.courses}
        terms = sorted(catalog.terms)
        self.upcoming_term = terms[-1] if terms else None

        for code, names in course_skills.items():
            if normalize_code(code) not in self._courses:
                continue
            ids = []
            for name in names:
                skill = self._skill(name)
                skill.courses.append(code)
                ids.append(skill.id)
            self.course_skills[normalize_code(code)] = ids

        for course in catalog.courses:
            for offering in course.offerings:
                for name in offering.instructors:
                    key = person_key(name)
                    if not key:
                        continue
                    professor = self.professors.setdefault(
                        key, Professor(id=f"prof:{key.replace(' ', '-')}", name=name)
                    )
                    labels = professor.courses.setdefault(course.code, [])
                    if offering.label not in labels:
                        labels.append(offering.label)
                    ids = self.course_professors[normalize_code(course.code)]
                    if key not in ids:
                        ids.append(key)
        self._attach_faculty(faculty)
        self._attach_events(events)

        # Skill-name search index.
        self._skill_tokens = {s.id: tokenize(s.name) for s in self.skills.values()}
        df: Counter[str] = Counter()
        for tokens in self._skill_tokens.values():
            df.update(set(tokens))
        n = max(len(self.skills), 1)
        self._idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}
        self._by_token: dict[str, list[str]] = defaultdict(list)
        for sid, tokens in self._skill_tokens.items():
            for token in set(tokens):
                self._by_token[token].append(sid)

    # ---- construction -------------------------------------------------

    @classmethod
    def load(
        cls,
        catalog: CatalogIndex,
        catalog_path: Path,
        skills_path: Path,
        faculty_path: Path | None = None,
        events_path: Path | None = None,
    ) -> KnowledgeGraph:
        raw = json.loads(catalog_path.read_text(encoding="utf-8"))
        prerequisites: dict[str, list[list[str]]] = {}
        for course in raw["courses"]:
            groups = []
            for group in course.get("prerequisites") or []:
                options = [
                    str(o["courseSpace"])
                    for o in (group.get("courseOptions") or [])
                    if isinstance(o, dict) and o.get("courseSpace")
                ]
                if options:
                    groups.append(list(dict.fromkeys(options)))
            if groups:
                prerequisites[normalize_code(course["code"])] = groups
        course_skills = json.loads(skills_path.read_text(encoding="utf-8"))
        faculty = []
        if faculty_path is not None and faculty_path.is_file():
            faculty = json.loads(faculty_path.read_text(encoding="utf-8")).get("faculty", [])
        events = []
        if events_path is not None and events_path.is_file():
            events = json.loads(events_path.read_text(encoding="utf-8")).get("events", [])
        return cls(catalog, course_skills, prerequisites, faculty, events)

    def _skill(self, name: str) -> Skill:
        sid = skill_id(name)
        skill = self.skills.get(sid)
        if skill is None:
            skill = self.skills[sid] = Skill(id=sid, name=display_name(name))
        return skill

    def _attach_faculty(self, faculty: list[dict[str, Any]]) -> None:
        """Match directory profiles to Schedule of Classes instructors by name."""
        by_last: dict[str, list[str]] = defaultdict(list)
        for key in self.professors:
            by_last[key.split()[-1]].append(key)
        for record in faculty:
            first = person_key(str(record.get("first_name") or "")).split()
            lasts = set(person_key(str(record.get("last_name") or "")).split())
            display = person_key(str(record.get("name") or "")).split()
            if display:
                lasts.add(display[-1])
            # Schedule of Classes truncates long first names, so allow a long prefix;
            # otherwise the first name must match exactly (avoids "Jen" ~ "Jenny").
            firsts = {n for n in (first[:1] + display[:1]) if n}
            match = next(
                (
                    key
                    for last in lasts
                    for key in by_last.get(last, [])
                    if any(
                        key.split()[0] == n
                        or (len(key.split()[0]) >= 10 and n.startswith(key.split()[0]))
                        for n in firsts
                    )
                ),
                None,
            )
            name = " ".join(str(record.get("name") or "").split())
            if match is None:
                # Research-only faculty (not teaching in the fetched terms) are still
                # useful "people to explore" nodes.
                match = person_key(name)
                if not match:
                    continue
                self.professors.setdefault(
                    match, Professor(id=f"prof:{match.replace(' ', '-')}", name=name)
                )
            professor = self.professors[match]
            professor.title = str(record.get("title") or "") or None
            professor.departments = tuple(record.get("departments") or ())
            professor.profile_url = record.get("profile_url")
            professor.research_text = str(record.get("research_text") or "") or None
            for area in record.get("areas") or []:
                skill = self._skill(str(area))
                if skill.id not in professor.areas:
                    professor.areas.append(skill.id)
                if match not in skill.professors:
                    skill.professors.append(match)

    def _attach_events(self, events: list[dict[str, Any]]) -> None:
        for record in events:
            try:
                start = datetime.fromisoformat(record["start_date"])
                end = datetime.fromisoformat(record["end_date"])
            except (KeyError, ValueError):
                continue
            ids = []
            for name in record.get("skills") or []:
                skill = self._skill(str(name))
                ids.append(skill.id)
                skill.events.append(record["id"])
            audience = record.get("audience") or {}
            self.events[record["id"]] = CampusEvent(
                id=record["id"],
                title=record["name"],
                event_type=record.get("event_type") or "Event",
                host=record.get("host") or "USC Career Center",
                start=start,
                end=end,
                timezone=record.get("time_zone") or "America/Los_Angeles",
                medium=str(record.get("medium") or "in_person").replace("_", " "),
                location=record.get("location") or "",
                description=record.get("description") or "",
                skills=tuple(ids),
                schools=tuple(audience.get("schools") or ()),
                url=record.get("rsvp_url") or "https://usc.joinhandshake.com/",
                is_mock=bool(record.get("is_mock", True)),
            )

    # ---- queries ------------------------------------------------------

    def course(self, code: str) -> CatalogCourse | None:
        return self._courses.get(normalize_code(code))

    def skills_of(self, code: str) -> list[Skill]:
        return [self.skills[s] for s in self.course_skills.get(normalize_code(code), [])]

    def professors_of(self, code: str) -> list[Professor]:
        return [self.professors[k] for k in self.course_professors.get(normalize_code(code), [])]

    def find_skill(self, name: str) -> Skill | None:
        return self.skills.get(skill_id(name))

    def candidate_skills(self, phrases: list[str], limit: int = 40) -> list[SkillCandidate]:
        """Skills a student's words may refer to: by skill name and via course text."""
        weights: dict[str, float] = {}
        for phrase in phrases:
            for word in re.findall(r"[a-z0-9+#]+", phrase.casefold()):
                for token in tokenize(word):
                    weights[token] = max(weights.get(token, 0.0), 1.0)
                for token in tokenize(EXPANSIONS.get(word, "")):
                    weights[token] = max(weights.get(token, 0.0), 0.6)
        scores: dict[str, float] = defaultdict(float)
        seen: dict[str, set[str]] = defaultdict(set)
        for token, weight in weights.items():
            for sid in self._by_token.get(token, []):
                if token not in seen[sid]:
                    seen[sid].add(token)
                    scores[sid] += weight * self._idf.get(token, 0.0)
        for sid in list(scores):
            tokens = set(self._skill_tokens[sid])
            coverage = len(seen[sid]) / max(len(tokens), 1)
            skill = self.skills[sid]
            # Skills fully named by the student's words rank first; shared skills
            # (taught by several courses) are more useful than one-off labels.
            scores[sid] *= 0.35 + 0.65 * coverage
            scores[sid] *= 1.0 + 0.12 * math.log1p(len(skill.courses) + len(skill.professors))
            if not skill.courses and not skill.professors:
                scores[sid] *= 0.3
        lowered = [p.casefold() for p in phrases]
        for sid, skill in self.skills.items():
            if len(skill.name) > 3 and any(skill.name.casefold() in p for p in lowered):
                scores[sid] = scores.get(sid, 0.0) * 1.5 + 4.0
        hits = self.catalog.search(phrases, 15, frozenset())
        top = max((h.score for h in hits), default=0.0)
        if top > 0:
            best = max(scores.values(), default=1.0) or 1.0
            for hit in hits:
                ids = self.course_skills.get(normalize_code(hit.course.code), [])
                for position, sid in enumerate(ids):
                    share = 0.7 if position == 0 else 0.4
                    scores[sid] += best * share * (hit.score / top)
        ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0]))[:limit]
        return [SkillCandidate(self.skills[sid], score) for sid, score in ranked if score > 0]

    def upcoming_events(self, now: datetime | None = None) -> list[CampusEvent]:
        now = now or datetime.now(UTC)
        return sorted((e for e in self.events.values() if e.end > now), key=lambda e: e.start)

    def stats(self) -> dict[str, int]:
        teaches = sum(len(v) for v in self.course_skills.values())
        prereq = sum(len(g) for groups in self.prerequisites.values() for g in groups)
        taught = sum(len(v) for v in self.course_professors.values())
        research = sum(len(p.areas) for p in self.professors.values())
        covers = sum(len(e.skills) for e in self.events.values())
        return {
            "courses": len(self._courses),
            "skills": len(self.skills),
            "professors": len(self.professors),
            "professors_with_research": sum(1 for p in self.professors.values() if p.areas),
            "events": len(self.events),
            "edges_teaches": teaches,
            "edges_prerequisite": prereq,
            "edges_taught_by": taught,
            "edges_researches": research,
            "edges_covers": covers,
            "edges": teaches + prereq + taught + research + covers,
        }
