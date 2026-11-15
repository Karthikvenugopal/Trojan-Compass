"""Evidence-based career coaching composed from shared data and request-local facts.

Career baselines describe occupations, never an employer's hiring bar. Search terms
on baseline skills are retrieval hints, not student facts or invented TEACHES edges.
"""

import re
from importlib.resources import files
from pathlib import Path
from typing import Literal

from pydantic import Field

from trojan_compass.catalog import CatalogCourse, CatalogIndex, tokenize
from trojan_compass.contracts import (
    CareerGuidance,
    CareerOption,
    CareerSkill,
    Clarification,
    Contract,
    GuidanceAction,
    PlanStep,
    Recommendation,
    RetrievalContext,
    Source,
)
from trojan_compass.recommendations.clock import SystemClock
from trojan_compass.recommendations.destination import DestinationResolver
from trojan_compass.recommendations.feasibility import FeasibilityChecker
from trojan_compass.recommendations.graph import GraphRepository, SkillNode
from trojan_compass.recommendations.preparation import (
    PreparationAnalyzer,
    normalize_code,
    skill_status,
)


def key(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", value.casefold()))


class BaselineSkill(Contract):
    name: str
    category: Literal["skill", "knowledge"]
    search_terms: list[str]
    aliases: list[str] = Field(default_factory=list)


class CareerPath(Contract):
    id: str
    title: str
    aliases: list[str]
    topics: list[str]
    skills: list[BaselineSkill]
    source: Source


class ResearchPath(Contract):
    id: str
    title: str
    topics: list[str]
    levels: list[str]
    summary: str
    checks: list[str]
    source: Source


class PathLibrary(Contract):
    roles: list[CareerPath]
    research: list[ResearchPath]

    @classmethod
    def load(cls) -> "PathLibrary":
        resource = files("trojan_compass").joinpath("data", "career_paths.json")
        source = Path(__file__).resolve().parents[2] / "data/seed/career_paths.json"
        return cls.model_validate_json(
            resource.read_text() if resource.is_file() else source.read_text()
        )

    def match(self, name: str) -> CareerPath | None:
        return next(
            (r for r in self.roles if key(name) in {key(r.title), *(key(a) for a in r.aliases)}),
            None,
        )

    def suggestions(self, context: RetrievalContext) -> list[CareerPath]:
        wanted = " ".join(i.value for i in context.interests + context.goals).casefold()
        ranked = sorted(self.roles, key=lambda r: -sum(key(t) in key(wanted) for t in r.topics))
        matched = [r for r in ranked if any(key(t) in key(wanted) for t in r.topics)]
        # No unrelated fallback. Live AI orchestration selects occupations from
        # evidence directly; this compatibility helper only returns actual matches.
        return matched[:3]


class EvidenceCareerGuide:
    """Holds only collaborators and shared public metadata; never student state."""

    def __init__(
        self, graph: GraphRepository, library: PathLibrary, catalog: CatalogIndex | None = None
    ) -> None:
        self._graph = graph
        self._library = library
        self._catalog = catalog

    async def guide(
        self,
        context: RetrievalContext,
        recommendations: list[Recommendation],
        *,
        exploration_role: CareerPath | None = None,
    ) -> CareerGuidance:
        chosen: str | None = context.target.name if context.target else None
        if chosen is None:
            for answer in context.answers:
                if (
                    answer.field == "target"
                    and answer.status == "provided"
                    and answer.value is not None
                ):
                    chosen = answer.value
                    break
        role = (
            self._library.match(chosen)
            if chosen and (context.target is None or context.target.kind == "role")
            else None
        )
        # A possible occupation selected by the AI is evidence scope, not a student target.
        if exploration_role is not None:
            role = exploration_role
        skills: list[CareerSkill] = []
        limitations = [
            "Occupation baselines are not company/team hiring requirements or a readiness score.",
            "Unknown skills are not gaps. Coursework records exposure, not mastery.",
            "Degree, licensure and professional eligibility require separate advisor review.",
        ]
        topics = role.topics if role else [v.value for v in context.interests]
        # Existing KG scopes stay authoritative for explicit company/role/team targets.
        if context.target:
            resolution = await DestinationResolver(self._graph).resolve(context)
            courses = await self._graph.find_courses([c.value for c in context.completed_courses])
            preparation = await PreparationAnalyzer(self._graph).analyze(
                resolution, context, courses
            )
            for assessment in preparation.assessments:
                source_pool = [s for r in assessment.requirements for s in r.requirement.sources]
                stated = next((s for s in context.skills if assessment.skill.matches(s.name)), None)
                skills.append(
                    CareerSkill(
                        name=assessment.skill.name,
                        status=assessment.status,
                        basis="; ".join(r.requirement.statement for r in assessment.requirements),
                        student_evidence=stated.evidence if stated else [],
                        sources=source_pool,
                    )
                )
            limitations.extend(preparation.limitations)
        if role:
            for baseline in role.skills:
                if any(
                    key(s.name) in {key(baseline.name), *(key(a) for a in baseline.aliases)}
                    for s in skills
                ):
                    continue
                node = SkillNode(id=baseline.name, name=baseline.name, aliases=baseline.aliases)
                stated = next((s for s in context.skills if node.matches(s.name)), None)
                skills.append(
                    CareerSkill(
                        name=baseline.name,
                        category=baseline.category,
                        status=skill_status(context, node),
                        student_evidence=stated.evidence if stated else [],
                        basis=f"The occupation source highlights {baseline.name} for {role.title}.",
                        sources=[role.source],
                    )
                )
        if not skills:
            options = [
                CareerOption(
                    id=r.id,
                    title=r.title,
                    why_consider=(
                        "An exploration option related to your interests, not an assigned career."
                        if context.interests
                        else "One of several directions you can compare."
                    ),
                    select_message=f"I want to explore a career as a {r.title}.",
                    sources=[r.source],
                )
                for r in self._library.suggestions(context)
            ]
            exploratory = self._research_actions(context, topics, []) if not chosen else []
            for rec in recommendations[:2] if not chosen else []:
                if rec.action_url:
                    exploratory.append(
                        GuidanceAction(
                            id=rec.id,
                            kind=rec.kind,
                            title=rec.title,
                            summary=rec.summary,
                            why_relevant="A general exploration option; career fit is unconfirmed.",
                            url=rec.action_url,
                            sources=rec.sources,
                            availability="snapshot",
                            checks=rec.unknowns,
                        )
                    )
            return CareerGuidance(
                actions=exploratory,
                mode="coverage_gap" if chosen else "explore",
                goal=chosen,
                headline=(
                    f"Skill expectations for {chosen[:400]} are not covered yet."
                    if chosen
                    else "Let's compare directions before choosing what to study."
                ),
                suggested_paths=options,
                limitations=limitations,
                steps=[
                    PlanStep(
                        id="explore",
                        title="Compare the work, not just the degree",
                        description="Compare occupations and pick a direction to try.",
                    )
                ],
            )
        # Priority is from student self-report, not a fabricated diagnostic test.
        priority = {"not_yet_learned": 0, "learning": 1, "unknown": 2, "known": 3}
        skills.sort(key=lambda s: priority[s.status])
        skills = skills[:12]
        skill_terms = {
            s.name: next((b.search_terms for b in role.skills if b.name == s.name), [s.name])
            if role
            else [s.name]
            for s in skills
        }
        actions = await self._learning_actions(context, skills, skill_terms, role)
        actions += self._research_actions(context, topics, [s.name for s in skills])
        for rec in recommendations:
            if rec.kind == "event" and rec.action_url and len(actions) < 11:
                actions.append(
                    GuidanceAction(
                        id=rec.id,
                        kind="event",
                        title=rec.title,
                        summary=rec.summary,
                        why_relevant="A sourced campus action related to your search.",
                        url=rec.action_url,
                        sources=rec.sources,
                        checks=rec.unknowns,
                        availability="snapshot",
                        term=rec.event.start.isoformat() if rec.event and rec.event.start else None,
                    )
                )
                break
        question = None
        answered = {a.field: a.status for a in context.answers}
        for skill in skills:
            if skill.status == "unknown" and answered.get(
                "skills." + skill.name.casefold()
            ) not in ("unknown", "none"):
                question = Clarification(
                    text=f"How comfortable are you with {skill.name}?",
                    options=[
                        f"I am comfortable with {skill.name}.",
                        f"I am learning {skill.name}.",
                        f"I have not learned {skill.name} yet.",
                        "I don't know",
                    ],
                    requested_fields=["skills." + skill.name.casefold()],
                    reason="This changes which skill we prioritize; unknown does not mean missing.",
                )
                break
        focus = next((s for s in skills if s.status in ("not_yet_learned", "learning")), skills[0])
        learning = [a.id for a in actions if a.kind == "course"][:2]
        experience = [a.id for a in actions if a.kind in ("faculty", "research")]
        steps = [
            PlanStep(
                id="baseline",
                title="Confirm your starting point",
                description="Review the skill check. Unknown skills are not confirmed gaps.",
                skill_names=[s.name for s in skills if s.status == "unknown"],
            ),
            PlanStep(
                id="learn",
                title=f"Work on {focus.name}"
                if focus.status != "known"
                else f"Deepen {focus.name}",
                description="Check access and starting level with an advisor.",
                skill_names=[focus.name],
                action_ids=learning,
                depends_on=["baseline"],
            ),
            PlanStep(
                id="apply",
                title="Apply it with people and research",
                description="Ask instructors and research programs about fit and access.",
                skill_names=[focus.name],
                action_ids=experience,
                depends_on=["learn"],
            ),
            PlanStep(
                id="reflect",
                title="Build evidence and reassess",
                description=(
                    f"Proposed exercise: demonstrate {focus.name} in a small artifact. "
                    "Get feedback and report what you can now do. Completion is not mastery."
                ),
                skill_names=[focus.name],
                depends_on=["apply"],
            ),
        ]
        limitations += [
            "Course text suggests relevance; outcomes, access and enrollment need verification.",
            "Teaching is verified; research fit and supervision availability are unknown.",
            "Research pathways are not confirmed openings. Check eligibility and deadlines.",
        ]
        return CareerGuidance(
            mode="plan",
            goal=chosen or (role.title if role else None),
            headline="Your career direction, skill check and next steps belong in one plan.",
            skills=skills[:12],
            actions=actions[:12],
            steps=steps,
            next_question=question,
            limitations=list(dict.fromkeys(limitations)),
        )

    async def _learning_actions(
        self,
        context: RetrievalContext,
        skills: list[CareerSkill],
        terms: dict[str, list[str]],
        role: CareerPath | None,
    ) -> list[GuidanceAction]:
        if self._catalog is None:
            return []
        excluded = frozenset(normalize_code(v.value) for v in context.completed_courses)
        completed = {
            a.id
            for a in await self._graph.find_courses([v.value for v in context.completed_courses])
        }
        actions: list[GuidanceAction] = []
        selected: list[CatalogCourse] = []
        seen: set[str] = set()
        stage = context.study_stage.value.casefold() if context.study_stage else ""
        for skill in skills:
            if skill.status == "known":
                continue
            phrases = terms[skill.name]
            if role:
                phrases = [*phrases, *role.topics[:1]]
            hits = self._catalog.search(phrases, 30, excluded)
            wanted_tokens = set(tokenize(" ".join(terms[skill.name])))
            candidates = [
                h
                for h in hits
                if h.course.offerings
                and wanted_tokens.intersection(tokenize(h.course.search_text))
                and h.course.code not in seen
                and not ("undergrad" in stage and h.course.level in ("graduate", "doctoral"))
            ]
            # Basic course numbering is an ordering hint, never eligibility or mastery.
            candidates.sort(
                key=lambda h: (
                    not bool(wanted_tokens.intersection(tokenize(h.course.title))),
                    number(h.course.code),
                    -h.score,
                )
            )
            for hit in candidates:
                resolved = await self._graph.find_courses([hit.course.code])
                if any(a.id in completed for a in resolved):
                    continue
                if resolved and all(
                    FeasibilityChecker(SystemClock()).check(a, context, excluded).excluded
                    is not None
                    for a in resolved
                ):
                    continue
                course = hit.course
                offering = course.best_offering
                if offering is None:
                    continue
                seen.add(course.code)
                selected.append(course)
                source = Source(
                    url=offering.source_url,
                    title=f"USC {course.code}: {course.title}",
                    checked_at=self._catalog.fetched,
                )
                actions.append(
                    GuidanceAction(
                        id="plan-course-" + normalize_code(course.code),
                        kind="course",
                        title=f"{course.code}: {course.title}",
                        summary=(course.description or course.title)[:900],
                        why_relevant=f"Course text relates to {skill.name}; verify the outcomes.",
                        skill_names=[skill.name],
                        url=source.url,
                        sources=[*skill.sources[:1], source],
                        availability="snapshot",
                        term=offering.label,
                        checks=[
                            "Seats and your eligibility are not confirmed.",
                            *course.prerequisites,
                            *course.restrictions,
                        ],
                    )
                )
                break
            if len(selected) >= 3:
                break
        people: set[str] = set()
        for course in selected:
            offering = course.best_offering
            if offering is None:
                continue
            for name in offering.instructors[:2]:
                if name.casefold() in people or len(people) >= 3:
                    continue
                people.add(name.casefold())
                source = Source(
                    url=offering.source_url,
                    title=f"USC {course.code}, {offering.label}",
                    checked_at=self._catalog.fetched,
                )
                actions.append(
                    GuidanceAction(
                        id="instructor-" + key(name).replace(" ", "-"),
                        kind="faculty",
                        title=name,
                        summary=f"Listed as an instructor for {course.code} in {offering.label}.",
                        why_relevant="A listed instructor for a learning candidate in this plan.",
                        url=source.url,
                        sources=[source],
                        term=offering.label,
                        checks=[
                            "Verify the current teaching assignment and faculty profile.",
                            "Research fit, office hours and supervision availability are unknown.",
                        ],
                    )
                )
        return actions

    def _research_actions(
        self, context: RetrievalContext, topics: list[str], skills: list[str]
    ) -> list[GuidanceAction]:
        stage = context.study_stage.value.casefold() if context.study_stage else ""
        level = (
            "undergraduate"
            if "undergrad" in stage
            else "graduate"
            if "graduate" in stage
            else "unknown"
        )
        wanted = {key(t) for t in topics}
        paths = [
            p
            for p in self._library.research
            if level in p.levels and (not p.topics or wanted.intersection(key(t) for t in p.topics))
        ]
        paths.sort(key=lambda p: not bool(p.topics))
        return [
            GuidanceAction(
                id=p.id,
                kind="research",
                title=p.title,
                summary=p.summary,
                why_relevant="A related research pathway; check access and openings.",
                skill_names=skills[:2],
                url=p.source.url,
                sources=[p.source],
                checks=p.checks,
                availability="unknown",
            )
            for p in paths[:2]
        ]


def number(code: str) -> int:
    match = re.search(r"\d{3}", code)
    return int(match[0]) if match else 999
