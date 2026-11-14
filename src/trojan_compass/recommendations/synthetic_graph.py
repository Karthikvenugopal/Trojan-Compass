"""Synthetic graph fixture for tests and local demos until the real KG adapter lands.

Everything here is invented for integration testing: "SYN" course codes, fictional
companies and example.org URLs. None of it is a real USC offering or a real employer
requirement, so it must not be presented to students as such.
"""

from datetime import UTC, datetime, timedelta, timezone

from trojan_compass.contracts import Source

from .fake_repository import InMemoryGraphRepository, InterestLink, build_repository
from .graph import (
    CampusAction,
    CourseInfo,
    Destination,
    Prerequisite,
    Requirement,
    SkillLink,
    SkillNode,
    TermOffering,
)

PACIFIC = timezone(timedelta(hours=-8))
VERIFIED = datetime(2026, 11, 1, tzinfo=UTC)
STALE = datetime(2025, 6, 1, tzinfo=UTC)


def _src(path: str, title: str) -> Source:
    return Source(url=f"https://example.org/{path}", title=title, checked_at=VERIFIED)


PYTHON = SkillNode(id="skill-python", name="Python", aliases=["python programming"])
DATA_STRUCTURES = SkillNode(id="skill-ds", name="Data structures", aliases=["DSA", "algorithms"])
ML = SkillNode(id="skill-ml", name="Machine learning", aliases=["ML"])
CV = SkillNode(id="skill-cv", name="Computer vision", aliases=["CV"])
CONTROL = SkillNode(id="skill-control", name="Robot control")
DISTRIBUTED = SkillNode(id="skill-distributed", name="Distributed systems")
SQL = SkillNode(id="skill-sql", name="SQL", aliases=["databases"])

SWE = Destination(
    id="role-swe",
    kind="role",
    name="Software Engineer",
    aliases=["SWE", "software developer"],
    sources=[_src("roles/swe", "Synthetic SWE role profile")],
)
MLE = Destination(
    id="role-mle",
    kind="role",
    name="Machine Learning Engineer",
    aliases=["ML engineer", "MLE"],
    sources=[_src("roles/mle", "Synthetic MLE role profile")],
)
ROBOTICS = Destination(
    id="role-robotics",
    kind="role",
    name="Robotics Engineer",
    sources=[_src("roles/robotics", "Synthetic robotics role profile")],
)
NIMBUS = Destination(
    id="company-nimbus",
    kind="company",
    name="Nimbus Robotics",
    aliases=["Nimbus"],
    related_role_ids=["role-robotics", "role-mle"],
    sources=[_src("companies/nimbus", "Synthetic Nimbus careers page")],
)
ORBIT = Destination(
    id="company-orbit",
    kind="company",
    name="Orbit Cloud",
    related_role_ids=["role-swe"],
    sources=[_src("companies/orbit", "Synthetic Orbit careers page")],
)
NIMBUS_PERCEPTION = Destination(
    id="team-nimbus-perception",
    kind="team",
    name="Perception",
    company="Nimbus Robotics",
    base_role_id="role-mle",
    sources=[_src("teams/nimbus-perception", "Synthetic team page")],
)
NIMBUS_PLATFORM = Destination(
    id="team-nimbus-platform",
    kind="team",
    name="Platform",
    company="Nimbus Robotics",
    base_role_id="role-swe",
)
ORBIT_PLATFORM = Destination(
    id="team-orbit-platform",
    kind="team",
    name="Platform",
    company="Orbit Cloud",
    base_role_id="role-swe",
    sources=[_src("teams/orbit-platform", "Synthetic team page")],
)


def _req(skill: SkillNode, scope: Destination, importance: str, path: str) -> Requirement:
    return Requirement.model_validate(
        {
            "skill": skill,
            "scope_id": scope.id,
            "importance": importance,
            "statement": f"{scope.label} lists {skill.name} ({importance}).",
            "sources": [_src(path, f"Synthetic requirement evidence: {scope.label}")],
        }
    )


