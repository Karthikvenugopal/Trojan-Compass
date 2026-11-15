"""Content-free failure metadata. No provider message, prompt or response is retained."""

from enum import StrEnum

import httpx


class FailureReason(StrEnum):
    INVALID_OUTPUT = "invalid_model_output"
    SCHEMA = "invalid_model_structure"
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
    FailureReason.SCHEMA: (
        "The AI returned an invalid context structure after validation repair. "
        "Your message is preserved. Error: invalid_model_structure."
    ),
    FailureReason.EVIDENCE: (
        "The AI could not tie its interpretation to your actual words "
        "after validation repair. Your message is preserved. "
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
        "The AI response could not be safely validated. Your message is still here. Guided "
        "choices can be processed directly."
    ),
    FailureReason.INTERNAL: (
        "This request could not be completed. Your message is still here; no recommendations "
        "were fabricated."
    ),
}
