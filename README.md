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

## Local test launcher

After configuring the server-only `.env`, run `bash scripts/dev.sh` from a normal
terminal. It checks local port permissions, creates/uses a project Python
`.venv`, installs missing dependencies, starts both services, and verifies their
HTTP readiness before printing the URL. Keep the terminal open while testing;
Ctrl+C stops both services. A sandbox that prohibits local listeners cannot host
this preview; the launcher reports that specific failure without claiming the
site is running. No conversation or prompt logs are written by the launcher.

## Integrated startup

All four workstreams now connect through the v2 contracts. The backend factory
wires configured LLM extraction → chat orchestration → Peri's `RecommendationEngine` →
Abishek's graph adapter. Riddhi's frontend sends the entire active in-memory
conversation to the same `/api/chat` route.

| `COMPASS_MODE` | Extraction | Recommendations and graph |
| --- | --- | --- |
| `demo` (default) | Offline; extracts no student facts | Existing fixed course fixture, explicitly labeled |
| `campus` | OpenAI or Gemini, requires server credentials | Real engine over reviewed USC seed using Abishek's in-memory adapter |
| `production` | OpenAI or Gemini, requires server credentials | Real engine over configured Neo4j; never falls back to fixtures |

For the integrated USC seed journey, set `COMPASS_MODE=campus` and provider
credentials in your server environment. OpenAI is the default (`OPENAI_API_KEY`,
`OPENAI_MODEL`). For Gemini, set `LLM_PROVIDER=gemini`, `GEMINI_API_KEY` and
`GEMINI_MODEL`. Choose a model supporting the provider’s structured-output API,
then start the same backend command above. See [provider setup and retention](docs/PROVIDERS.md). The reviewed seed
ships inside the wheel and loads at startup only. Optional `COMPASS_SEED_PATH`
selects a server-owned public graph import file; it is never a student upload.
No database is needed for campus mode. This is a snapshot, not live campus data.

For production, also set `NEO4J_URI`, `NEO4J_USERNAME`, `NEO4J_PASSWORD` and optional
`NEO4J_DATABASE` (default `neo4j`). Import public data separately using
`trojan-compass-import data/seed/usc.json`; the chat server performs no graph
imports or writes. The factory closes its Neo4j driver on shutdown. Use a
read-only database account for the chat runtime and a separate importer account.
Missing configuration fails startup; unavailable dependencies produce safe 503s.
See [data setup](docs/DATA_IMPORT.md) for database-side parameter logging controls.

For the frontend, in a second terminal:

```sh
cd frontend
cp .env.example .env.local
npm ci
npm run dev
```

The example now sets `VITE_USE_MOCK_API=false`, so the frontend uses the real API
through Vite's same-origin `/api` proxy. To deliberately use frontend-only fixtures,
set it to `true`. No frontend environment file contains backend/provider credentials.
The backend `.env.example` documents variables; it is not automatically loaded.
Configure them in your server environment and restart both servers after changes.

Each extractor sends the full conversation as untrusted data in one typed
request, validates the schema and user-quotation provenance, and retains no
provider thread or previous-response state. OpenAI uses Chat Completions with
`store=false`; Gemini uses a standalone `generateContent` request without tools
or explicit context caches. Live model
accuracy and external retention controls still require account-specific validation.
No real student data, provider call or live Neo4j database was used for the
integration tests. HTTP-provider responses and the database lifecycle are mocked;
the USC seed adapter, engine, chat orchestration and frontend contract are real.

The current seed is small: course identities, a career-event recurrence/occurrence,
and a general software-developer requirement. It has no company/team requirements
or verified enrollment availability. Some course-skill links are inferred. The
current graph model omits date-only event schedules, prerequisite edges and some
source semantics when returning actions. The UI exposes unknowns and coverage
limitations; consult [graph limitations](docs/GRAPH_INTEGRATION.md). Missing matches
are not evidence that USC lacks suitable opportunities.

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
Gemini retention and paid/unpaid data-use differences are documented separately
in [provider setup](docs/PROVIDERS.md); its retention is not claimed to be disabled.
No claim is made about the retention settings of the environment running this
repository or external infrastructure.

## Checks

```sh
pytest -q
mypy src tests
ruff check src tests
ruff format --check src tests
cd frontend
npm test
npm run build
```

Tests cover supported evidence, multi-turn payloads and corrected snapshots,
assistant-vs-user provenance, unknown skills/coursework, graph clarifications,
concurrent/sequential request isolation, oversized and chunked requests,
malformed input, dependency/provider failures, no file I/O during chat and
content-safe responses/logging. Tests use fake extractors, recommendation services
and HTTP transports. They verify plumbing and policy without real student data.

## Project ownership

- **Karthik:** stateless chat API, request/response contracts, and orchestration.
- **Abishek:** knowledge graph and USC source data.
- **Peri:** recommendation service, matching, and evidence.
- **Frontend:** onboarding, conversation UX, suggested replies, recommendation cards, source disclosures, and recoverable errors.

## Frontend

See [`frontend/README.md`](frontend/README.md) for setup, adapter configuration, privacy behavior, and frontend checks.

## Shared campus graph

Install the project with `pip install -e .`, configure `NEO4J_URI`, `NEO4J_USERNAME`, and
`NEO4J_PASSWORD`, then import sourced seed data or a reviewed CSV/JSON partner update:

```sh
trojan-compass-import data/seed/usc.json
trojan-compass-import path/to/campus-update.csv
trojan-compass-import path/to/campus-update.json
```

Imports merge on stable identifiers and can be repeated to update shared records. See
[`docs/DATA_IMPORT.md`](docs/DATA_IMPORT.md) for templates, required fields, source refresh
limits, and database query-log privacy settings. See
[`docs/GRAPH_INTEGRATION.md`](docs/GRAPH_INTEGRATION.md) for the graph/recommendation contract.
