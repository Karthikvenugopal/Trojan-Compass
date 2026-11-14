"""Inspectable, rule-based ranking.

Scores are small integers that exist only for ordering. They are never returned to the
student or shown as match percentages; the explanation text carries the reasoning.

Total = relevance + learning benefit + readiness + feasibility + freshness + preference.
Every weight lives in ``RankingPolicy`` so a reviewer can read or tune the rules in one place.
"""

from dataclasses import dataclass
from datetime import timedelta
from typing import Literal

from .clock import Clock
from .feasibility import Feasibility
from .retrieval import Candidate, SkillMatch

ActionKind = Literal["course", "event"]


@dataclass(frozen=True)
class RankingPolicy:
    # Relevance: how directly the action serves the destination's sourced requirements.
    core_requirement: int = 3
    preferred_requirement: int = 1
    team_specific_bonus: int = 2  # a team-specific need is more specific than the baseline
    bridge: int = 3  # unblocks a course the student needs but can't take yet
    interest_topic: int = 1  # tagged with a stated interest only, no requirement path
    max_skills_counted: int = 3  # stop actions that list many skills from winning on volume

    # Learning benefit, from the student's own statements. Unknown earns less than a
    # stated gap because an unmentioned skill is not evidence of a gap.
    not_yet_learned: int = 3
    learning: int = 2
    unknown: int = 1
    known_advanced: int = 1  # known skills still benefit from advanced depth
    exposure_discount: int = 1  # completed coursework already gave some exposure

    # Readiness: prerequisites met > in progress > not confirmed.
    ready: int = 2
    partial: int = 1

    # Feasibility: a confirmed open term or scheduled dated event beats unknown availability.
    availability_confirmed: int = 2
    modality_mismatch: int = -2

    # Freshness of the record's last verification.
    fresh_within: timedelta = timedelta(days=120)
    fresh_bonus: int = 1
    stale_after: timedelta = timedelta(days=365)
    stale_penalty: int = -1

    # The student asked specifically for courses or events in this message.
    requested_kind: int = 2

    # Mixed results: swap in the best action of the other kind only if it scores within
    # this margin of the last selected item. Categories are never forced.
    diversity_margin: int = 2


@dataclass(frozen=True)
class ScoreBreakdown:
    relevance: int
    benefit: int
    readiness: int
    feasibility: int
    freshness: int
    preference: int

    @property
    def total(self) -> int:
        return (
            self.relevance
            + self.benefit
            + self.readiness
            + self.feasibility
            + self.freshness
            + self.preference
        )


@dataclass(frozen=True)
class Scored:
    candidate: Candidate
    feasibility: Feasibility
    score: ScoreBreakdown


class Ranker:
    def __init__(self, policy: RankingPolicy, clock: Clock) -> None:
        self._policy = policy
        self._clock = clock

    def score(
        self, candidate: Candidate, feasibility: Feasibility, requested: ActionKind | None
    ) -> ScoreBreakdown:
        p = self._policy
        # One term per required skill: an event that both introduces and networks around
        # the same skill must not count that skill twice.
        per_skill = {m.assessment.skill.id: self._relevance(m) for m in candidate.matches}
        relevance_terms = sorted(per_skill.values(), reverse=True)
        relevance = sum(relevance_terms[: p.max_skills_counted])
        relevance += p.bridge * min(len(candidate.bridges), 1)
        relevance += p.interest_topic * min(len(candidate.topics), 1)

        benefits = [self._benefit(m) for m in candidate.matches]
        if candidate.bridges:
            benefits.append(p.not_yet_learned)  # bridges exist only for stated gaps
        if candidate.topics and not benefits:
            benefits.append(p.unknown)
        benefit = max(benefits, default=0)

        readiness = {"ready": p.ready, "partial": p.partial}.get(feasibility.readiness, 0)
        feasible = p.availability_confirmed if feasibility.availability_confirmed else 0
        if feasibility.modality_mismatch:
            feasible += p.modality_mismatch

        freshness = 0
        verified = candidate.action.last_verified
        if verified is not None:
            age = self._clock.now() - verified
            if age <= p.fresh_within:
                freshness = p.fresh_bonus
            elif age > p.stale_after:
                freshness = p.stale_penalty

        preference = p.requested_kind if requested == candidate.action.kind else 0
        return ScoreBreakdown(relevance, benefit, readiness, feasible, freshness, preference)

    def has_benefit(self, candidate: Candidate) -> bool:
        """Drop actions that only cover skills the student already knows at this depth."""
        return bool(candidate.bridges or candidate.topics) or any(
            self._benefit(m) > 0 for m in candidate.matches
        )

    def select(self, scored: list[Scored], limit: int) -> list[Scored]:
        ordered = sorted(scored, key=lambda s: (-s.score.total, s.candidate.action.title))
        chosen = ordered[:limit]
        if limit < 2 or len(chosen) < 2:
            return chosen
        kinds = {s.candidate.action.kind for s in chosen}
        if len(kinds) == 1:
            other = next((s for s in ordered[limit:] if s.candidate.action.kind not in kinds), None)
            if (
                other is not None
                and other.score.preference == chosen[-1].score.preference
                and other.score.total >= chosen[-1].score.total - self._policy.diversity_margin
            ):
                chosen[-1] = other
        return chosen

    def _relevance(self, match: SkillMatch) -> int:
        p = self._policy
        primary = match.assessment.primary
        weight = p.core_requirement if match.assessment.is_core else p.preferred_requirement
        if primary.destination.kind == "team":
            weight += p.team_specific_bonus
        return weight

    def _benefit(self, match: SkillMatch) -> int:
        p = self._policy
        status = match.assessment.status
        relation = match.link.relation
        if relation == "teaches":
            if status == "known":
                value = p.known_advanced if match.link.level == "advanced" else 0
            else:
                value = {
                    "not_yet_learned": p.not_yet_learned,
                    "learning": p.learning,
                    "unknown": p.unknown,
                }[status]
        elif relation == "practices":
            # Practice helps most once the basics exist; it is not a substitute for learning.
            value = p.learning if status in ("learning", "known") else p.unknown
        else:  # exposes / networking: useful context, smaller claim
            value = p.unknown
        if match.assessment.exposure and value > 0:
            value = max(value - p.exposure_discount, 0)
        return value
