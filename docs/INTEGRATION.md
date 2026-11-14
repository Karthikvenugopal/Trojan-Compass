# Integration handoff — contract v1

Owners: Abishek (graph/ingestion), Peri (recommendations), Riddhi (frontend), conversation backend (sessions, extraction, API, final composition).

The repository was empty at inspection; there were no existing dependencies or owner implementations to modify. Contracts are published first in `src/trojan_compass/contracts/__init__.py`; JSON examples are in `docs/examples`. All example students and resources are synthetic.

**Proposed signature for Peri: `async def recommend(request: RecommendationRequest) -> RecommendationResult`.** Async keeps graph/LLM I/O off the server event loop. Inject the implementation into `create_app(recommendations=...)`. A synchronous implementation must be wrapped with `asyncio.to_thread`; do not call blocking retrieval directly. This is a published proposal, not a claim that Peri has approved it. No reachable teammate contact or existing integration thread was supplied. Confirm the signature in the PR before integration.

- Abishek: supply shared course/event evidence, URLs, timestamps and graph paths through Peri. No conversation/profile writes to the KG; this backend has no graph write client.
- Peri: return course/event recommendations, graph evidence and material clarification requests. Unknown skills remain unknown. `not_yet_learned` requires an explicit student statement. Return one clarification with stable ID, requested profile fields, options and reason. Use paths such as `target`, `skills.python`, `constraints.time_window`. Clarification may accompany provisional recommendations. Do not persist or log requests. Backend validates responses and caps the returned count.
- Riddhi: create a session, send messages, render `ChatResponse`, and delete on explicit clear. Render source URLs, evidence, unknowns and limitations alongside recommendations. IDs are bearer capabilities: keep them in tab memory; do not add profiles/messages to localStorage, analytics or console logs. 404 `session_unavailable` means create a fresh session; 503 capacity errors mean retry later. Do not automatically replay private messages into a new session. Streaming, auth, resumes and LinkedIn are outside this POC.

Optional fields use JSON null. Collections default to independent empty lists. Skill statuses: `known`, `learning`, `not_yet_learned`, `unknown`. Lists in extraction patches replace the specified field; omitted fields remain unchanged; nullable fields can be explicitly cleared. Contracts reject extra fields and non-HTTP action/source URLs. OpenAPI at `/openapi.json` is the API schema.
