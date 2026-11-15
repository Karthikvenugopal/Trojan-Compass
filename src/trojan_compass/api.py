"""HTTP composition and privacy boundary. No sessions, cookies or student repositories."""

import logging
import os
from typing import TYPE_CHECKING, Literal

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException
from starlette.types import ASGIApp, Lifespan, Message, Receive, Scope, Send

from trojan_compass.contracts import (
    MAX_BODY_BYTES,
    CareerGuidanceService,
    ChatRequest,
    ChatResponse,
    ContextExtractor,
    CourseHistoryService,
    RecommendationService,
)
from trojan_compass.controlled_intake import ControlledIntakeParser
from trojan_compass.cors import configured_origins, validate_origins
from trojan_compass.diagnostics import dummy_response
from trojan_compass.documents import (
    MAX_DOCUMENT_BYTES,
    DocumentFailure,
    DocumentKind,
    DocumentText,
    MemoryDocumentParser,
)
from trojan_compass.extraction import DemoContextExtractor, OpenAIContextExtractor
from trojan_compass.failures import FAILURE_MESSAGES, STAGE_LABELS, FailureReason
from trojan_compass.gemini import GeminiContextExtractor
from trojan_compass.linkedin import (
    LinkedInRequest,
    LinkedInText,
    LinkedInUnavailable,
    PublicLinkedInReader,
)
from trojan_compass.services import (
    AskBackPolicy,
    ChatService,
    ChatUnavailable,
    DemoRecommendationService,
)

if TYPE_CHECKING:
    from trojan_compass.ai_chat import AIChatService
    from trojan_compass.assistant import CampusAssistant

AppMode = Literal["demo", "diagnostic", "campus", "production"]


