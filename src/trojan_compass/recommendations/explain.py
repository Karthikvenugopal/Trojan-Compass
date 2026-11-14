"""Turn a ranked candidate into the shared ``Recommendation`` contract.

Every sentence comes from a graph record or from the student's own statement for this
request. Wording rules: courses *teach*; events offer *practice, exposure or networking*.
Events never imply proficiency, and networking never implies a job or team placement.
"""

from trojan_compass.contracts import CourseDetails, EventSchedule, Recommendation, Source

from .graph import CampusAction, SkillLink
from .ranking import Scored
from .retrieval import Bridge, SkillMatch

MAX_REASONS = 3
MAX_SOURCES = 6

STATUS_PHRASES = {
    "known": "You said you already know it, so this would add depth.",
    "learning": "You said you're learning it.",
    "not_yet_learned": "You said you haven't learned it yet.",
    "unknown": (
        "You haven't mentioned your background in it, so treat this as worth checking, "
        "not a confirmed gap."
    ),
}
RELATION_VERBS = {
    "teaches": "taught in",
    "practices": "practiced at",
    "exposes": "introduced at",
    "networking": "discussed at",
}
EVENT_CAVEAT = "Attending offers practice and exposure; it doesn't by itself show proficiency."
NETWORKING_CAVEAT = "Networking can start conversations, but it doesn't guarantee a job or team."


class Explainer:
    def build(self, scored: Scored) -> Recommendation:
        candidate = scored.candidate
        action = candidate.action
        unique = {m.assessment.skill.id: m for m in reversed(candidate.matches)}
        matches = sorted(
            unique.values(),
            key=lambda m: (
                not m.assessment.is_core,
                m.assessment.primary.destination.kind != "team",
            ),
        )[:MAX_REASONS]

        reasons = [self._bridge_reason(candidate.bridges)] if candidate.bridges else []
        reasons += [self._match_reason(m) for m in matches]
        reasons += [
            f"Tagged with {topic}, which you said interests you." for topic in candidate.topics[:1]
        ]
        if not reasons and candidate.broad:
            reasons.append(_broad_reason(action))

        return Recommendation(
            id=action.id,
            kind=action.kind,
            title=display_title(action),
            summary=action.summary,
            why_relevant=reasons,
            benefits=self._benefits(action),
            prerequisites_or_access=list(scored.feasibility.access),
            unknowns=list(scored.feasibility.unknowns),
            action_url=action.url,
            sources=self._sources(candidate.action, matches, candidate.bridges),
            evidence_path=self._evidence_path(
                candidate.action, matches, candidate.bridges, candidate.topics
            ),
            event=(
                EventSchedule(
                    start=action.event.start, end=action.event.end, timezone=action.event.timezone
                )
                if action.event
                else None
            ),
            course=CourseDetails(term=_term(action), modality=action.course.modality)
            if action.course
            else None,
            modality=action.course.modality if action.course else None,
            status=_status(action),
        )

    def _match_reason(self, match: SkillMatch) -> str:
        assessment = match.assessment
        primary = assessment.primary
        importance = primary.requirement.importance
        text = (
            f"{primary.destination.label} ({primary.scope_label}) lists "
            f"{assessment.skill.name} as a {importance} requirement. "
            f"{STATUS_PHRASES[assessment.status]}"
        )
        if primary.via_interest:
            text = f"Through your interest in {primary.via_interest}: {text}"
        if assessment.exposure:
            text += (
                f" You've had exposure through {', '.join(assessment.exposure)}; finishing a "
                "course shows exposure, not mastery."
            )
        return text

    @staticmethod
    def _bridge_reason(bridges: list[Bridge]) -> str:
        skill = bridges[0].skill.name
        blocked = list(
            dict.fromkeys(display_title(b.blocked) for b in bridges if b.skill.name == skill)
        )
        verb = "requires" if len(blocked) == 1 else "require"
        return (
            f"Builds {skill}, which {' and '.join(blocked)} {verb}. You said you haven't "
            "learned it yet, so taking this first opens those up."
        )

    @staticmethod
    def _benefits(action: CampusAction) -> list[str]:
        benefits = [_benefit(link) for link in action.skills]
        if action.kind == "event":
            benefits.append(EVENT_CAVEAT)
            if any(link.relation == "networking" for link in action.skills):
                benefits.append(NETWORKING_CAVEAT)
        return list(dict.fromkeys(benefits))

    @staticmethod
    def _sources(
        action: CampusAction, matches: list[SkillMatch], bridges: list[Bridge]
    ) -> list[Source]:
        pool = list(action.sources)
        for match in matches:
            pool += match.assessment.primary.requirement.sources
        for bridge in bridges:
            pool += bridge.blocked.sources
        unique: dict[str, Source] = {}
        for source in pool:
            unique.setdefault(str(source.url), source)
        return list(unique.values())[:MAX_SOURCES]

    @staticmethod
    def _evidence_path(
        action: CampusAction,
        matches: list[SkillMatch],
        bridges: list[Bridge],
        topics: list[str],
    ) -> list[str]:
        """One readable chain from the student's direction to this action."""
        title = display_title(action)
        if bridges:
            bridge = bridges[0]
            path = []
            if bridge.origin is not None:
                path += _requirement_steps(
                    bridge.origin.primary.destination.label,
                    bridge.origin.primary.scope_label,
                    bridge.origin.skill.name,
                    bridge.origin.primary.via_interest,
                )
            path += [
                f"needs {display_title(bridge.blocked)}",
                f"which requires {bridge.skill.name}",
                f"taught in {title}",
            ]
            return path
        if matches:
            match = matches[0]
            primary = match.assessment.primary
            return [
                *_requirement_steps(
                    primary.destination.label,
                    primary.scope_label,
                    match.assessment.skill.name,
                    primary.via_interest,
                ),
                f"{RELATION_VERBS[match.link.relation]} {title}",
            ]
        if topics:
            return [f"Interest: {topics[0]}", f"topic of {title}"]
        return ["Broad starting point", _broad_step(action), title]


