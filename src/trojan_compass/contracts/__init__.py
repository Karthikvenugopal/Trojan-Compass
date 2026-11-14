"""Version 1 integration boundary shared by conversation, retrieval, and frontend."""

from datetime import datetime
from typing import Annotated, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator

Text = Annotated[str, Field(min_length=1, max_length=4000, strict=True)]
SkillStatus = Literal["known", "learning", "not_yet_learned", "unknown"]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Skill(Contract):
    name: Text
    status: SkillStatus = "unknown"
    supporting_statement: Text


class Target(Contract):
    kind: Literal["company", "role", "team"]
    name: Text
    company_name: Text | None = None


class Constraints(Contract):
    time_window: Text | None = None
    modality: Text | None = None
    additional_preferences: list[Text] = Field(default_factory=list)


class StudentProfile(Contract):
    interests: list[Text] = Field(default_factory=list)
    skills: list[Skill] = Field(default_factory=list)
    experiences: list[Text] = Field(default_factory=list)
    completed_courses: list[Text] = Field(default_factory=list)
    program: Text | None = None
    goals: list[Text] = Field(default_factory=list)
    target: Target | None = None
    constraints: Constraints = Field(default_factory=Constraints)

    def skill_status(self, name: str) -> SkillStatus:
        """Absence is uncertainty, never evidence that a prerequisite is missing."""
        return next((s.status for s in self.skills if s.name.casefold() == name.casefold()), "unknown")


class Clarification(Contract):
    id: Text
    text: Text
    options: list[Text] = Field(default_factory=list)
    requested_fields: list[Text] = Field(default_factory=list)
    reason: Text


class Source(Contract):
    url: HttpUrl
    title: Text
    checked_at: datetime | None = None


class EventSchedule(Contract):
    start: datetime | None = None
    end: datetime | None = None
    timezone: Text | None = None

    @model_validator(mode="after")
    def ordered(self) -> "EventSchedule":
        for value in (self.start, self.end):
            if value is not None and value.utcoffset() is None:
                raise ValueError("Event timestamps require a UTC offset")
        if self.start and self.end and self.end < self.start:
            raise ValueError("Event end must not precede start")
        return self


class CourseDetails(Contract):
    term: Text | None = None
    modality: Text | None = None


class Recommendation(Contract):
    id: Text
    kind: Literal["course", "event"]
    title: Text
    summary: Text
    why_relevant: list[Text] = Field(default_factory=list)
    benefits: list[Text] = Field(default_factory=list)
    prerequisites_or_access: list[Text] = Field(default_factory=list)
    unknowns: list[Text] = Field(default_factory=list)
    action_url: HttpUrl | None = None
    sources: list[Source] = Field(default_factory=list)
    evidence_path: list[Text] = Field(default_factory=list)
    event: EventSchedule | None = None
    course: CourseDetails | None = None


class RecommendationRequest(Contract):
    profile: StudentProfile
    user_query: Text
    limit: int = Field(default=3, ge=1, le=10, strict=True)


class RecommendationResult(Contract):
    recommendations: list[Recommendation] = Field(default_factory=list)
    clarification: Clarification | None = None
    limitations: list[Text] = Field(default_factory=list)


class RecommendationService(Protocol):
    async def recommend(self, request: RecommendationRequest) -> RecommendationResult:
        """Retrieve recommendations and evidence; do not persist student context."""
        ...


class ChatResponse(Contract):
    session_id: str
    message: str
    suggested_replies: list[str] = Field(default_factory=list)
    recommendations: list[Recommendation] = Field(default_factory=list)
    profile_summary: StudentProfile = Field(default_factory=StudentProfile)
    limitations: list[str] = Field(default_factory=list)


class CreateSessionResponse(Contract):
    session_id: str


class MessageRequest(Contract):
    message: Text
