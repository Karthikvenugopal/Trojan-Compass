"""Behavioral tests for the recommendation engine against the synthetic graph fixture.

Student context uses the v2 ``RetrievalContext`` shape with synthetic quotations.
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from trojan_compass.contracts import (
    RecommendationRequest,
    RecommendationResult,
    RecommendationService,
    RetrievalContext,
)
from trojan_compass.recommendations import FixedClock, RecommendationEngine
from trojan_compass.recommendations.destination import DestinationResolver
from trojan_compass.recommendations.fake_repository import InMemoryGraphRepository
from trojan_compass.recommendations.graph import EventInfo
from trojan_compass.recommendations.preparation import PreparationAnalyzer
from trojan_compass.recommendations.synthetic_graph import ACTIONS, synthetic_repository

PACIFIC = timezone(timedelta(hours=-8))
NOW = datetime(2026, 11, 14, 12, 0, tzinfo=PACIFIC)


def make_engine(
    repo: InMemoryGraphRepository | None = None, now: datetime = NOW
) -> RecommendationEngine:
    return RecommendationEngine(repo or synthetic_repository(), clock=FixedClock(now))


def evidence(quote: str) -> list[dict[str, Any]]:
    return [{"message_index": 0, "quote": quote}]


def supported(value: str) -> dict[str, Any]:
    return {"value": value, "evidence": evidence(f"Synthetic statement about {value}.")}


def skill(name: str, status: str) -> dict[str, Any]:
    return {"name": name, "status": status, "evidence": evidence(f"Synthetic: {name} {status}.")}


def target(kind: str, name: str, company: str | None = None) -> dict[str, Any]:
    return {
        "kind": kind,
        "name": name,
        "company_name": company,
        "evidence": evidence(f"Synthetic: I want {name}."),
    }


def context(**fields: Any) -> dict[str, Any]:
    """Plain strings for list-of-SupportedText fields are wrapped with synthetic evidence."""
    for key in ("interests", "completed_courses", "goals", "experiences"):
        if key in fields:
            fields[key] = [supported(v) for v in fields[key]]
    return fields


def make_request(
    query: str = "What should I do next?", limit: int = 3, **fields: Any
) -> RecommendationRequest:
    return RecommendationRequest.model_validate(
        {"context": context(**fields), "user_query": query, "limit": limit}
    )


def offers_not_sure(result: RecommendationResult) -> bool:
    assert result.clarification is not None
    return any("not sure" in option.casefold() for option in result.clarification.options)


async def run(
    request: RecommendationRequest, engine: RecommendationEngine | None = None
) -> RecommendationResult:
    return await (engine or make_engine()).recommend(request)


def ids(result: RecommendationResult) -> list[str]:
    return [r.id for r in result.recommendations]


def by_id(result: RecommendationResult, action_id: str) -> Any:
    return next(r for r in result.recommendations if r.id == action_id)


def text(result: RecommendationResult) -> str:
    return result.model_dump_json()


# --- Interface -----------------------------------------------------------------------------


def test_engine_satisfies_shared_protocol() -> None:
    service: RecommendationService = make_engine()
    assert asyncio.iscoroutinefunction(service.recommend)


# --- Destination resolution -----------------------------------------------------------------


async def test_role_alias_resolves() -> None:
    result = await run(make_request(target=target("role", "swe")))
    assert result.recommendations
    assert any(
        "Software Engineer (role baseline)" in r.evidence_path for r in result.recommendations
    )


async def test_ambiguous_team_asks_once_and_still_explores_interests() -> None:
    result = await run(make_request(target=target("team", "Platform"), interests=["robotics"]))
    assert result.clarification is not None
    assert result.clarification.requested_fields == ["target"]
    assert set(result.clarification.options) == {
        "Platform team at Nimbus Robotics (team)",
        "Platform team at Orbit Cloud (team)",
        "I'm not sure",
    }
    assert result.recommendations, "ambiguity must not block interest-grounded results"


async def test_company_name_disambiguates_team() -> None:
    result = await run(
        make_request(
            target=target("team", "Platform", "Orbit Cloud"), completed_courses=["SYN 201"]
        )
    )
    assert result.clarification is None or result.clarification.requested_fields != ["target"]
    dist = by_id(result, "course-syn450")
    assert "Platform team at Orbit Cloud (team-specific)" in dist.evidence_path
    assert "Prerequisite met: you completed SYN 201." in dist.prerequisites_or_access


async def test_company_with_several_roles_asks_and_gives_provisional_results() -> None:
    result = await run(make_request(target=target("company", "Nimbus")))
    assert result.clarification is not None
    assert result.clarification.text == "What kind of work at Nimbus Robotics interests you most?"
    assert result.clarification.requested_fields == ["target"]
    assert offers_not_sure(result)
    assert result.recommendations


async def test_unknown_target_is_not_invented() -> None:
    result = await run(make_request(target=target("company", "Zeta Corp")))
    assert any("isn't in the career graph" in note for note in result.limitations)
    assert result.clarification is not None
    assert result.clarification.requested_fields == ["interests"]
    # Only clearly labeled broad starting points; nothing claims to serve "Zeta Corp".
    assert all(r.evidence_path[0] == "Broad starting point" for r in result.recommendations)
    assert "Zeta" not in " ".join(r for rec in result.recommendations for r in rec.why_relevant)


async def test_beginner_with_interest_gets_grounded_actions_without_job_title() -> None:
    result = await run(make_request(interests=["robots"]))
    assert result.recommendations
    assert all(r.evidence_path[0] == "Interest: robots" for r in result.recommendations)
    # One direction, so no direction question; the only question is the one that changes
    # which course fits (Python is an unconfirmed prerequisite of Robot Control).
    assert result.clarification is not None
    assert result.clarification.requested_fields == ["skills.python"]


async def test_interest_with_several_directions_offers_choice_and_results() -> None:
    result = await run(make_request(interests=["self-driving cars"]))
    assert result.clarification is not None
    assert result.clarification.text.startswith("Your interests connect to a few directions")
    assert offers_not_sure(result)
    assert result.recommendations


async def test_no_context_asks_once_and_still_offers_broad_starting_points() -> None:
    result = await run(make_request())
    assert result.clarification is not None
    assert "No job title needed" in result.clarification.text
    assert result.clarification.requested_fields == ["interests"]
    # Answering "I'm not sure" must not gate results: broad options come with the question.
    assert result.recommendations
    for rec in result.recommendations:
        assert rec.evidence_path[0] == "Broad starting point"
        assert "isn't matched to your background yet" in rec.why_relevant[0]
    assert any("general starting points" in note for note in result.limitations)


async def test_broad_starting_points_skip_courses_with_prerequisites() -> None:
    result = await run(make_request(limit=10))
    courses = [r for r in result.recommendations if r.kind == "course"]
    assert [c.id for c in courses] == ["course-syn101"]


# --- Preparation ---------------------------------------------------------------------------


async def test_unmentioned_skill_is_unknown_not_missing() -> None:
    result = await run(make_request(target=target("role", "Software Engineer")))
    joined = text(result).casefold()
    assert "not a confirmed gap" in joined
    assert "missing" not in joined
    # Python is core, unmentioned, and an unconfirmed prerequisite of SYN 201: worth asking.
    assert result.clarification is not None
    assert result.clarification.requested_fields == ["skills.python"]
    assert offers_not_sure(result)


async def test_completed_course_is_exposure_not_mastery() -> None:
    repo = synthetic_repository()
    ctx = RetrievalContext.model_validate(
        context(target=target("role", "Software Engineer"), completed_courses=["SYN 201"])
    )
    resolution = await DestinationResolver(repo).resolve(ctx)
    completed = await repo.find_courses([c.value for c in ctx.completed_courses])
    prep = await PreparationAnalyzer(repo).analyze(resolution, ctx, completed)
    ds = prep.by_skill()["skill-ds"]
    assert ds.status == "unknown"
    assert ds.exposure == ("SYN 201",)


async def test_exposure_is_explained() -> None:
    result = await run(
        make_request(
            target=target("role", "Software Engineer"),
            skills=[skill("Python", "learning")],
            completed_courses=["SYN 101"],
        )
    )
    reasons = " ".join(by_id(result, "course-syn201").why_relevant)
    assert "exposure through SYN 101" in reasons
    assert "not mastery" in reasons


async def test_team_and_role_scopes_stay_distinct() -> None:
    result = await run(
        make_request(
            target=target("team", "Perception", "Nimbus Robotics"),
            skills=[skill("Python", "known")],
            limit=10,
        )
    )
    reasons = " ".join(r for rec in result.recommendations for r in rec.why_relevant)
    assert "Perception team at Nimbus Robotics (team-specific) lists Computer vision" in reasons
    assert "Machine Learning Engineer (role baseline) lists Machine learning" in reasons


async def test_team_without_team_records_says_so() -> None:
    result = await run(make_request(target=target("team", "Platform", "Nimbus Robotics")))
    assert any("No team-specific requirements are recorded" in n for n in result.limitations)


async def test_known_skill_alias_is_respected() -> None:
    result = await run(
        make_request(target=target("role", "SWE"), skills=[skill("python programming", "known")])
    )
    assert "course-syn101" not in ids(result)


# --- Feasibility ---------------------------------------------------------------------------


async def test_unknown_prerequisite_is_labeled_not_assumed() -> None:
    result = await run(make_request(target=target("team", "Platform", "Orbit Cloud"), limit=10))
    dist = by_id(result, "course-syn450")
    assert any(u.startswith("Prerequisite not confirmed: SYN 201") for u in dist.unknowns)


async def test_restrictions_and_open_term_are_reported() -> None:
    result = await run(
        make_request(
            target=target("role", "ML engineer"),
            skills=[skill("Python", "known")],
            completed_courses=["SYN 201"],
        )
    )
    ml = by_id(result, "course-syn367")
    assert "Restriction listed: Open to engineering majors." in ml.prerequisites_or_access
    assert any("D-clearance" in u for u in ml.unknowns)
    assert ml.course.term == "Spring 2027 (enrollment open)"


async def test_unknown_offering_is_not_called_enrollable() -> None:
    result = await run(
        make_request(target=target("role", "Robotics Engineer"), skills=[skill("Python", "known")])
    )
    control = by_id(result, "course-syn445")
    assert control.course.term is None
    assert any("Schedule of Classes" in u for u in control.unknowns)


async def test_course_without_upcoming_offering_is_excluded() -> None:
    result = await run(
        make_request(target=target("role", "SWE"), skills=[skill("Python", "known")], limit=10)
    )
    assert "course-syn310" not in ids(result)
    assert "Skipped SYN 310: Databases: no upcoming offering is listed." in result.limitations


async def test_expired_events_never_appear() -> None:
    for kind_target in (target("role", "SWE"), target("role", "Robotics Engineer")):
        result = await run(make_request(target=kind_target, limit=10))
        assert "event-past-hack" not in ids(result)


async def test_clock_controls_event_window() -> None:
    request = make_request(target=target("role", "Robotics Engineer"), limit=10)
    before = await run(request)
    after = await run(request, make_engine(now=datetime(2026, 11, 21, tzinfo=PACIFIC)))
    assert "event-build-night" in ids(before)
    assert "event-build-night" not in ids(after)


def test_naive_datetimes_are_rejected() -> None:
    with pytest.raises(ValueError):
        FixedClock(datetime(2026, 11, 14))
    with pytest.raises(ValueError):
        EventInfo(start=datetime(2026, 11, 20))


# --- Ranking and explanation ---------------------------------------------------------------


async def test_default_limit_and_no_percentages() -> None:
    result = await run(make_request(target=target("role", "Robotics Engineer")))
    assert len(result.recommendations) <= 3
    assert "%" not in text(result)


async def test_requested_kind_is_preferred_without_hiding_evidence() -> None:
    result = await run(
        make_request("Any events coming up?", target=target("role", "Robotics Engineer"))
    )
    assert result.recommendations[0].kind == "event"


async def test_every_recommendation_is_evidence_backed() -> None:
    profiles: list[dict[str, Any]] = [
        {"target": target("role", "SWE")},
        {"target": target("team", "Perception", "Nimbus Robotics")},
        {"target": target("company", "Nimbus")},
        {"interests": ["self-driving"]},
        {"interests": ["robots"], "skills": [skill("Python", "not_yet_learned")]},
    ]
    for profile in profiles:
        result = await run(make_request(limit=10, **profile))
        assert result.recommendations
        for rec in result.recommendations:
            assert rec.why_relevant and rec.benefits and rec.sources
            assert len(rec.evidence_path) >= 2
            assert rec.action_url is not None


async def test_event_wording_never_claims_proficiency_or_jobs() -> None:
    result = await run(
        make_request(
            target=target("role", "ML engineer"), skills=[skill("Python", "known")], limit=10
        )
    )
    panel = by_id(result, "event-ml-panel")
    assert any("doesn't by itself show proficiency" in b for b in panel.benefits)
    assert any("doesn't guarantee a job or team" in b for b in panel.benefits)


# --- Demo acceptance: context and graph changes ---------------------------------------------


async def test_correcting_a_skill_changes_results() -> None:
    gap = await run(
        make_request(target=target("role", "SWE"), skills=[skill("Python", "not_yet_learned")])
    )
    known = await run(make_request(target=target("role", "SWE"), skills=[skill("Python", "known")]))
    assert "course-syn101" in ids(gap)
    assert "course-syn101" not in ids(known)
    assert ids(gap) != ids(known)


async def test_changing_goal_changes_results() -> None:
    swe = await run(make_request(target=target("role", "SWE")))
    robotics = await run(make_request(target=target("role", "Robotics Engineer")))
    assert ids(swe) != ids(robotics)
    assert any(
        "Robotics Engineer (role baseline)" in r.evidence_path for r in robotics.recommendations
    )


async def test_cancelled_event_drops_out_with_explanation() -> None:
    request = make_request(target=target("role", "Robotics Engineer"), limit=10)
    repo = synthetic_repository()
    before = await run(request, make_engine(repo))
    original = next(a for a in ACTIONS if a.id == "event-build-night")
    assert original.event is not None
    cancelled = original.model_copy(
        update={"event": original.event.model_copy(update={"status": "cancelled"})}
    )
    after = await run(request, make_engine(repo.with_action(cancelled)))
    assert "event-build-night" in ids(before)
    assert "event-build-night" not in ids(after)
    assert "Skipped Robotics Build Night: the organizer cancelled it." in after.limitations


async def test_unmet_prerequisite_redirects_to_bridge_course() -> None:
    result = await run(
        make_request(
            target=target("role", "ML engineer"), skills=[skill("Python", "not_yet_learned")]
        )
    )
    assert "course-syn367" not in ids(result)
    assert any(
        n.startswith("Skipped SYN 367: Machine Learning: it requires Python")
        for n in result.limitations
    )
    intro = by_id(result, "course-syn101")
    assert any(
        r.startswith("Builds Python, which SYN 367: Machine Learning") for r in intro.why_relevant
    )
    assert intro.evidence_path[:4] == [
        "Machine Learning Engineer (role baseline)",
        "requires Machine learning",
        "needs SYN 367: Machine Learning",
        "which requires Python",
    ]


# --- Request isolation ---------------------------------------------------------------------


async def test_requests_are_isolated_and_engine_is_stateless() -> None:
    engine = make_engine()
    state_before = dict(vars(engine))
    a = make_request(target=target("role", "SWE"), skills=[skill("Python", "not_yet_learned")])
    b = make_request(target=target("role", "Robotics Engineer"), skills=[skill("Python", "known")])

    solo_a, solo_b = await engine.recommend(a), await engine.recommend(b)
    together = await asyncio.gather(*(engine.recommend(r) for r in (a, b, a, b)))

    assert [ids(r) for r in together] == [ids(solo_a), ids(solo_b)] * 2
    assert together[0] == solo_a and together[1] == solo_b
    assert vars(engine) == state_before, "no per-request state may be stored on the engine"


async def test_no_student_data_is_logged(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    await run(make_request(target=target("role", "SWE"), interests=["secret-interest"]))
    assert "secret-interest" not in caplog.text


async def test_team_specific_requirement_ranks_first_for_team_target() -> None:
    result = await run(
        make_request(
            target=target("team", "Perception", "Nimbus Robotics"),
            skills=[skill("Python", "learning")],
        )
    )
    assert (
        "Perception team at Nimbus Robotics (team-specific)"
        in result.recommendations[0].evidence_path
    )
