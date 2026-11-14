"""Recommendation pipeline: resolve -> analyze -> retrieve -> check feasibility -> rank -> explain.

Statelessness is a design rule, not a convention:
- The engine instance holds only collaborators and configuration, all set in ``__init__``.
- Every student-derived value lives in local variables of ``recommend`` and is released when
  the call returns. Nothing is cached, persisted, logged, or written to the graph.
- Each request is evaluated from scratch, so a corrected skill or an updated graph record
  changes the next result with no stale memory.
"""

import re

from trojan_compass.contracts import (
    Clarification,
    RecommendationRequest,
    RecommendationResult,
    RetrievalContext,
)

from .clock import Clock, SystemClock
from .destination import NOT_SURE, DestinationResolver
from .explain import Explainer, display_title
from .feasibility import Feasibility, FeasibilityChecker
from .graph import GraphRepository
from .preparation import Preparation, PreparationAnalyzer, completed_course_names
from .ranking import ActionKind, Ranker, RankingPolicy, Scored
from .retrieval import ActionRetriever, Bridge, Candidate

MAX_EXCLUSION_NOTES = 3
EVENT_WORDS = re.compile(r"\b(events?|workshops?|meetups?|talks?|panels?|hackathons?)\b", re.I)
COURSE_WORDS = re.compile(r"\b(courses?|class(es)?|enroll\w*)\b", re.I)


def requested_kind(query: str) -> ActionKind | None:
    """A light preference from this message's wording; never a hard filter."""
    wants_event = bool(EVENT_WORDS.search(query))
    wants_course = bool(COURSE_WORDS.search(query))
    if wants_event == wants_course:
        return None
    return "event" if wants_event else "course"


class RecommendationEngine:
    """Implements ``trojan_compass.contracts.RecommendationService``."""

    def __init__(
        self,
        repository: GraphRepository,
        clock: Clock | None = None,
        policy: RankingPolicy | None = None,
    ) -> None:
        clock = clock or SystemClock()
        self._repository = repository
        self._resolver = DestinationResolver(repository)
        self._analyzer = PreparationAnalyzer(repository)
        self._retriever = ActionRetriever(repository)
        self._feasibility = FeasibilityChecker(clock)
        self._ranker = Ranker(policy or RankingPolicy(), clock)
        self._explainer = Explainer()

    async def recommend(self, request: RecommendationRequest) -> RecommendationResult:
        context = request.context
        resolution = await self._resolver.resolve(context)
        course_names = completed_course_names(context)
        completed = await self._repository.find_courses(course_names) if course_names else []
        preparation = await self._analyzer.analyze(resolution, context, completed)
        candidates = await self._retriever.retrieve(preparation, resolution.topics)
        if resolution.broad:
            candidates += await self._retriever.retrieve_broad()

        evaluated, excluded = self._evaluate(candidates, context, preparation)
        bridges = self._bridges(excluded)
        if bridges:
            extra, extra_excluded = self._evaluate(
                await self._retriever.retrieve_bridges(bridges), context, preparation
            )
            _merge(evaluated, extra)
            excluded += extra_excluded

        kind = requested_kind(request.user_query)
        scored = [
            Scored(candidate, feasibility, self._ranker.score(candidate, feasibility, kind))
            for candidate, feasibility in evaluated.values()
            if feasibility.excluded is None and self._ranker.has_benefit(candidate)
        ]
        selected = self._ranker.select(scored, request.limit)

        limitations = [*resolution.limitations, *preparation.limitations]
        limitations += [
            f"Skipped {display_title(c.action)}: {f.excluded}."
            for c, f in excluded[:MAX_EXCLUSION_NOTES]
        ]
        if not selected and (resolution.directions or resolution.topics):
            limitations.append(
                "I couldn't find a sourced campus action that fits right now. I'd rather say "
                "so than suggest something unverified."
            )
        if resolution.broad and selected:
            limitations.append(
                "These are general starting points, not matched to your background yet. "
                "Tell me what you enjoy and I can make them specific."
            )
        if selected:
            limitations.append(
                "Details come from campus sources as last checked. Confirm dates, seats and "
                "eligibility through the linked pages before relying on them."
            )

        return RecommendationResult(
            recommendations=[self._explainer.build(s) for s in selected],
            clarification=resolution.clarification or _skill_clarification(preparation, scored),
            limitations=list(dict.fromkeys(limitations)),
        )

    def _evaluate(
        self, candidates: list[Candidate], context: RetrievalContext, preparation: Preparation
    ) -> tuple[dict[str, tuple[Candidate, Feasibility]], list[tuple[Candidate, Feasibility]]]:
        evaluated: dict[str, tuple[Candidate, Feasibility]] = {}
        excluded: list[tuple[Candidate, Feasibility]] = []
        for candidate in candidates:
            feasibility = self._feasibility.check(
                candidate.action, context, preparation.completed_codes
            )
            evaluated[candidate.action.id] = (candidate, feasibility)
            if feasibility.excluded is not None:
                excluded.append((candidate, feasibility))
        return evaluated, excluded

    @staticmethod
    def _bridges(
        excluded: list[tuple[Candidate, Feasibility]],
    ) -> list[Bridge]:
        """A blocked course points back to actions that teach its missing prerequisite."""
        bridges = []
        for candidate, feasibility in excluded:
            # The origin is what the blocked course would have served (e.g. Machine learning),
            # so the evidence path reads: requirement -> blocked course -> its prerequisite.
            origin = candidate.matches[0].assessment if candidate.matches else None
            for skill in feasibility.unmet_skills:
                bridges.append(Bridge(skill, candidate.action, origin))
        # Explain bridges toward core requirements first.
        bridges.sort(key=lambda b: not (b.origin is not None and b.origin.is_core))
        return bridges


