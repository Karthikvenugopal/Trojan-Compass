"""V2 shared contracts. RetrievalContext is temporary, never a stored profile."""

from datetime import datetime
from typing import Annotated, Literal, Protocol, Self

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator

Text = Annotated[str, Field(min_length=1, max_length=4000, strict=True)]
SkillStatus = Literal["known", "learning", "not_yet_learned", "unknown"]
MAX_BODY_BYTES = 65536
InformationKey = Annotated[
    str,
    Field(
        max_length=120,
        pattern=(
            r"^(direction|direction_detail|background|study_stage|work_experience|completed_courses|program|preferences|time_window|"
            r"modality|target|skills\..{1,100})$"
        ),
    ),
]
AnswerStatus = Literal["not_answered", "unknown", "none", "provided"]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class InformationEdit(Contract):
    """An explicit student correction carried in a user turn, never stored server-side."""

    field: InformationKey
    status: AnswerStatus
    value: Annotated[str, Field(min_length=1, max_length=1000)] | None = None

    @field_validator("field")
    @classmethod
    def canonical_field(cls, value: str) -> str:
        return value.casefold()

    @model_validator(mode="after")
    def consistent(self) -> Self:
        if (self.status == "provided") != (self.value is not None):
            raise ValueError("Only a provided answer has a text value")
        return self


class ShownResource(Contract):
    """Ordered assistant display context, never evidence about the student."""

    id: Text
    title: Text
    kind: Literal["course", "event", "faculty", "research"]
    section: Literal["plan", "recommendations"]


class ChatMessage(Contract):
    role: Literal["user", "assistant"]
    content: Annotated[str, Field(min_length=1, max_length=20400, strict=True)]
    edit: InformationEdit | None = None
    asked_field: InformationKey | None = None
    shown_resources: list[ShownResource] = Field(default_factory=list, max_length=24)

    @model_validator(mode="after")
    def student_edit(self) -> Self:
        if self.role == "user" and self.shown_resources:
            raise ValueError("Shown resources belong only to assistant turns")
        if self.role == "user" and self.asked_field is not None:
            raise ValueError("Only assistant questions can declare their asked field")
        # Full background is kept in the active conversation, never a backend file/session.
        imported = self.role == "user" and self.content.startswith(
            ("Use my resume as background.\n", "Use my LinkedIn profile as background.\n")
        )
        if len(self.content) > 4000 and not imported:
            raise ValueError("Ordinary messages are limited to 4000 characters")
        if self.role != "user" and self.edit is not None:
            raise ValueError("Only student messages can carry information edits")
        if self.edit is not None and self.edit.value is not None:
            if self.edit.value not in self.content:
                raise ValueError("The correction sentence must be present in the student message")
        return self


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


class StudentAnswer(InformationEdit):
    evidence: list[StudentStatement] = Field(default_factory=list, max_length=8)

    @model_validator(mode="after")
    def supported(self) -> Self:
        if self.status != "not_answered" and not self.evidence:
            raise ValueError("An answered field requires student evidence")
        return self


class ContextRequirement(Contract):
    """Additional information explicitly made material by the student's request."""

    field: Literal["direction_detail", "background", "time_window", "modality"]
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


AcademicLevel = Literal["undergraduate", "graduate", "doctoral", "not_started", "unknown"]


class SupportedAcademicLevel(Contract):
    value: AcademicLevel
    evidence: list[StudentStatement] = Field(min_length=1, max_length=8)


class RetrievalContext(Contract):
    interests: list[SupportedText] = Field(default_factory=list)
    skills: list[Skill] = Field(default_factory=list)
    experiences: list[SupportedText] = Field(default_factory=list)
    completed_courses: list[SupportedText] = Field(default_factory=list)
    program: SupportedText | None = None
    study_stage: SupportedText | None = None
    academic_level: SupportedAcademicLevel | None = None
    goals: list[SupportedText] = Field(default_factory=list)
    target: Target | None = None
    constraints: Constraints = Field(default_factory=Constraints)
    answers: list[StudentAnswer] = Field(default_factory=list, max_length=128)
    requested_context: list[ContextRequirement] = Field(default_factory=list, max_length=4)

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
    exploration_options: list[Text] = Field(default_factory=list, max_length=5)


