"""V2 shared contracts. RetrievalContext is temporary, never a stored profile."""

from datetime import datetime
from typing import Annotated, Literal, Protocol, Self

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator

Text = Annotated[str, Field(min_length=1, max_length=4000, strict=True)]
SkillStatus = Literal["known", "learning", "not_yet_learned", "unknown"]
MAX_BODY_BYTES = 65536


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ChatMessage(Contract):
    role: Literal["user", "assistant"]
    content: Text


class ChatRequest(Contract):
    messages: list[ChatMessage] = Field(min_length=1, max_length=64)

    @model_validator(mode="after")
    def conversation(self) -> Self:
        if self.messages[0].role != "user" or self.messages[-1].role != "user":
            raise ValueError("Conversation must start and end with a user message")
        if sum(len(m.content) for m in self.messages) > 24000:
            raise ValueError("Conversation exceeds 24000 characters; nothing was truncated")
        return self


class StudentStatement(Contract):
    message_index: int = Field(ge=0, strict=True)
    quote: Text


class SupportedText(Contract):
    value: Text
    evidence: list[StudentStatement] = Field(min_length=1, max_length=8)


class Skill(Contract):
    name: Text
    status: SkillStatus = "unknown"
    evidence: list[StudentStatement] = Field(min_length=1, max_length=8)


class Target(Contract):
    kind: Literal["company", "role", "team"]
    name: Text
    company_name: Text | None = None
    evidence: list[StudentStatement] = Field(min_length=1, max_length=8)


class Constraints(Contract):
    time_window: SupportedText | None = None
    modality: SupportedText | None = None
    additional_preferences: list[SupportedText] = Field(default_factory=list)


class RetrievalContext(Contract):
    interests: list[SupportedText] = Field(default_factory=list)
    skills: list[Skill] = Field(default_factory=list)
    experiences: list[SupportedText] = Field(default_factory=list)
    completed_courses: list[SupportedText] = Field(default_factory=list)
    program: SupportedText | None = None
    goals: list[SupportedText] = Field(default_factory=list)
    target: Target | None = None
    constraints: Constraints = Field(default_factory=Constraints)

    def skill_status(self, name: str) -> SkillStatus:
        return next(
            (s.status for s in self.skills if s.name.casefold() == name.casefold()), "unknown"
        )


class Clarification(Contract):
    text: Text
    options: list[Text] = Field(default_factory=list, max_length=6)
    requested_fields: list[Text] = Field(min_length=1, max_length=1)
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
    def ordered(self) -> Self:
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
    sources: list[Source] = Field(min_length=1)
    evidence_path: list[Text] = Field(min_length=1)
    event: EventSchedule | None = None
    course: CourseDetails | None = None
    modality: Text | None = None
    status: Text | None = None


class RecommendationRequest(Contract):
    context: RetrievalContext
    user_query: Text
    limit: int = Field(default=3, ge=1, le=10, strict=True)


class RecommendationResult(Contract):
    recommendations: list[Recommendation] = Field(default_factory=list)
    clarification: Clarification | None = None
    limitations: list[Text] = Field(default_factory=list)


class RecommendationService(Protocol):
    async def recommend(self, request: RecommendationRequest) -> RecommendationResult:
        """Retrieve grounded evidence without persisting or logging student context."""
        ...


class ContextExtractor(Protocol):
    async def extract(self, messages: list[ChatMessage]) -> RetrievalContext:
        """Re-derive supported facts from this request only; retain no messages/context."""
        ...


class ChatResponse(Contract):
    message: Text
    suggested_replies: list[Text] = Field(default_factory=list)
    recommendations: list[Recommendation] = Field(default_factory=list)
    limitations: list[Text] = Field(default_factory=list)
