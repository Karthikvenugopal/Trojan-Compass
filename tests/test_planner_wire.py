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


def test_answer_audit_recovers_interest_from_question_and_keeps_uncertainty() -> None:
    from trojan_compass.contracts import ChatMessage, StudentAnswer, StudentStatement
    from trojan_compass.planner_wire import (
        IntakeAudit,
        PlannerOutput,
        PlannerQuestion,
        QuestionReview,
        apply_question_review,
    )
    from trojan_compass.readiness import request_information

    messages = [
        ChatMessage(
            role="user", content="Which courses help with an AI career? I am unsure about timing."
        )
    ]
    wire = PlannerOutput(
        intent="ask",
        question=PlannerQuestion(field="direction", text="What interests you?", reason="Synthetic"),
    )
    audit = [
        StudentAnswer(field=f, status="not_answered")
        for f in ["study_stage", "program", "work_experience", "completed_courses"]
    ]
    audit += [
        StudentAnswer(
            field="direction",
            status="provided",
            value="Artificial intelligence",
            evidence=[StudentStatement(message_index=0, quote="AI career")],
        ),
        StudentAnswer(
            field="time_window",
            status="unknown",
            evidence=[StudentStatement(message_index=0, quote="unsure about timing")],
        ),
    ]
    review = QuestionReview(
        next_step="ask",
        answer_audit=IntakeAudit.from_answers(audit),
        question=PlannerQuestion(
            field="study_stage", text="What level are you studying?", reason="Synthetic"
        ),
    )
    updated = apply_question_review(wire, review)
    info = request_information(updated.context(messages), messages, ai_owned=True)
    assert info.answer("direction").status == "provided"
    assert info.answer("time_window").status == "unknown"
    assert updated.question and updated.question.field == "study_stage"


def test_incomplete_answer_audit_is_rejected_instead_of_repeating_a_question() -> None:
    from trojan_compass.contracts import StudentAnswer
    from trojan_compass.extraction import ExtractionFailure
    from trojan_compass.planner_wire import (
        IntakeAudit,
        PlannerOutput,
        QuestionReview,
        apply_question_review,
    )

    audit = [StudentAnswer(field="program", status="not_answered") for _ in range(6)]
    with pytest.raises(ExtractionFailure):
        apply_question_review(
            PlannerOutput(intent="ask"),
            QuestionReview(next_step="ask", answer_audit=IntakeAudit.from_answers(audit)),
        )


def test_assistant_resource_context_is_not_student_evidence() -> None:
    from pydantic import ValidationError

    from trojan_compass.contracts import ChatMessage, ShownResource
    from trojan_compass.extraction import ExtractionFailure
    from trojan_compass.planner_wire import PlannerOutput, StudentFact

    resource = ShownResource(
        id="test-course", title="Synthetic course", kind="course", section="plan"
    )
    with pytest.raises(ValidationError):
        ChatMessage(role="user", content="hello", shown_resources=[resource])
    messages = [
        ChatMessage(role="user", content="Help me choose"),
        ChatMessage(role="assistant", content="Explore this.", shown_resources=[resource]),
    ]
    wire = PlannerOutput(
        intent="search",
        facts=[
            StudentFact(
                field="completed_course",
                status="provided",
                value="Synthetic course",
                message_index=1,
                quote="Synthetic course",
            )
        ],
    )
    with pytest.raises(ExtractionFailure):
        wire.context(messages)


def test_named_target_audit_projects_to_a_valid_request_local_fact() -> None:
    from trojan_compass.contracts import ChatMessage, StudentAnswer, StudentStatement
    from trojan_compass.planner_wire import AuditedDecision, IntakeAudit
    from trojan_compass.readiness import request_information

    user = ChatMessage(role="user", content="I want to become a software engineer.")
    answers = [
        StudentAnswer(field=f, status="not_answered")
        for f in [
            "direction",
            "study_stage",
            "program",
            "work_experience",
            "completed_courses",
            "time_window",
        ]
    ]
    answers.append(
        StudentAnswer(
            field="target",
            status="provided",
            value="Software engineer",
            evidence=[StudentStatement(message_index=0, quote="software engineer")],
        )
    )
    decision = AuditedDecision(
        answer_audit=IntakeAudit.from_answers(answers), academic_level=None, intent="ask"
    )
    context = decision.planner().context([user])
    info = request_information(context, [user], ai_owned=True)
    assert info.answer("target").status == "provided"
    assert info.answer("direction").status == "provided"


@pytest.mark.parametrize("status", ["provided", "unknown", "none"])
def test_audited_answer_wire_requires_provenance_for_answered_states(status: str) -> None:
    from pydantic import TypeAdapter, ValidationError

    from trojan_compass.planner_wire import AnswerObservation

    decoder: TypeAdapter[AnswerObservation] = TypeAdapter(AnswerObservation)
    with pytest.raises(ValidationError):
        decoder.validate_python(
            {
                "status": status,
                "value": "Synthetic value" if status == "provided" else None,
                "evidence": [],
            }
        )
    result = decoder.validate_python({"status": "not_answered", "value": None, "evidence": []})
    assert result.status == "not_answered"
