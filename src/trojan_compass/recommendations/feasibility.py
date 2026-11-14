"""Can the student actually act on this? Checked only against recorded data.

Rules:
- Known-cancelled, postponed-without-date, already-ended and registration-closed events are
  excluded as upcoming opportunities.
- A course is excluded only on recorded evidence: a prerequisite the student said they
  haven't learned, no listed upcoming offering, or every listed term closed.
- Anything not recorded (eligibility, offerings, registration) becomes an explicit unknown.
  Missing data never turns into an assumption that the student is eligible.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from trojan_compass.contracts import RetrievalContext

from .clock import Clock
from .graph import CampusAction, CourseInfo, EventInfo, SkillNode
from .preparation import normalize_code, skill_status

Readiness = Literal["ready", "partial", "unknown", "blocked"]


@dataclass(frozen=True)
class Feasibility:
    readiness: Readiness
    availability_confirmed: bool
    access: tuple[str, ...] = ()
    unknowns: tuple[str, ...] = ()
    excluded: str | None = None
    unmet_skills: tuple[SkillNode, ...] = ()
    unknown_prerequisite_skills: tuple[SkillNode, ...] = ()
    modality_mismatch: bool = False


def format_when(value: datetime) -> str:
    """Format in the record's own UTC offset; no tz database lookup is needed."""
    return value.strftime("%a %b %d, %Y %I:%M %p (UTC%z)").replace(" 0", " ")


class FeasibilityChecker:
    def __init__(self, clock: Clock) -> None:
        self._clock = clock

    def check(
        self, action: CampusAction, context: RetrievalContext, completed_codes: frozenset[str]
    ) -> Feasibility:
        if not action.sources:
            # Unsourced records are never shown: the student couldn't verify them.
            return Feasibility("unknown", False, excluded="no source is recorded for it")
        if action.course is not None:
            return self._course(action.course, context, completed_codes)
        assert action.event is not None  # guaranteed by CampusAction validation
        return self._event(action.event)

    def _course(
        self, course: CourseInfo, context: RetrievalContext, completed_codes: frozenset[str]
    ) -> Feasibility:
        access: list[str] = []
        unknowns: list[str] = []
        unmet: list[SkillNode] = []
        unknown_skills: list[SkillNode] = []
        partial = False
        unconfirmed = False

        for prereq in course.prerequisites:
            if prereq.course_code and normalize_code(prereq.course_code) in completed_codes:
                access.append(f"Prerequisite met: you completed {prereq.course_code}.")
                continue
            status = skill_status(context, prereq.skill) if prereq.skill else "unknown"
            if status == "known":
                access.append(f"Prerequisite: {prereq.description} (you said you know this).")
            elif status == "learning":
                partial = True
                access.append(
                    f"Prerequisite: {prereq.description}. You said you're still learning it."
                )
            elif status == "not_yet_learned" and prereq.skill is not None:
                unmet.append(prereq.skill)
            else:
                unconfirmed = True
                if prereq.skill is not None:
                    unknown_skills.append(prereq.skill)
                unknowns.append(
                    f"Prerequisite not confirmed: {prereq.description}. Check whether you "
                    "meet it or have an equivalent."
                )

        if unmet:
            names = ", ".join(s.name for s in unmet)
            return Feasibility(
                "blocked",
                False,
                excluded=f"it requires {names}, which you said you haven't learned yet",
                unmet_skills=tuple(unmet),
            )

        for restriction in course.restrictions:
            access.append(f"Restriction listed: {restriction}.")
        if course.restrictions:
            unknowns.append(
                "Whether the listed restriction applies to you isn't known. Check with your "
                "department advisor about D-clearance."
            )

        confirmed = False
        if course.offered_terms is None:
            unknowns.append(
                "Upcoming offerings aren't confirmed. Check the USC Schedule of Classes."
            )
        elif not course.offered_terms:
            return Feasibility("unknown", False, excluded="no upcoming offering is listed")
        elif all(t.status == "closed" for t in course.offered_terms):
            return Feasibility(
                "unknown", False, excluded="enrollment is listed as closed for every term"
            )
        else:
            for offering in course.offered_terms:
                if offering.status == "open":
                    confirmed = True
                    access.append(f"The source lists enrollment for {offering.term} as open.")
                elif offering.status == "scheduled":
                    access.append(
                        f"Listed for {offering.term}. Enrollment status isn't confirmed yet."
                    )
                elif offering.status == "unknown":
                    unknowns.append(f"Enrollment status for {offering.term} isn't listed.")

        preferred = context.constraints.modality.value if context.constraints.modality else None
        mismatch = _modality_mismatch(course.modality, preferred)
        if course.modality:
            access.append(f"Format: {course.modality}.")
        if mismatch:
            unknowns.append(
                f"Listed as {course.modality}, which may not match your preference ({preferred})."
            )

        readiness: Readiness = "ready"
        if partial:
            readiness = "partial"
        elif unconfirmed:
            readiness = "unknown"
        return Feasibility(
            readiness,
            confirmed,
            tuple(access),
            tuple(unknowns),
            unknown_prerequisite_skills=tuple(unknown_skills),
            modality_mismatch=mismatch,
        )

    def _event(self, event: EventInfo) -> Feasibility:
        now = self._clock.now()
        if event.status == "cancelled":
            return Feasibility("ready", False, excluded="the organizer cancelled it")
        if event.status == "postponed":
            return Feasibility("ready", False, excluded="it was postponed with no confirmed date")
        finish = event.end or event.start
        if finish is not None and finish < now:
            return Feasibility("ready", False, excluded="it has already taken place")
        if (
            event.registration_deadline is not None
            and event.registration_deadline < now
            and event.registration_required is not False
        ):
            return Feasibility("ready", False, excluded="its registration deadline has passed")

        access: list[str] = []
        unknowns: list[str] = []
        if event.start is None:
            unknowns.append("The date and time aren't listed yet.")
        else:
            access.append(f"Starts {format_when(event.start)}.")
        if event.status == "unknown":
            unknowns.append("The event's status isn't confirmed by its source.")

        if event.eligibility is None:
            unknowns.append("Eligibility isn't published. Confirm with the organizer.")
        else:
            access.append(f"Eligibility: {', '.join(event.eligibility)}.")

        if event.registration_required is True:
            access.append("Registration required.")
            if event.registration_url is None:
                unknowns.append("A registration link isn't listed.")
        elif event.registration_required is False:
            access.append("No registration required, per the source.")
        else:
            unknowns.append("Registration details aren't listed.")
        if event.registration_deadline is not None:
            access.append(f"Register by {format_when(event.registration_deadline)}.")

        confirmed = event.status == "scheduled" and event.start is not None
        return Feasibility("ready", confirmed, tuple(access), tuple(unknowns))


def _modality_mismatch(listed: str | None, preferred: str | None) -> bool:
    if not listed or not preferred:
        return False
    return listed.strip().casefold() != preferred.strip().casefold()