class PrivateBoundary:
    """Bound bytes before parsing, sanitize errors, and forbid HTTP response caching."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        started = False

        async def private_send(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
                headers = list(message.get("headers", []))
                headers.extend([(b"cache-control", b"no-store"), (b"pragma", b"no-cache")])
                message = {**message, "headers": headers}
            await send(message)

        body_limit = (
            MAX_DOCUMENT_BYTES if scope.get("path") == "/api/import-document" else MAX_BODY_BYTES
        )
        chunks: list[bytes] = []
        total = 0
        # Inspect the actual stream, not just spoofable/missing Content-Length.
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            total += len(chunk)
            if total > body_limit:
                response = JSONResponse(
                    status_code=413,
                    content={
                        "error": {
                            "code": "conversation_too_large",
                            "message": f"Request exceeds {body_limit} bytes. "
                            "Nothing was truncated.",
                        }
                    },
                )
                await response(scope, receive, private_send)
                return
            chunks.append(chunk)
            if not message.get("more_body", False):
                break
        body = b"".join(chunks)
        delivered = False

        async def replay() -> Message:
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        try:
            await self.app(scope, replay, private_send)
        except Exception:
            # Prevent server traceback logging, even for unexpected dependency errors.
            if not started:
                response = JSONResponse(
                    status_code=500,
                    content={
                        "error": {
                            "code": "internal_error",
                            "message": "Request could not be handled.",
                        }
                    },
                )
                await response(scope, receive, private_send)


def configure_private_logging() -> None:
    """Disable library HTTP/debug/access logging that could reveal URLs or provider data."""
    for name in ("httpx", "httpcore", "uvicorn.access", "uvicorn.error", "fastapi", "asyncio"):
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.addHandler(logging.NullHandler())
        logger.propagate = False
        logger.disabled = True


def create_app(
    *,
    extractor: ContextExtractor | None = None,
    recommendations: RecommendationService | None = None,
    mode: AppMode = "demo",
    lifespan: Lifespan[FastAPI] | None = None,
    cors_origins: tuple[str, ...] | None = None,
    policy: AskBackPolicy | None = None,
    course_history: CourseHistoryService | None = None,
    assistant: "CampusAssistant | None" = None,
    guidance: CareerGuidanceService | None = None,
    local_intake: ControlledIntakeParser | None = None,
    chat_service: "AIChatService | None" = None,
) -> FastAPI:
    """Inject Abishek→Peri service here; fail closed for missing production dependencies."""
    configure_private_logging()
    if mode not in ("demo", "diagnostic") and (extractor is None or recommendations is None):
        raise ValueError("Production requires an extractor and real RecommendationService")
    service = ChatService(
        extractor or DemoContextExtractor(),
        recommendations or DemoRecommendationService(),
        policy=policy,
        course_history=course_history,
        assistant=assistant,
        guidance=guidance,
        local_intake=local_intake,
    )
    app = FastAPI(title="Trojan Compass", version="0.2.0", debug=False, lifespan=lifespan)
    app.add_middleware(PrivateBoundary)
    # CORS wraps the privacy boundary so even early 413/500 responses get the
    # allowed origin header. Otherwise the browser masks the real safe error.
    origins = configured_origins() if cors_origins is None else validate_origins(cors_origins)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(origins),
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
        max_age=0,
    )

    @app.post("/api/import-document", response_model=DocumentText)
    async def import_document(
        request: Request, format: DocumentKind
    ) -> DocumentText | JSONResponse:
        try:
            return await MemoryDocumentParser().parse(await request.body(), format)
        except DocumentFailure:
            return JSONResponse(
                status_code=422,
                content={
                    "error": {
                        "code": "document_unreadable",
                        "message": "Could not read this file. "
                        "Use a text PDF (up to 20 pages) or DOCX, "
                        "under 4 MB and 20,000 extracted characters. Encrypted/scanned files "
                        "may not work. You can paste relevant text instead. Nothing was saved.",
                    }
                },
            )

    @app.post("/api/import-linkedin", response_model=LinkedInText)
    async def import_linkedin(request: LinkedInRequest) -> LinkedInText | JSONResponse:
        try:
            return await PublicLinkedInReader().read(request)
        except LinkedInUnavailable:
            return JSONResponse(
                status_code=422,
                content={
                    "error": {
                        "code": "linkedin_unavailable",
                        "message": "LinkedIn did not provide readable public background. "
                        "Upload your profile PDF export or paste the relevant text instead. "
                        "No login or access restrictions were bypassed; nothing was saved.",
                    }
                },
            )

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, exc: RequestValidationError) -> JSONResponse:
        # FastAPI's default errors echo offending input; emit static details instead.
        if request.url.path == "/api/import-linkedin":
            return JSONResponse(
                status_code=422,
                content={
                    "error": {
                        "code": "invalid_linkedin_url",
                        "message": "Use a public https://www.linkedin.com/in/profile-name URL.",
                    }
                },
            )
        if request.url.path == "/api/import-document":
            return JSONResponse(
                status_code=422,
                content={
                    "error": {
                        "code": "invalid_document_format",
                        "message": "Use format=pdf or format=docx.",
                    }
                },
            )
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "invalid_conversation",
                    "message": "Use 1–64 user/assistant messages, 1–4000 characters each "
                    "(20,400 for imported background), "
                    "24000 characters total, starting and ending with user. "
                    "Nothing was truncated.",
                }
            },
        )

    @app.exception_handler(ChatUnavailable)
    async def unavailable(request: Request, exc: ChatUnavailable) -> JSONResponse:
        return JSONResponse(
            status_code=503,
            content={
                "error": {
                    "code": exc.reason.value,
                    "message": FAILURE_MESSAGES[exc.reason]
                    + (
                        " Timed out while " + STAGE_LABELS[exc.stage] + "."
                        if exc.reason == FailureReason.TIMEOUT and exc.stage
                        else ""
                    ),
                }
            },
        )

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": "http_error",
                    "message": "Request could not be handled.",
                }
            },
        )

    @app.post("/api/chat", response_model=ChatResponse)
    async def chat(request: ChatRequest) -> ChatResponse:
        if mode == "diagnostic":
            return dummy_response()
        return await (chat_service or service).chat(request)

    @app.get("/api/diagnostics/dummy", response_model=ChatResponse)
    async def diagnostic_dummy() -> ChatResponse:
        # No request content is read by a provider or retrieval dependency here.
        return dummy_response()

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "mode": mode}

    return app


def app_from_environment() -> FastAPI:
    from trojan_compass.composition import create_configured_app

    configure_private_logging()
    return create_configured_app()


def configured_extractor() -> ContextExtractor:
    """Select a server-only provider; invalid/missing configuration fails closed."""
    provider = os.environ.get("LLM_PROVIDER", "openai")
    if provider == "ollama":
        from trojan_compass.ollama import OllamaContextExtractor, configured_ollama

        configured_ollama()  # Validate endpoint/model settings before accepting requests.
        return OllamaContextExtractor()
    if provider == "gemini":
        key = os.environ.get("GEMINI_API_KEY", "")
        model = os.environ.get("GEMINI_MODEL", "")
        if not key or not model:
            raise ValueError("GEMINI_API_KEY and GEMINI_MODEL are required")
        return GeminiContextExtractor(key, model)
    if provider != "openai":
        raise ValueError("LLM_PROVIDER must be openai, gemini or ollama")
    key = os.environ.get("OPENAI_API_KEY", "")
    model = os.environ.get("OPENAI_MODEL", "")
    if not key or not model:
        raise ValueError("OPENAI_API_KEY and OPENAI_MODEL are required")
    return OpenAIContextExtractor(key, model)
