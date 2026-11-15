"""Explicit browser-origin configuration; no wildcard or credentialed CORS."""

import os

from pydantic import HttpUrl

LOCAL_ORIGINS = ("http://localhost:5173", "http://127.0.0.1:5173")


def configured_origins() -> tuple[str, ...]:
    configured = os.getenv("COMPASS_CORS_ORIGINS")
    if configured is None:
        return LOCAL_ORIGINS
    return validate_origins(
        tuple(value.strip() for value in configured.split(",") if value.strip())
    )


def validate_origins(origins: tuple[str, ...]) -> tuple[str, ...]:
    normalized: list[str] = []
    for origin in origins:
        try:
            parsed = HttpUrl(origin)
            if (
                parsed.username is not None
                or parsed.password is not None
                or parsed.path not in (None, "/")
                or parsed.query is not None
                or parsed.fragment is not None
                or "*" in origin
            ):
                raise ValueError()
        except ValueError:
            raise ValueError(
                "CORS origins must be HTTP(S) origins without paths or credentials",
            ) from None
        normalized.append(str(parsed).rstrip("/"))
    return tuple(dict.fromkeys(normalized))
