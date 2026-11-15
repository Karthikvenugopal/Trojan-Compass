"""Content-free failure metadata. No provider message, prompt or response is retained."""

from enum import StrEnum

import httpx


class FailureReason(StrEnum):
    INVALID_OUTPUT = "invalid_model_output"
    SCHEMA = "invalid_model_structure"
    DECISION = "invalid_ai_next_step"
    EVIDENCE = "invalid_model_evidence"
    CONFLICT = "conflicting_model_fields"
    TRUNCATED = "incomplete_model_output"
    REFUSAL = "model_refusal"
    AUTH = "provider_authentication"
    QUOTA = "provider_quota"
    RATE_LIMIT = "provider_rate_limit"
    TIMEOUT = "provider_timeout"
    NETWORK = "provider_connection"
    PROVIDER = "provider_unavailable"
    CONFIGURATION = "provider_configuration"
    INTERNAL = "service_failure"
    LOCAL_CONTEXT = "local_context_limit"


class DecisionIssue(StrEnum):
    MISSING_QUESTION = "missing_question"
    REPEATED_QUESTION = "asked_answered_field"
    QUESTION_SCOPE = "question_outside_missing_fields"
    EARLY_SEARCH = "minimum_not_answered"
    EMPTY_QUERY = "empty_search_query"
    SEARCH_QUESTION = "search_and_question_conflict"
    CAREER_REQUIRED = "career_target_made_mandatory"
    INVALID_ROUTE = "invalid_campus_route"


class CompositionIssue(StrEnum):
    RESOURCE_IDS = "invalid_or_duplicate_resource_ids"
    SKILL_IDS = "invalid_or_duplicate_skill_ids"
    STEP_ORDER = "invalid_step_dependency_order"
    STEP_REFERENCES = "step_references_unselected_evidence"
    GENERATED_URL = "generated_url_in_prose"


class ProcessingStage(StrEnum):
    CAMPUS_ANSWER = "campus_answer"
    EXTRACTION = "extraction"
    COURSE_HISTORY = "course_history"
    RETRIEVAL = "retrieval"
    GUIDANCE = "guidance"


STAGE_LABELS = {
    ProcessingStage.CAMPUS_ANSWER: "answering a campus question",
    ProcessingStage.EXTRACTION: "interpreting your answer",
    ProcessingStage.COURSE_HISTORY: "finding course-history examples",
    ProcessingStage.RETRIEVAL: "searching campus data",
    ProcessingStage.GUIDANCE: "building the career guide",
}


def provider_reason(error: httpx.HTTPStatusError) -> FailureReason:
    status = error.response.status_code
    if status in (401, 403):
        return FailureReason.AUTH
    if status == 429:
        try:
            if error.response.json().get("error", {}).get("code") == "insufficient_quota":
                return FailureReason.QUOTA
        except (ValueError, AttributeError):
            pass
        return FailureReason.RATE_LIMIT
    return FailureReason.CONFIGURATION if status in (400, 404, 422) else FailureReason.PROVIDER


FAILURE_MESSAGES = {
    FailureReason.DECISION: (
        "The AI did not choose a valid next step after a retry. "
        "Your message is preserved; no search or recommendation was fabricated."
    ),
    FailureReason.LOCAL_CONTEXT: (
        "The local model context budget is too small for this request. Nothing was truncated. "
        "Use a shorter background or configure a larger supported OLLAMA_CONTEXT_LENGTH."
    ),
    FailureReason.SCHEMA: (
        "The AI response did not match the required structure. "
        "Your message is preserved. Error: invalid_model_structure."
    ),
    FailureReason.EVIDENCE: (
        "The AI response failed evidence validation. Your message is preserved. "
        "Error: invalid_model_evidence."
    ),
    FailureReason.CONFLICT: (
        "The AI returned conflicting interpretations after validation repair. "
        "Your message is preserved. Error: conflicting_model_fields."
    ),
    FailureReason.TRUNCATED: (
        "The AI response was cut off before extraction completed. "
        "Your message is preserved. Error: incomplete_model_output."
    ),
    FailureReason.REFUSAL: (
        "The AI provider declined this extraction request. "
        "Your message is preserved. Error: model_refusal."
    ),
    FailureReason.AUTH: (
        "The AI provider rejected the server credentials. Update the server API key; retrying "
        "this message will not fix that."
    ),
    FailureReason.QUOTA: (
        "The AI provider reports exhausted API quota. Check the provider account's credits or "
        "limits; retrying will not fix exhausted quota."
    ),
    FailureReason.RATE_LIMIT: (
        "The AI provider is rate-limiting requests. Wait briefly before retrying; your "
        "message is still here."
    ),
    FailureReason.TIMEOUT: ("This request timed out. Your text is still here to retry."),
    FailureReason.NETWORK: (
        "The server could not connect to the AI provider. Check the server's connection; your "
        "message is still here."
    ),
    FailureReason.PROVIDER: (
        "The AI provider is unavailable. Your message is still here; try again when the "
        "provider recovers."
    ),
    FailureReason.CONFIGURATION: (
        "The AI provider rejected the server model or request configuration. The server setup "
        "needs fixing; repeated retries will not help."
    ),
    FailureReason.INVALID_OUTPUT: (
        "The AI response could not be safely validated. Your message is still here. No "
        "scripted recommendations were substituted."
    ),
    FailureReason.INTERNAL: (
        "This request could not be completed. Your message is still here; no recommendations "
        "were fabricated."
    ),
}