REQUIREMENTS = [
    _req(PYTHON, SWE, "core", "roles/swe#python"),
    _req(DATA_STRUCTURES, SWE, "core", "roles/swe#ds"),
    _req(SQL, SWE, "preferred", "roles/swe#sql"),
    _req(PYTHON, MLE, "core", "roles/mle#python"),
    _req(ML, MLE, "core", "roles/mle#ml"),
    _req(DATA_STRUCTURES, MLE, "preferred", "roles/mle#ds"),
    _req(PYTHON, ROBOTICS, "core", "roles/robotics#python"),
    _req(CONTROL, ROBOTICS, "core", "roles/robotics#control"),
    _req(CV, ROBOTICS, "preferred", "roles/robotics#cv"),
    _req(CV, NIMBUS_PERCEPTION, "core", "teams/nimbus-perception#cv"),
    _req(DISTRIBUTED, ORBIT_PLATFORM, "core", "teams/orbit-platform#distributed"),
    # No team-specific records for NIMBUS_PLATFORM on purpose: the engine must say so.
]


def _course(
    id: str,
    code: str,
    title: str,
    summary: str,
    links: list[SkillLink],
    prerequisites: list[Prerequisite] | None = None,
    terms: list[TermOffering] | None = None,
    restrictions: list[str] | None = None,
    modality: str | None = "In person",
    verified: datetime = VERIFIED,
    topics: list[str] | None = None,
) -> CampusAction:
    return CampusAction(
        id=id,
        kind="course",
        title=title,
        summary=summary,
        skills=links,
        topics=topics or [],
        url=f"https://example.org/courses/{id}",
        sources=[_src(f"catalog/{id}", f"Synthetic catalog: {code}")],
        last_verified=verified,
        course=CourseInfo(
            code=code,
            prerequisites=prerequisites or [],
            restrictions=restrictions or [],
            offered_terms=terms,
            modality=modality,
        ),
    )


def _event(
    id: str,
    title: str,
    summary: str,
    links: list[SkillLink],
    start: datetime,
    status: str = "scheduled",
    eligibility: list[str] | None = None,
    topics: list[str] | None = None,
) -> CampusAction:
    return CampusAction.model_validate(
        {
            "id": id,
            "kind": "event",
            "title": title,
            "summary": summary,
            "skills": links,
            "topics": topics or [],
            "url": f"https://example.org/events/{id}",
            "sources": [_src(f"events/{id}", f"Synthetic event listing: {title}")],
            "last_verified": VERIFIED,
            "event": {
                "start": start,
                "end": start + timedelta(hours=2),
                "timezone": "America/Los_Angeles",
                "status": status,
                "eligibility": eligibility,
                "registration_required": True,
                "registration_url": f"https://example.org/events/{id}/register",
            },
        }
    )


