"""Dependency-injected orchestration; services retain dependencies, never student state."""

import asyncio

from trojan_compass.contracts import (
    ChatMessage,
    ChatRequest,
    ChatResponse,
    Clarification,
    ContextExtractor,
    CourseDetails,
    Recommendation,
    RecommendationRequest,
    RecommendationResult,
    RecommendationService,
    RetrievalContext,
    Source,
)
from trojan_compass.extraction import validate_evidence
from trojan_compass.readiness import CHECKLIST_HINT, request_information


class ChatUnavailable(Exception):
    """Sanitized failure without sensitive exception details."""


class AskBackPolicy:
    """Defer discovery to graph retrieval; filter questions already answered by context."""

    def field(self, question: Clarification) -> str | None:
        field = question.requested_fields[0]
        field = "direction" if field == "interests" else field.removeprefix("constraints.")
        if field in (
            "direction",
            "direction_detail",
            "background",
            "target",
            "time_window",
            "modality",
        ):
            return field
        if field.startswith("skills.") and 0 < len(field[7:]) <= 100:
            return field
        return None

    def choose(
        self,
        question: Clarification | None,
        context: RetrievalContext,
        messages: list[ChatMessage],
    ) -> Clarification | None:
        if question is None:
            return None
        field = self.field(question)
        if field is None:
            return None
        information = request_information(context, messages)
        # Merely asking before is not evidence of an answer. Explicit unknown/none
        # resolves the question without claiming that the student has a skill.
        return question if information.answer(field).status == "not_answered" else None


class ChatService:
    def __init__(
        self,
        extractor: ContextExtractor,
        recommendations: RecommendationService,
        policy: AskBackPolicy | None = None,
    ) -> None:
        self._extractor = extractor
        self._recommendations = recommendations
        self._policy = policy or AskBackPolicy()

    async def chat(self, request: ChatRequest) -> ChatResponse:
        try:
            # One bounded lifecycle; no retries that silently replay private content.
            async with asyncio.timeout(40):
                context = RetrievalContext.model_validate(
                    (await self._extractor.extract(request.messages)).model_dump(),
                )
                validate_evidence(context, request.messages)
                information = request_information(context, request.messages)
                context = information.context
                opening_question = information.missing_question()
                if opening_question is not None:
                    first_question = opening_question.requested_fields == ["direction"] and not any(
                        m.role == "assistant" for m in request.messages
                    )
                    return ChatResponse(
                        message=(
                            f"{opening_question.text}\n\n{CHECKLIST_HINT}"
                            if first_question
                            else opening_question.text
                        ),
                        suggested_replies=opening_question.options,
                        information=information.snapshot(),
                    )
                retrieval_request = RecommendationRequest(
                    context=context,
                    user_query=request.messages[-1].content,
                )
                result = RecommendationResult.model_validate(
                    (await self._recommendations.recommend(retrieval_request)).model_dump(),
                )
                if result.clarification is not None:
                    required_field = self._policy.field(result.clarification)
                    if required_field is not None:
                        information.require(required_field)
                question = self._policy.choose(result.clarification, context, request.messages)
                if question is not None:
                    options = list(question.options)
                    if not any(
                        "know" in option.casefold() or "sure" in option.casefold()
                        for option in options
                    ):
                        options = options[:5] + ["I don't know"]
                    return ChatResponse(
                        message=question.text,
                        suggested_replies=options,
                        information=information.snapshot(),
                    )
                recommendations = result.recommendations[: retrieval_request.limit]
                if not recommendations:
                    return ChatResponse(
                        message=(
                            "Your search details are collected. I don't have a verified "
                            "USC match for them in my current data. "
                            + (
                                "I can check these areas if you'd like to switch:"
                                if result.exploration_options
                                else "You can try a different interest or check again "
                                "when more data is available."
                            )
                        ),
                        suggested_replies=result.exploration_options,
                        information=information.snapshot(),
                    )
                limitations = list(result.limitations)
                if context.constraints.time_window is not None:
                    limitations.append(
                        "Your timing preference is recorded, but automatic schedule matching "
                        "is not supported yet. Confirm dates and availability using the sources."
                    )
                if context.constraints.modality is not None and any(
                    recommendation.kind == "event" for recommendation in recommendations
                ):
                    limitations.append(
                        "Event format preferences are recorded but not automatically checked. "
                        "Confirm each event's format with the organizer."
                    )
                unavailable = [
                    field.label
                    for field in information.snapshot().fields
                    if field.status == "unknown" and field.required
                ]
                if unavailable:
                    limitations.append(
                        "You indicated no usable information for: "
                        + ", ".join(unavailable)
                        + ". Suggestions cannot be matched to those details."
                    )
                if recommendations:
                    if information.answer("direction").status in (
                        "unknown",
                        "none",
                    ) or information.answer("direction_detail").status in ("unknown", "none"):
                        message = (
                            "You haven't chosen a specific direction yet. These are general campus "
                            "starting points, not personalized matches."
                        )
                    else:
                        message = "Here are campus options with supporting sources below."
                # Composition is deterministic: retrieved text is never executed or reprompted.
                return ChatResponse(
                    message=message,
                    suggested_replies=[],
                    recommendations=recommendations,
                    limitations=limitations,
                    information=information.snapshot(),
                )
        except Exception:
            raise ChatUnavailable() from None


class DemoRecommendationService:
    """Fixed, sourced campus example; no live extraction, ranking or graph access."""

    async def recommend(self, request: RecommendationRequest) -> RecommendationResult:
        limitations = [
            "Demo mode: no live LLM extraction or USC knowledge graph is connected. "
            "This fixed example is not a personalized recommendation. "
            "Current enrollment and eligibility are unverified.",
        ]
        query = request.user_query.casefold()
        general = any(
            answer.field == "direction" and answer.status in ("unknown", "none")
            for answer in request.context.answers
        )
        programming = any(i.value.casefold() == "programming" for i in request.context.interests)
        if (
            general
            or programming
            or any(word in query for word in ("program", "course", "sure", "starting point"))
        ):
            return RecommendationResult(
                recommendations=[
                    Recommendation(
                        id="demo-csci102",
                        kind="course",
                        title="Demo: CSCI 102 — Fundamentals of Computation",
                        summary="USC introductory programming course, shown as a demo example.",
                        why_relevant=[
                            "A general programming starting point; individual fit is unverified."
                        ],
                        benefits=["Explore introductory programming."],
                        prerequisites_or_access=["Check current access requirements with USC."],
                        unknowns=[
                            "Current enrollment, eligibility, future terms and individual fit."
                        ],
                        action_url="https://bytes.usc.edu/cs102/",
                        sources=[
                            Source(
                                url="https://bytes.usc.edu/cs102/",
                                title="USC CSCI 102 course page (fixture checked 2026-11-14)",
                            )
                        ],
                        evidence_path=[
                            "demo fixture, not KG traversal",
                            "USC course page",
                            "CSCI 102",
                        ],
                        course=CourseDetails(term="Fall 2026 course page"),
                        status="demo_fixture",
                    )
                ],
                limitations=limitations,
            )
        if "event" in query:
            return RecommendationResult(
                limitations=limitations
                + [
                    "No current events are included in the demo fixture.",
                ]
            )
        return RecommendationResult(
            clarification=Clarification(
                text="Would you like to explore a programming course or campus events?",
                options=["Try a programming course", "Explore campus events", "I’m not sure"],
                requested_fields=["interests"],
                reason="Choose a demo resource to explore.",
            ),
            limitations=limitations,
        )
