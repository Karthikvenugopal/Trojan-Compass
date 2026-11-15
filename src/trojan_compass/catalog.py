"""Full USC course catalog search, used when curated skill links find no match.

The catalog is the normalized public USC Schedule of Classes snapshot produced by
``scripts/fetch_usc_catalog.py``. It is shared public data loaded once at startup;
no student information is stored or logged.

Matching is lexical (BM25 over each course's official title, description and
recommended preparation). Every card quotes the official description text that
matched, so the evidence is USC's own wording, not an inferred skill edge.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from trojan_compass.contracts import (
    CourseDetails,
    Recommendation,
    RecommendationRequest,
    RecommendationResult,
    RecommendationService,
    RetrievalContext,
    Source,
)
from trojan_compass.recommendations.clock import SystemClock
from trojan_compass.recommendations.feasibility import FeasibilityChecker
from trojan_compass.recommendations.graph import GraphRepository
from trojan_compass.recommendations.preparation import completed_course_names, normalize_code
from trojan_compass.recommendations.service import requested_kind

CATALOG_NOTICE = (
    "Course matches come from USC's public Schedule of Classes snapshot ({terms}, fetched "
    "{fetched}). They are ranked by how closely the official course description matches "
    "what you said; check seats, prerequisites and D-clearance on the linked listing."
)

STOPWORDS = frozenset(
    """a about above after again all also am an and any are as at be because been before
    being below between both but by can could did do does doing don done during each etc
    few for from further get got had has have having he her here hers him his how i if in
    into is it its itself just know learn learned learning like me more most my myself no
    nor not now of off on once only or other our out over own really same she should so
    some such than that the their them then there these they this those through to too
    try tried under until up us use used using very want was we were what when where which
    while who whom why will with would yet you your yt youtube video videos level normal
    production experience experiences interested interest interests things thing stuff
    course courses class classes study studying basic basics""".split()
)

# Query expansion for common abbreviations students use. These widen the search
# terms only; evidence still quotes the official description that actually matched.
EXPANSIONS: dict[str, str] = {
    "rag": "retrieval augmented generation information retrieval search",
    "rags": "retrieval augmented generation information retrieval search",
    "llm": "large language models natural language processing",
    "llms": "large language models natural language processing",
    "nlp": "natural language processing",
    "ai": "artificial intelligence",
    "ml": "machine learning",
    "dl": "deep learning neural networks",
    "genai": "generative artificial intelligence",
    "agentic": "agents intelligent agents artificial intelligence",
    "cv": "computer vision",
    "db": "database",
    "dbs": "database",
    "ui": "user interface",
    "ux": "user experience design",
    "os": "operating systems",
}


def tokenize(text: str) -> list[str]:
    words = re.findall(r"[a-z0-9]+", text.casefold())
    return [stem(w) for w in words if w not in STOPWORDS and len(w) > 1]


def stem(word: str) -> str:
    """Tiny suffix stripper; enough to join retrieval/retrieve, models/model."""
    for suffix in ("ations", "ation", "ings", "ing", "ies", "ed", "es", "s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 4:
            word = word[: -len(suffix)]
            if suffix == "ies":
                word += "y"
            break
    for suffix in ("al", "e", "y"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 5:
            return word[: -len(suffix)]
    return word


@dataclass(frozen=True)
class Offering:
    term: str
    label: str
    source_url: str
    active_sections: int
    modes: tuple[str, ...]
    seats_total: int | None
    seats_remaining: int | None
    syllabus_urls: tuple[str, ...]
    instructors: tuple[str, ...] = ()
    schedule: tuple[str, ...] = ()


@dataclass(frozen=True)
class CatalogCourse:
    code: str
    title: str
    level: str
    description: str | None
    recommended_prep: str | None
    units: tuple[str, ...]
    schools: tuple[str, ...]
    programs: tuple[str, ...]
    prerequisites: tuple[str, ...]
    restrictions: tuple[str, ...]
    offerings: tuple[Offering, ...]
    search_text: str = field(repr=False)

    @property
    def best_offering(self) -> Offering | None:
        live = [o for o in self.offerings if o.active_sections > 0] or list(self.offerings)
        return max(live, key=lambda o: o.term) if live else None


@dataclass(frozen=True)
class Hit:
    course: CatalogCourse
    score: float
    matched: tuple[str, ...]
    phrase: str


class CatalogIndex:
    """BM25 index over course title (boosted), description and recommended prep."""

    K1 = 1.4
    B = 0.75
    TITLE_BOOST = 3

    def __init__(self, courses: list[CatalogCourse], terms: dict[str, str], fetched: datetime):
        self.courses = courses
        self.terms = terms
        self.fetched = fetched
        self._docs: list[Counter[str]] = []
        df: Counter[str] = Counter()
        for course in courses:
            tokens = tokenize(course.search_text) + tokenize(course.title) * (self.TITLE_BOOST - 1)
            counts = Counter(tokens)
            self._docs.append(counts)
            df.update(counts.keys())
        n = max(len(courses), 1)
        self._avg = sum(sum(d.values()) for d in self._docs) / n
        self._idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}
        self._by_code = {normalize_code(c.code): c for c in courses}

    @classmethod
    def load(cls, path: Path) -> CatalogIndex:
        payload = json.loads(path.read_text(encoding="utf-8"))
        courses = [_course(raw) for raw in payload["courses"] if raw.get("title")]
        fetched = datetime.fromisoformat(payload["fetched_at"])
        if fetched.utcoffset() is None:
            fetched = fetched.replace(tzinfo=UTC)
        return cls(courses, payload.get("terms", {}), fetched)

    def find(self, code: str) -> CatalogCourse | None:
        return self._by_code.get(normalize_code(code))

    def best_phrase(self, phrases: list[str], matched: tuple[str, ...]) -> str | None:
        """The student phrase whose words (and expansions) best explain the match."""
        wanted = set(matched)

        def weight(phrase: str) -> float:
            tokens = set(tokenize(phrase))
            for word in re.findall(r"[a-z0-9]+", phrase.casefold()):
                tokens.update(tokenize(EXPANSIONS.get(word, "")))
            return sum(self._idf.get(t, 0.0) for t in tokens & wanted)

        best = max(phrases, key=weight, default=None)
        return best if best is not None and weight(best) > 0 else None

    def search(self, phrases: Iterable[str], limit: int, exclude: frozenset[str]) -> list[Hit]:
        phrases = [p for p in dict.fromkeys(p.strip() for p in phrases) if p]
        weights: dict[str, float] = {}
        for phrase in phrases:
            for word in re.findall(r"[a-z0-9]+", phrase.casefold()):
                expansion = EXPANSIONS.get(word)
                for token in tokenize(word):
                    weights[token] = max(weights.get(token, 0.0), 1.0)
                for token in tokenize(expansion or ""):
                    weights[token] = max(weights.get(token, 0.0), 0.6)
        if not weights:
            return []
        hits: list[Hit] = []
        for course, doc in zip(self.courses, self._docs, strict=True):
            if normalize_code(course.code) in exclude:
                continue
            length = sum(doc.values())
            score = 0.0
            matched: list[str] = []
            for token, weight in weights.items():
                tf = doc.get(token, 0)
                if not tf:
                    continue
                matched.append(token)
                norm = (
                    tf * (self.K1 + 1) / (tf + self.K1 * (1 - self.B + self.B * length / self._avg))
                )
                score += weight * self._idf.get(token, 0.0) * norm
            if len(matched) < min(2, len(weights)):
                continue
            text = course.search_text.casefold()
            phrase = next((p for p in phrases if len(p) > 3 and p.casefold() in text), "")
            if phrase:
                score *= 1.5
            best = course.best_offering
            if best is None or best.active_sections == 0:
                score *= 0.6
            elif best.term == min(self.terms or {best.term: ""}):
                score *= 0.85  # only offered in the earliest (likely past) fetched term
            hits.append(Hit(course, score, tuple(matched), phrase))
        hits.sort(key=lambda h: (-h.score, h.course.code))
        return hits[:limit]


class CatalogRecommendationService:
    """Fall back to full-catalog search when the curated graph has no match."""

    def __init__(
        self,
        inner: RecommendationService,
        index: CatalogIndex,
        *,
        graph: GraphRepository | None = None,
    ) -> None:
        self._inner = inner
        self._index = index
        self._graph = graph
        self._feasibility = FeasibilityChecker(SystemClock())

    async def recommend(self, request: RecommendationRequest) -> RecommendationResult:
        """Merge curated graph results with catalog matches.

        Catalog courses whose official text contains a phrase the student used come
        first (most specific), then curated results, then other catalog matches.
        A curated clarification with no results is returned unchanged.
        """
        result = await self._inner.recommend(request)
        if result.clarification or requested_kind(request.user_query) == "event":
            return result
        context = request.context
        phrases = query_phrases(context)
        exclude = frozenset(normalize_code(n) for n in completed_course_names(context))
        # Retrieve a bounded candidate pool before applying the same student-fit
        # constraints as the graph path. No student query/results are cached.
        hits = self._index.search(phrases, max(30, request.limit * 3), exclude)
        completed_names = [
            re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", name.casefold()))
            .strip()
            .removesuffix(" course")
            for name in completed_course_names(context)
        ]
        hits = [
            hit
            for hit in hits
            if not any(
                name
                and len(name.split()) >= 2
                and (name in hit.course.title.casefold() or hit.course.title.casefold() in name)
                for name in completed_names
            )
        ]
        stage = context.study_stage.value.casefold() if context.study_stage else ""
        if "undergrad" in stage:
            hits = [h for h in hits if h.course.level not in ("graduate", "doctoral")]
        hits = [h for h in hits if h.course.offerings]
        canonical_ids: dict[str, str] = {}
        if self._graph is not None and hits:
            completed_actions = await self._graph.find_courses(completed_course_names(context))
            completed_ids = {a.id for a in completed_actions}
            feasible_hits = []
            for hit in hits:
                # Resolve public aliases (e.g. PSYC 100 / PSYC 100L) through the
                # adapter rather than guessing identity by stripping course suffixes.
                actions = await self._graph.find_courses([hit.course.code])
                if actions:
                    canonical_ids[normalize_code(hit.course.code)] = actions[0].id
                    if any(a.id in completed_ids for a in actions):
                        continue
                    if all(
                        self._feasibility.check(a, context, exclude).excluded is not None
                        for a in actions
                    ):
                        continue
                feasible_hits.append(hit)
            hits = feasible_hits
        hits = hits[: request.limit]
        if not hits:
            return result
        strong = [self._card(h, phrases) for h in hits if h.phrase]
        weak = [self._card(h, phrases) for h in hits if not h.phrase]
        merged: list[Recommendation] = []
        seen: set[str] = set()
        states = {a.field: a.status for a in context.answers}
        starting_out = (
            states.get("work_experience") == "none"
            and states.get("completed_courses") == "none"
            and not any(s.status in ("known", "learning") for s in context.skills)
        )
        # Keep the graph's introductory fit ahead of broad lexical matches when
        # the student explicitly reports no experience or completed coursework.
        ordered = (
            [*result.recommendations, *strong, *weak]
            if starting_out
            else [*strong, *result.recommendations, *weak]
        )
        for card in ordered:
            code = normalize_code(card.title.split(":", 1)[0])
            key = canonical_ids.get(
                code,
                card.id
                if card.kind == "course" and not card.id.startswith("usc-catalog-")
                else code,
            )
            if key not in seen:
                seen.add(key)
                merged.append(card)
        merged = merged[: request.limit]
        used_catalog = any(card.id.startswith("usc-catalog-") for card in merged)
        notice = CATALOG_NOTICE.format(
            terms=", ".join(self._index.terms.values()) or "selected terms",
            fetched=self._index.fetched.date().isoformat(),
        )
        return result.model_copy(
            update={
                "recommendations": merged,
                "limitations": [*result.limitations, *([notice] if used_catalog else [])],
                "exploration_options": [],
            }
        )

    def _card(self, hit: Hit, phrases: list[str]) -> Recommendation:
        course = hit.course
        best = course.best_offering
        snippet = _snippet(course.description or course.title, hit.matched)
        mention = hit.phrase or self._index.best_phrase(phrases, hit.matched) or phrases[0]
        sources = [
            Source(
                url=o.source_url,
                title=f"USC Schedule of Classes: {course.code} ({o.label})",
                checked_at=self._index.fetched,
            )
            for o in sorted(course.offerings, key=lambda o: o.term, reverse=True)
        ][:3]
        access = []
        if course.recommended_prep:
            access.append(f"Recommended preparation: {course.recommended_prep}")
        if course.prerequisites:
            access.append("Prerequisites: " + ", ".join(course.prerequisites))
        access += [f"Restriction: {r}" for r in course.restrictions[:3]]
        facts = [f"Level: {course.level}"]
        if course.units:
            facts.append(f"Units: {', '.join(course.units)}")
        if course.schools:
            facts.append(f"Offered by {', '.join(course.schools[:2])}")
        unknowns = [
            "Whether you meet published prerequisites, registration restrictions "
            "or need D-clearance."
        ]
        term = None
        if best is not None:
            seats = ""
            if best.seats_total is not None:
                seats = (
                    f"; {best.seats_remaining} of {best.seats_total} seats open at fetch time"
                    if best.seats_remaining is not None
                    else f"; capacity {best.seats_total}; remaining seats unknown at fetch time"
                )
            status = "scheduled" if best.active_sections else "no active sections"
            term = f"{best.label} ({status}{seats})"
        else:
            unknowns.append("No offering found in the fetched terms.")
        action_url = next(iter(best.syllabus_urls), None) if best else None
        return Recommendation(
            id="usc-catalog-" + normalize_code(course.code),
            kind="course",
            title=f"{course.code}: {course.title}",
            summary=_truncate(course.description or course.title, 600),
            why_relevant=[
                f"You mentioned “{mention}”; USC's official description says: “{snippet}”"
            ],
            benefits=facts,
            prerequisites_or_access=access,
            unknowns=unknowns,
            action_url=action_url or (sources[0].url if sources else None),
            sources=sources,
            evidence_path=[
                f"Your words: {mention}",
                "Matched in official course text: " + ", ".join(hit.matched[:6]),
                f"{course.code}: {course.title}",
            ],
            course=CourseDetails(
                term=term, modality=(", ".join(best.modes) or None) if best else None
            )
            if term
            else CourseDetails(),
            modality=", ".join(best.modes) if best and best.modes else None,
            status=term.split("(", 1)[1].split(";")[0].rstrip(")") if term else None,
        )


def query_phrases(context: RetrievalContext) -> list[str]:
    """Student-stated directions first, then skills/experience as weaker context."""
    phrases = [i.value for i in context.interests + context.goals]
    if context.target:
        phrases.append(context.target.name)
    phrases += [s.name for s in context.skills]
    phrases += [e.value for e in context.experiences]
    # Student-reported completed coursework is useful background for finding
    # the next course; exact course codes are excluded from results above.
    phrases += [course.value for course in context.completed_courses]
    phrases += [
        a.value
        for a in context.answers
        if a.value is not None
        and a.status == "provided"
        and a.field in ("direction", "direction_detail")
    ]
    return [p for p in dict.fromkeys(phrases) if p]


def _snippet(text: str, matched: tuple[str, ...], width: int = 220) -> str:
    sentences = re.split(r"(?<=[.;])\s+", text)
    wanted = set(matched)
    best = max(sentences, key=lambda s: len(wanted.intersection(tokenize(s))))
    return _truncate(best, width)


def _truncate(text: str, width: int) -> str:
    return text if len(text) <= width else text[: width - 1].rsplit(" ", 1)[0] + "…"


def _strings(values: object) -> tuple[str, ...]:
    if not values:
        return ()
    if isinstance(values, str):
        return (values,)
    out = []
    for value in values if isinstance(values, list) else [values]:
        if isinstance(value, str):
            out.append(value)
        elif isinstance(value, dict):
            text = value.get("courseSpace") or value.get("description") or value.get("name")
            if not text:
                text = " ".join(str(v) for v in value.values() if isinstance(v, str))
            if text:
                out.append(" ".join(str(text).split()))
    return tuple(dict.fromkeys(out))


def _course(raw: dict[str, Any]) -> CatalogCourse:
    offerings = tuple(
        Offering(
            term=o["term"],
            label=o.get("term_label", o["term"]),
            source_url=o["source_url"],
            active_sections=int(o.get("active_sections") or 0),
            modes=tuple(o.get("modes") or ()),
            seats_total=o.get("seats_total"),
            seats_remaining=o.get("seats_remaining"),
            syllabus_urls=tuple(u.replace(" ", "%20") for u in o.get("syllabus_urls") or ()),
            instructors=tuple(o.get("instructors") or ()),
            schedule=tuple(o.get("schedule") or ()),
        )
        for o in (raw.get("offerings") or {}).values()
    )
    description = raw.get("description")
    prep = raw.get("recommended_prep")
    restrictions = (
        _strings(raw.get("major_restrictions"))
        + _strings(raw.get("school_restrictions"))
        + _strings(raw.get("course_restrictions"))
    )
    return CatalogCourse(
        code=raw["code"],
        title=raw["title"],
        level=raw.get("level") or "unknown",
        description=description,
        recommended_prep=prep,
        units=tuple(str(u) for u in raw.get("units") or ()),
        schools=tuple(raw.get("schools") or ()),
        programs=tuple(raw.get("programs") or ()),
        prerequisites=_strings(raw.get("prerequisites")),
        restrictions=restrictions,
        offerings=offerings,
        search_text=" ".join(filter(None, [raw["title"], description, prep])),
    )
