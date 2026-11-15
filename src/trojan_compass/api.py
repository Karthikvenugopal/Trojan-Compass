"""HTTP composition and privacy boundary. No sessions, cookies or student repositories."""

import logging
import os
from typing import Literal

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException
from starlette.types import ASGIApp, Lifespan, Message, Receive, Scope, Send

from trojan_compass.contracts import (
    MAX_BODY_BYTES,
    ChatRequest,
    ChatResponse,
    ContextExtractor,
    RecommendationService,
)
from trojan_compass.extraction import DemoContextExtractor, OpenAIContextExtractor
from trojan_compass.services import ChatService, ChatUnavailable, DemoRecommendationService

AppMode = Literal["demo", "campus", "production"]


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

        chunks: list[bytes] = []
        total = 0
        # Inspect the actual stream, not just spoofable/missing Content-Length.
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            total += len(chunk)
            if total > MAX_BODY_BYTES:
                response = JSONResponse(
                    status_code=413,
                    content={
                        "error": {
                            "code": "conversation_too_large",
                            "message": "Request exceeds 65536 bytes; nothing was truncated.",
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
) -> FastAPI:
    """Inject Abishek→Peri service here; fail closed for missing production dependencies."""
    configure_private_logging()
    if mode != "demo" and (extractor is None or recommendations is None):
        raise ValueError("Production requires an extractor and real RecommendationService")
    service = ChatService(
        extractor or DemoContextExtractor(),
        recommendations or DemoRecommendationService(),
    )
    app = FastAPI(title="Trojan Compass", version="0.2.0", debug=False, lifespan=lifespan)
    app.add_middleware(PrivateBoundary)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, exc: RequestValidationError) -> JSONResponse:
        # FastAPI's default errors echo offending input; emit static details instead.
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "invalid_conversation",
                    "message": "Use 1–64 user/assistant messages, 1–4000 characters each, "
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
                    "code": "chat_unavailable",
                    "message": "Recommendations are temporarily unavailable. Please try again.",
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
        return await service.chat(request)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "mode": mode}

    return app


def app_from_environment() -> FastAPI:
    from trojan_compass.composition import create_configured_app

    configure_private_logging()
    return create_configured_app()


def configured_extractor() -> OpenAIContextExtractor:
    """Server-only configuration for use by the production composition factory."""
    key = os.environ.get("OPENAI_API_KEY", "")
    model = os.environ.get("OPENAI_MODEL", "")
    if not key or not model:
        raise ValueError("OPENAI_API_KEY and OPENAI_MODEL are required")
    return OpenAIContextExtractor(key, model)
