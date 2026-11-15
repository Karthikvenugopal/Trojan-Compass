"""Static policy fixture for focused orchestration tests written for two fields.

These tests isolate corrections, failures, privacy and graph behavior from the
university intake checklist. Full default-policy HTTP journeys live separately
in test_university.py; this never supplies or invents student facts.
"""

from typing import Any

from fastapi import FastAPI

from trojan_compass.api import create_app as default_app
from trojan_compass.composition import create_configured_app as configured_app
from trojan_compass.composition import seed_repository
from trojan_compass.contracts import ChatMessage, RetrievalContext
from trojan_compass.readiness import COMPACT_FIXED_FIELDS, RequestInformation
from trojan_compass.readiness import request_information as default_information
from trojan_compass.services import AskBackPolicy as DefaultPolicy
from trojan_compass.services import ChatService as DefaultService


class AskBackPolicy(DefaultPolicy):
    def __init__(self) -> None:
        super().__init__(COMPACT_FIXED_FIELDS)


class ChatService(DefaultService):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs.setdefault("policy", AskBackPolicy())
        super().__init__(*args, **kwargs)


def create_app(*args: Any, **kwargs: Any) -> FastAPI:
    kwargs.setdefault("policy", AskBackPolicy())
    return default_app(*args, **kwargs)


def create_configured_app(*args: Any, **kwargs: Any) -> FastAPI:
    kwargs.setdefault("policy", AskBackPolicy())
    # Shared tiny seed makes focused coverage-gap tests independent of refreshes.
    if args and args[0].mode == "campus" and "graph" not in kwargs:
        kwargs["graph"] = seed_repository(args[0].seed_path)
    return configured_app(*args, **kwargs)


def request_information(
    context: RetrievalContext, messages: list[ChatMessage]
) -> RequestInformation:
    return default_information(context, messages, COMPACT_FIXED_FIELDS)