ACTIONS = [
    _course(
        "course-syn101",
        "SYN 101",
        "Introduction to Programming in Python",
        "Synthetic intro course: programming fundamentals in Python.",
        [SkillLink(skill=PYTHON, relation="teaches", level="intro")],
        terms=[TermOffering(term="Spring 2027", status="open")],
        topics=["programming"],
    ),
    _course(
        "course-syn201",
        "SYN 201",
        "Data Structures",
        "Synthetic course: lists, trees, graphs and complexity.",
        [
            SkillLink(skill=DATA_STRUCTURES, relation="teaches", level="intermediate"),
            SkillLink(skill=PYTHON, relation="teaches", level="intermediate"),
        ],
        prerequisites=[Prerequisite(description="Python programming", skill=PYTHON)],
        terms=[TermOffering(term="Spring 2027", status="scheduled")],
    ),
    _course(
        "course-syn367",
        "SYN 367",
        "Machine Learning",
        "Synthetic course: supervised learning, evaluation and model building.",
        [SkillLink(skill=ML, relation="teaches", level="intermediate")],
        prerequisites=[
            Prerequisite(description="Python programming", skill=PYTHON),
            Prerequisite(description="SYN 201 or equivalent", course_code="SYN 201"),
        ],
        terms=[TermOffering(term="Spring 2027", status="open")],
        restrictions=["Open to engineering majors"],
        topics=["artificial intelligence"],
    ),
    _course(
        "course-syn467",
        "SYN 467",
        "Computer Vision",
        "Synthetic course: image processing, detection and 3D perception.",
        [SkillLink(skill=CV, relation="teaches", level="advanced")],
        prerequisites=[Prerequisite(description="SYN 367 or equivalent", course_code="SYN 367")],
        terms=[TermOffering(term="Spring 2027", status="scheduled")],
    ),
    _course(
        "course-syn445",
        "SYN 445",
        "Robot Control",
        "Synthetic course: kinematics, feedback control and motion planning.",
        [SkillLink(skill=CONTROL, relation="teaches", level="intermediate")],
        prerequisites=[Prerequisite(description="Python programming", skill=PYTHON)],
        terms=None,
        topics=["robotics"],
    ),
    _course(
        "course-syn450",
        "SYN 450",
        "Distributed Systems",
        "Synthetic course: replication, consensus and large-scale services.",
        [SkillLink(skill=DISTRIBUTED, relation="teaches", level="advanced")],
        prerequisites=[Prerequisite(description="SYN 201", course_code="SYN 201")],
        terms=[TermOffering(term="Fall 2027", status="scheduled")],
    ),
    _course(
        "course-syn310",
        "SYN 310",
        "Databases",
        "Synthetic course: relational modeling and SQL.",
        [SkillLink(skill=SQL, relation="teaches", level="intermediate")],
        terms=[],
        verified=STALE,
    ),
    _event(
        "event-build-night",
        "Robotics Build Night",
        "Synthetic event: build and program small robots with student mentors.",
        [
            SkillLink(skill=CONTROL, relation="practices"),
            SkillLink(skill=PYTHON, relation="practices"),
        ],
        datetime(2026, 11, 20, 18, 0, tzinfo=PACIFIC),
        eligibility=["All enrolled students"],
        topics=["robotics"],
    ),
    _event(
        "event-ml-panel",
        "ML Industry Panel",
        "Synthetic event: practitioners discuss ML careers; open Q&A.",
        [SkillLink(skill=ML, relation="exposes"), SkillLink(skill=ML, relation="networking")],
        datetime(2026, 12, 2, 17, 0, tzinfo=PACIFIC),
        topics=["artificial intelligence"],
    ),
    _event(
        "event-cv-workshop",
        "Computer Vision Workshop",
        "Synthetic event: hands-on image classification with a pretrained model.",
        [SkillLink(skill=CV, relation="practices")],
        datetime(2026, 12, 5, 13, 0, tzinfo=PACIFIC),
        eligibility=["All enrolled students"],
    ),
    _event(
        "event-past-hack",
        "Fall Hack Night",
        "Synthetic event that already happened.",
        [SkillLink(skill=PYTHON, relation="practices")],
        datetime(2026, 10, 1, 18, 0, tzinfo=PACIFIC),
    ),
]

INTEREST_LINKS = [
    InterestLink(
        "robotics",
        "role-robotics",
        ("robots",),
        (_src("topics/robotics", "Synthetic topic map: robotics"),),
    ),
    InterestLink(
        "artificial intelligence",
        "role-mle",
        ("ai", "machine learning"),
        (_src("topics/ai", "Synthetic topic map: AI"),),
    ),
    InterestLink("self-driving", "role-robotics", ("autonomous",)),
    InterestLink("self-driving", "role-mle", ("autonomous",)),
    InterestLink("apps", "role-swe", ("web", "software")),
]


def synthetic_repository() -> InMemoryGraphRepository:
    return build_repository(
        [SWE, MLE, ROBOTICS, NIMBUS, ORBIT, NIMBUS_PERCEPTION, NIMBUS_PLATFORM, ORBIT_PLATFORM],
        REQUIREMENTS,
        ACTIONS,
        INTEREST_LINKS,
    )
