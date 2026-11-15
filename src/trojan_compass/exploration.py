"""Bridge explicit interests to existing sourced skill links, without inventing a target.

Owned by chat composition. The recommendation engine and graph implementations
remain unchanged; their feasibility, ranking and card composition are reused.
"""

import re

from trojan_compass.contracts import (
    Clarification,
    RecommendationRequest,
    RecommendationResult,
    RecommendationService,
)
from trojan_compass.recommendations.clock import Clock, SystemClock
from trojan_compass.recommendations.explain import Explainer
from trojan_compass.recommendations.feasibility import FeasibilityChecker
from trojan_compass.recommendations.graph import GraphRepository
from trojan_compass.recommendations.preparation import completed_course_names, normalize_code
from trojan_compass.recommendations.ranking import Ranker, RankingPolicy, Scored
from trojan_compass.recommendations.retrieval import Candidate
from trojan_compass.recommendations.service import requested_kind


def interest_name(value: str) -> str:
    text = " ".join(re.sub(r"[^\w\s]", " ", value.casefold()).split())
    for frame in ("i am interested in ", "i enjoy ", "i like ", "interested in "):
        if text.startswith(frame):
            text = text[len(frame) :]
            break
    # These are query synonyms, not student skill assertions or new KG edges.
    return {
        "coding": "computer programming",
        "programming": "computer programming",
        "programming apps or websites": "computer programming",
        "psychology or behavior": "psychology",
        "health or medicine": "medicine",
        "education or social work": "social work",
        "visual art or design": "design",
        "film or storytelling": "film",
        "music or performance": "music",
        "business or entrepreneurship": "business",
        "public policy or social work": "public policy",
        "law or justice": "law",
        "design or architecture": "architecture",
        "engineering or physical systems": "engineering",
    }.get(text, text)


class ExplorationRecommendationService:
    def __init__(
        self, engine: RecommendationService, graph: GraphRepository, clock: Clock | None = None
    ) -> None:
        self._engine = engine
        self._graph = graph
        clock = clock or SystemClock()
        self._feasibility = FeasibilityChecker(clock)
        self._ranker = Ranker(RankingPolicy(), clock)
        self._explainer = Explainer()

    async def recommend(self, request: RecommendationRequest) -> RecommendationResult:
        result = await self._engine.recommend(request)
        if result.recommendations or result.clarification or request.context.target is not None:
            return result

        # Bounded shared-data lookup, never a student cache. Primary engine queries
        # remain authoritative; this only bridges interests to existing skill edges.
        actions = [a for a in await self._graph.browse_actions(30_000) if a.sources]
        interests = request.context.interests + request.context.goals
        names = completed_course_names(request.context)
        completed = await self._graph.find_courses(names) if names else []
        codes = frozenset(normalize_code(n) for n in names) | frozenset(
            normalize_code(a.course.code) for a in completed if a.course
        )
        scored: list[Scored] = []
        paths: dict[str, tuple[str, str, str]] = {}
        known = {interest_name(s.name) for s in request.context.skills if s.status == "known"}
        for action in actions:
            if action.course and normalize_code(action.course.code) in codes:
                continue
            match = next(
                (
                    (interest.value, link)
                    for interest in interests
                    for link in action.skills
                    if interest_name(interest.value)
                    in {
                        interest_name(link.skill.name),
                        *(interest_name(a) for a in link.skill.aliases),
                    }
                ),
                None,
            )
            if match is None:
                topic_match = next(
                    (
                        (interest.value, topic)
                        for interest in interests
                        for topic in action.topics
                        if interest_name(interest.value) == interest_name(topic)
                    ),
                    None,
                )
                if topic_match is None:
                    continue
                feasibility = self._feasibility.check(action, request.context, codes)
                if feasibility.excluded is not None:
                    continue
                candidate = Candidate(action, topics=[topic_match[1]])
                scored.append(
                    Scored(
                        candidate,
                        feasibility,
                        self._ranker.score(
                            candidate, feasibility, requested_kind(request.user_query)
                        ),
                    )
                )
                paths[action.id] = (topic_match[0], topic_match[1], "topic")
                continue
            interest, link = match
            if (
                link.relation == "teaches"
                and link.level != "advanced"
                and interest_name(link.skill.name) in known
            ):
                continue
            feasibility = self._feasibility.check(action, request.context, codes)
            if feasibility.excluded is not None:
                continue
            # A temporary interest score, not a fabricated Topic node. The card's
            # reasons/evidence below name the actual skill relation explicitly.
            candidate = Candidate(action, topics=[interest])
            scored.append(
                Scored(
                    candidate,
                    feasibility,
                    self._ranker.score(candidate, feasibility, requested_kind(request.user_query)),
                )
            )
            paths[action.id] = (interest, link.skill.name, link.relation)

        selected = self._ranker.select(scored, request.limit)
        if selected:
            recommendations = []
            for item in selected:
                action = item.candidate.action
                interest, skill, relation = paths[action.id]
                if relation == "topic":
                    card = self._explainer.build(item)
                    recommendations.append(
                        card.model_copy(
                            update={
                                "why_relevant": [
                                    f"You mentioned “{interest}”; "
                                    f"this option is tagged with {skill}."
                                ],
                                "benefits": card.benefits
                                or [f"Explore {skill} through this sourced campus option."],
                                "evidence_path": [
                                    f"Student interest: {interest}",
                                    f"Topic: {skill}",
                                    f"{action.title} → COVERS → {skill}",
                                ],
                            }
                        )
                    )
                    continue
                verb = {
                    "teaches": "teaches",
                    "practices": "offers practice in",
                    "exposes": "offers exposure to",
                    "networking": "supports conversations about",
                }[relation]
                card = self._explainer.build(item)
                recommendations.append(
                    card.model_copy(
                        update={
                            "why_relevant": [
                                f"You mentioned “{interest}”; this option {verb} {skill}."
                            ],
                            "evidence_path": [
                                f"Student interest: {interest}",
                                f"Skill: {skill}",
                                f"{action.title} → {relation} → {skill}",
                            ],
                        }
                    )
                )
            question = None
            unknowns = selected[0].feasibility.unknown_prerequisite_skills
            if unknowns:
                skill = unknowns[0].name
                question = Clarification(
                    text=f"How comfortable are you with {skill}?",
                    options=["I'm comfortable with it", "I'm still learning it", "I don't know"],
                    requested_fields=[f"skills.{skill.casefold()}"],
                    reason="A recorded prerequisite changes whether this course is a useful fit.",
                )
            return RecommendationResult(
                recommendations=recommendations,
                clarification=question,
                limitations=[
                    "Matched your interest to sourced topic or skill links; eligibility and "
                    "enrollment still need confirmation."
                ],
            )

        usable = [
            a
            for a in actions
            if self._feasibility.check(a, request.context, codes).excluded is None
            and not (a.course and normalize_code(a.course.code) in codes)
        ]
        options = sorted(
            {
                name
                for action in usable
                for name in (
                    *action.topics,
                    *(
                        link.skill.name
                        for link in action.skills
                        if interest_name(link.skill.name) not in known
                    ),
                )
            }
        )[:5]
        return result.model_copy(update={"exploration_options": options})