def _merge(
    target: dict[str, tuple[Candidate, Feasibility]],
    extra: dict[str, tuple[Candidate, Feasibility]],
) -> None:
    for action_id, (candidate, feasibility) in extra.items():
        if action_id in target:
            target[action_id][0].bridges.extend(candidate.bridges)
        else:
            target[action_id] = (candidate, feasibility)


def _skill_clarification(preparation: Preparation, scored: list[Scored]) -> Clarification | None:
    """Ask about one core skill only when the answer would change which action fits.

    That is the case when the student hasn't mentioned the skill and either (a) a feasible
    course lists it as an unconfirmed prerequisite, or (b) feasible actions for it span
    introductory and more advanced levels.
    """
    unknown_core = {
        a.skill.id: a
        for a in preparation.assessments
        if a.status == "unknown" and a.is_core and not a.exposure
    }
    if not unknown_core:
        return None

    ranked = sorted(scored, key=lambda s: -s.score.total)
    for item in ranked:
        for skill in item.feasibility.unknown_prerequisite_skills:
            if skill.id in unknown_core:
                return _ask(unknown_core[skill.id].skill.name)

    for skill_id, assessment in unknown_core.items():
        levels = {
            m.link.level
            for s in scored
            for m in s.candidate.matches
            if m.assessment.skill.id == skill_id and m.link.relation == "teaches"
        }
        if "intro" in levels and levels & {"intermediate", "advanced"}:
            return _ask(assessment.skill.name)
    return None


def _ask(skill_name: str) -> Clarification:
    # Path is "skills.<canonical graph name, casefolded>". The chat AskBackPolicy compares
    # that segment with the extracted skill name, so a slug like "data-structures" would
    # never register as answered.
    return Clarification(
        text=f"How comfortable are you with {skill_name}?",
        options=[
            "I'm comfortable with it",
            "I'm still learning it",
            "I haven't learned it yet",
            NOT_SURE,
        ],
        requested_fields=[f"skills.{skill_name.casefold()}"],
        reason="Your answer decides between an introductory option and a more advanced one.",
    )