class RecommendationService(Protocol):
    async def recommend(self, request: RecommendationRequest) -> RecommendationResult:
        """Retrieve grounded evidence without persisting or logging student context."""
        ...


class ContextExtractor(Protocol):
    async def extract(self, messages: list[ChatMessage]) -> RetrievalContext:
        """Re-derive supported facts from this request only; retain no messages/context."""
        ...


class CourseHistoryOption(Contract):
    """A sourced course to ask about, never an assertion the student completed it."""

    code: Text
    title: Text
    sources: list[Source] = Field(min_length=1)


class CourseHistoryService(Protocol):
    async def suggest(
        self, context: RetrievalContext, limit: int = 5
    ) -> list[CourseHistoryOption]: ...


class InformationField(InformationEdit):
    label: Text
    category: Literal["fixed", "request"]
    required: bool = False


class InformationSnapshot(Contract):
    """A response view for frontend memory, not a persistent student profile."""

    fields: list[InformationField] = Field(default_factory=list)
    ready: bool = False
    missing_fields: list[InformationKey] = Field(default_factory=list)


class CareerOption(Contract):
    id: Text
    title: Text
    why_consider: Text
    select_message: Text
    sources: list[Source] = Field(min_length=1)


class CareerSkill(Contract):
    name: Text
    status: SkillStatus = "unknown"
    category: Literal["skill", "knowledge"] = "skill"
    basis: Text
    student_evidence: list[StudentStatement] = Field(default_factory=list)
    sources: list[Source] = Field(min_length=1)


class GuidanceAction(Contract):
    id: Text
    kind: Literal["course", "event", "faculty", "research"]
    title: Text
    summary: Text
    why_relevant: Text
    skill_names: list[Text] = Field(default_factory=list)
    url: HttpUrl
    sources: list[Source] = Field(min_length=1)
    availability: Literal["unknown", "snapshot"] = "unknown"
    checks: list[Text] = Field(default_factory=list)
    term: Text | None = None


class PlanStep(Contract):
    id: Text
    title: Text
    description: Text
    skill_names: list[Text] = Field(default_factory=list)
    action_ids: list[Text] = Field(default_factory=list)
    depends_on: list[Text] = Field(default_factory=list)


class CareerGuidance(Contract):
    mode: Literal["explore", "plan", "coverage_gap"]
    goal: Text | None = None
    headline: Text
    suggested_paths: list[CareerOption] = Field(default_factory=list, max_length=3)
    skills: list[CareerSkill] = Field(default_factory=list, max_length=12)
    actions: list[GuidanceAction] = Field(default_factory=list, max_length=12)
    steps: list[PlanStep] = Field(default_factory=list, max_length=5)
    next_question: Clarification | None = None
    limitations: list[Text] = Field(default_factory=list)


class CareerGuidanceService(Protocol):
    async def guide(
        self, context: RetrievalContext, recommendations: list[Recommendation]
    ) -> CareerGuidance: ...


class ChatResponse(Contract):
    asked_field: InformationKey | None = None
    guidance: CareerGuidance | None = None
    message: Text
    suggested_replies: list[Text] = Field(default_factory=list)
    recommendations: list[Recommendation] = Field(default_factory=list)
    limitations: list[Text] = Field(default_factory=list)
    information: InformationSnapshot = Field(default_factory=InformationSnapshot)
    course_history_options: list[CourseHistoryOption] = Field(default_factory=list, max_length=8)
    # Official pages a direct campus/course answer relied on (empty for card replies).
    sources: list[Source] = Field(default_factory=list, max_length=5)