def _broad_step(action: CampusAction) -> str:
    return (
        "introductory course with no listed prerequisites"
        if action.course
        else "upcoming campus event"
    )


def _broad_reason(action: CampusAction) -> str:
    return (
        f"A general starting point: an {_broad_step(action)}. It isn't matched to your "
        "background yet."
    )


def _status(action: CampusAction) -> str | None:
    """Short machine-friendly status: the event's recorded status or the best listed term."""
    if action.event is not None:
        return action.event.status
    term = _term(action)
    return term.split("(", 1)[1].rstrip(")") if term else "offering unconfirmed"


def _requirement_steps(
    destination: str, scope: str, skill: str, via_interest: str | None
) -> list[str]:
    steps = [f"Interest: {via_interest}"] if via_interest else []
    return [*steps, f"{destination} ({scope})", f"requires {skill}"]


def _benefit(link: SkillLink) -> str:
    level = f" ({link.level} level)" if link.level else ""
    return {
        "teaches": f"Structured coursework in {link.skill.name}{level}.",
        "practices": f"Hands-on practice with {link.skill.name}.",
        "exposes": f"An introduction to {link.skill.name}.",
        "networking": f"A chance to meet people working on {link.skill.name}.",
    }[link.relation]


def display_title(action: CampusAction) -> str:
    if action.course and not action.title.startswith(action.course.code):
        return f"{action.course.code}: {action.title}"
    return action.title


def _term(action: CampusAction) -> str | None:
    """Only report a term the source lists; never imply open enrollment without data."""
    if not action.course or not action.course.offered_terms:
        return None
    for status in ("open", "scheduled", "unknown"):
        for offering in action.course.offered_terms:
            if offering.status == status:
                suffix = {
                    "open": "enrollment open",
                    "scheduled": "scheduled",
                    "unknown": "status unconfirmed",
                }[status]
                return f"{offering.term} ({suffix})"
    return None
