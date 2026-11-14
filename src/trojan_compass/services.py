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


class ChatUnavailable(Exception):
    """Sanitized failure without sensitive exception details."""


class AskBackPolicy:
    """Defer discovery to graph retrieval; filter questions already answered by context."""

    def choose(
        self,
        question: Clarification | None,
        context: RetrievalContext,
        messages: list[ChatMessage],
    ) -> Clarification | None:
        if question is None:
            return None
        # A prior identical question has already had its chance, including "not sure".
        if any(m.role == "assistant" and question.text in m.content for m in messages):
            return None
        path = question.requested_fields[0].split(".")
        if path[0] == "skills" and len(path) == 2:
            answered = context.skill_status(path[1]) != "unknown"
        elif path[0] == "constraints" and len(path) == 2:
            answered = path[1] in type(context.constraints).model_fields and bool(
                getattr(context.constraints, path[1]),
            )
        elif len(path) == 1 and path[0] in type(context).model_fields:
            answered = bool(getattr(context, path[0]))
        else:
            # Do not forward questions requesting arbitrary data or unsupported fields.
            return None
        return None if answered else question


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
                retrieval_request = RecommendationRequest(
                    context=context,
                    user_query=request.messages[-1].content,
                )
                result = RecommendationResult.model_validate(
                    (await self._recommendations.recommend(retrieval_request)).model_dump(),
                )
                question = self._policy.choose(result.clarification, context, request.messages)
                recommendations = result.recommendations[: retrieval_request.limit]
                limitations = list(result.limitations)
                if result.clarification and question is None:
                    limitations.append(
                        "A redundant or unsupported clarification was omitted; "
                        "some retrieval details may remain uncertain.",
                    )
                if recommendations:
                    message = "Here are campus options with supporting sources below."
                    if question:
                        message += " " + question.text
                elif question:
                    message = question.text
                else:
                    message = (
                        "I couldn’t find supported matches for this request. "
                        "You can try a broader topic or another course or event preference."
                    )
                options = list(question.options) if question else []
                if question and not any("sure" in option.casefold() for option in options):
                    options = options[:5] + ["I’m not sure — show broad starting points"]
                # Composition is deterministic: retrieved text is never executed or reprompted.
                return ChatResponse(
                    message=message,
                    suggested_replies=options,
                    recommendations=recommendations,
                    limitations=limitations,
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
        if any(word in query for word in ("program", "course", "sure", "starting point")):
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
