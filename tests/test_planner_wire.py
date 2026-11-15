"""Reproduce JSON-schema-valid local output rejected by hidden Python-only invariants."""

import json

import httpx
import pytest

from trojan_compass.ai_chat import ConversationDecision
from trojan_compass.contracts import Clarification, RetrievalContext
from trojan_compass.ollama import OllamaStructuredLLM


@pytest.mark.asyncio
async def test_schema_valid_unanswered_echo_is_normalized_before_python_validation() -> None:
    raw = ConversationDecision(
        context=RetrievalContext(),
        intent="ask",
        question=Clarification(
            text="What would you like to explore?",
            options=["Art", "Science", "I’m not sure"],
            requested_fields=["direction"],
            reason="An initial direction helps.",
        ),
    ).model_dump()
    raw["context"]["answers"] = [
        {"field": "program", "status": "not_answered", "value": "Unknown", "evidence": []}
    ]
    # The published wire schema permits these field values independently. Its
    # Python model_validator adds a conditional constraint the decoder cannot see.
    schema = ConversationDecision.model_json_schema()["$defs"]["StudentAnswer"]["properties"]
    assert "not_answered" in schema["status"]["enum"]
    assert any(option.get("type") == "string" for option in schema["value"]["anyOf"])

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/show":
            return httpx.Response(200, json={"model_info": {"qwen3.context_length": 40960}})
        return httpx.Response(
            200,
            json={
                "message": {"role": "assistant", "content": json.dumps(raw)},
                "done": True,
                "done_reason": "stop",
            },
        )

    result = await OllamaStructuredLLM("qwen3:4b", transport=httpx.MockTransport(handler)).complete(
        "Return the supplied JSON schema.", "Synthetic greeting", ConversationDecision
    )
    assert result.context.answers[0].status == "not_answered"
    assert result.context.answers[0].value is None
    assert result.context.answers[0].evidence == []


def test_compact_facts_preserve_unknown_without_conditional_null_generation() -> None:
    from trojan_compass.contracts import ChatMessage
    from trojan_compass.planner_wire import PlannerOutput

    result = PlannerOutput.model_validate(
        {
            "intent": "ask",
            "facts": [
                {
                    "field": "program",
                    "status": "unknown",
                    "value": "I do not know",
                    "message_index": 0,
                    "quote": "I do not know",
                }
            ],
        }
    )
    context = result.context([ChatMessage(role="user", content="I do not know")])
    assert context.program is None
    assert context.answers[0].status == "unknown" and context.answers[0].value is None


def test_compact_facts_ground_before_applying_out_of_order_corrections() -> None:
    from trojan_compass.contracts import ChatMessage
    from trojan_compass.planner_wire import PlannerOutput

    messages = [
        ChatMessage(role="user", content="I study Physics"),
        ChatMessage(role="assistant", content="Any correction?"),
        ChatMessage(role="user", content="Correction: I study Music now."),
    ]
    # Reverse output order and a miscounted index must not restore the old major.
    result = PlannerOutput.model_validate(
        {
            "intent": "search",
            "facts": [
                {
                    "field": "program",
                    "status": "provided",
                    "value": "Music",
                    "message_index": 1,
                    "quote": "I study Music now.",
                },
                {
                    "field": "program",
                    "status": "provided",
                    "value": "Physics",
                    "message_index": 0,
                    "quote": "I study Physics",
                },
            ],
        }
    )
    context = result.context(messages)
    assert context.program and context.program.value == "Music"
    assert context.program.evidence[0].message_index == 2


def test_compact_course_fact_does_not_establish_skill_mastery() -> None:
    from trojan_compass.contracts import ChatMessage
    from trojan_compass.planner_wire import PlannerOutput

    result = PlannerOutput.model_validate(
        {
            "intent": "search",
            "facts": [
                {
                    "field": "completed_course",
                    "status": "provided",
                    "value": "MUSC 100",
                    "message_index": 0,
                    "quote": "I completed MUSC 100",
                }
            ],
        }
    )
    context = result.context([ChatMessage(role="user", content="I completed MUSC 100")])
    assert context.completed_courses[0].value == "MUSC 100" and context.skills == []


def test_compact_schema_does_not_accept_unanswered_rows_or_multiple_question_fields() -> None:
    from pydantic import ValidationError

    from trojan_compass.planner_wire import PlannerOutput

    with pytest.raises(ValidationError):
        PlannerOutput.model_validate(
            {
                "intent": "ask",
                "facts": [
                    {
                        "field": "program",
                        "status": "not_answered",
                        "value": "unknown",
                        "message_index": 0,
                        "quote": "Hi",
                    }
                ],
            }
        )
    with pytest.raises(ValidationError):
        PlannerOutput.model_validate(
            {
                "intent": "ask",
                "question": {
                    "field": ["program", "study_stage"],
                    "text": "Two questions?",
                    "reason": "Invalid",
                    "options": [],
                },
            }
        )
