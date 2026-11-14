# Trojan Compass

Trojan Compass connects student goals to USC courses and events through a shared
knowledge graph. This branch implements the **stateless chat backend**.

`POST /api/chat` accepts the active conversation and returns a grounded message,
suggested replies, recommendations and limitations. It never requires a session
identifier or returns a student profile. The frontend owns the conversation in
memory; each request re-derives temporary retrieval context from that conversation.

## Run

Python 3.11+:

```sh
python -m venv .venv
source .venv/bin/activate
pip install -e . pytest pytest-asyncio mypy ruff
uvicorn trojan_compass.api:app_from_environment --factory --no-access-log
```

Default `COMPASS_MODE=demo` makes **no LLM or KG calls**. Try “Help me get started”,
then “I'm not sure”. The demo asks one question and shows a fixed CSCI 102 example
with its official source, unknowns and a demo label. It does not interpret a
student's background or claim personalized ranking. No current event fixture is
available. The public course page was checked on 2026-11-14; it is a static fixture,
not evidence of current enrollment availability.

```sh
curl http://127.0.0.1:8000/api/chat \
  -H 'Content-Type: application/json' \
  -d '{"messages":[{"role":"user","content":"Help me get started"}]}'
```

OpenAPI is at `/docs`. Shared Pydantic models are in
`src/trojan_compass/contracts`; JSON examples and schemas are in `docs/examples`.
Examples use synthetic student statements. `GET /health` reports the configured
mode. There are no session, resume or LinkedIn ingestion endpoints.

## Production composition

Peri and Abishek's implementations are not present in master or this branch.
The integration boundary is ready, but live graph integration is pending their
implementations and contract confirmation; see [the handoff](docs/INTEGRATION.md).
Construct Abishek's read-only adapter, inject it into Peri's recommendation
service, then inject that service into the chat app:

```python
from trojan_compass.api import configured_extractor, create_app

# Inside your deployment's app factory, after building Peri's service:
# return create_app(mode="production", extractor=configured_extractor(),
#                   recommendations=peri_service)
```

Set `OPENAI_API_KEY` and `OPENAI_MODEL` server-side for a model supporting strict
structured outputs. The extractor uses a typed schema and validates all returned
facts and quotation provenance. It sends the full conversation as untrusted data
in one Chat Completions request with `store=false`. No provider conversation IDs,
threads or previous-response state are used. No live provider call was run during
implementation, and no API key is needed for tests. `COMPASS_MODE=production` in
the generic demo factory fails closed; production must use the composition above.

## Behavior and limits

- Requests allow 1–64 messages, 1–4000 characters each, 24000 characters total,
  and 65536 raw UTF-8 body bytes. First and last messages must be from the user.
  Roles are user/assistant only; no extra fields. Excess bytes return 413;
  invalid/oversized structured conversations return 422. Nothing is truncated.
- Context contains interests, skill statuses and evidence, completed courses,
  experiences, optional program/target/goals, and constraints. Each fact cites a
  student quotation and its message index. The extractor re-reads all turns;
  corrections replace earlier claims. Assistant text cannot supply evidence.
- Missing or uncertain skills remain `unknown`. Coursework never automatically
  proves mastery. Quotation provenance is mechanically checked; semantic
  interpretation, including subtle corrections/negations, still depends on the
  model. Offline tests cannot establish live-model accuracy. Evaluate this with
  synthetic conversations against the chosen model before real deployment.
- Retrieval runs without requiring a career target or questionnaire. Peri's
  graph-informed service can return one material clarification, with or without
  provisional recommendations. The policy removes questions whose requested
  field is already answered, unsupported fields, and previously asked identical
  questions. “I'm not sure” is always offered. Peri should return broad options
  when the student cannot narrow their interests; do not repeatedly gate results.
- Recommendations require sources and evidence paths. Composition is deterministic
  and makes no campus claims beyond the returned records. Missing results are
  acknowledged; retrieval, extraction, refusal, schema or timeout failures yield
  a static 503 error. Provider calls time out at 25 seconds; orchestration at 40.
- The service is stateless, with no retry/replay queue or cross-request context.
  A malformed dependency result fails closed. It caps results to the requested
  limit and forwards unknowns and limitations.

## Privacy and deployment

There is no student database, session store, Redis, profile cache, student KG node,
file write, browser storage, transcript log or application memory across requests.
Only request-local objects contain student data; they become eligible for normal
Python garbage collection after processing. This is not secure memory erasure.
Injected services must honor the same no-persistence contract. The frontend must
send the active conversation again on the next turn and discard it on clear.

Responses use `Cache-Control: no-store`; no cookies are set. Validation and error
responses never echo input or provider exceptions. Application code emits no
student-content logs. HTTP/debug/access loggers are disabled. No Sentry, tracing,
analytics or LLM instrumentation is installed or initialized. Do not enable
body/prompt/response capture or attach student context as trace attributes in a
hosting integration; proxy logs must omit bodies and query content. Keep the
server bound to localhost for local development; deploy behind your normal HTTPS
and ingress limits. Render returned text as text and source links safely.

External provider retention is separate: `store=false` does **not** disable all
provider retention. OpenAI documents default abuse-monitoring retention of up to
30 days; special retention controls require provider approval/configuration. This
project has **not verified or configured zero data retention**. Review your account
controls before sending student content. See [OpenAI data controls](https://developers.openai.com/api/docs/guides/your-data)
and [structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs).
No claim is made about the retention settings of the environment running this
repository or external infrastructure.

## Checks

```sh
pytest -q
mypy src tests
ruff check src tests
ruff format --check src tests
```

Tests cover supported evidence, multi-turn payloads and corrected snapshots,
assistant-vs-user provenance, unknown skills/coursework, graph clarifications,
concurrent/sequential request isolation, oversized and chunked requests,
malformed input, dependency/provider failures, no file I/O during chat and
content-safe responses/logging. Tests use fake extractors, recommendation services
and HTTP transports. They verify plumbing and policy without real student data.
