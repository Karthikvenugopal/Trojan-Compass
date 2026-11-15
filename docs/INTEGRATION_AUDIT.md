# End-to-end audit

The audit follows the local launcher, environment/provider selection, Vite API
proxy, frontend response decoding, ASGI privacy boundary, structured extraction,
recommendation service and graph/import adapters. All conversations in checks are
synthetic. No student state, transcript storage, sessions or content logging was
added. Real provider credentials remain in ignored server-only configuration.

## Reproduced and fixed

- **CORS preflight:** direct requests from either frontend development origin
  returned 405 without an allow-origin header. The backend now permits exactly
  `http://localhost:5173` and `http://127.0.0.1:5173`, supports POST preflight, and
  preserves CORS on sanitized validation/oversize/dependency errors. Other
  origins are rejected. Cookies/credentialed CORS and wildcard origins are not
  enabled. `COMPASS_CORS_ORIGINS` accepts an explicit comma-separated production
  allowlist; empty disables cross-origin access.
- **API base URL:** a trailing slash produced `//api/chat`. The frontend now
  normalizes it before making the request.
- **Malformed card data:** the frontend checked only the top-level arrays. A
  malformed recommendation could reach card rendering and throw. Nested fields
  and HTTP(S) links are now validated; invalid data produces the existing
  recoverable error and preserves the draft without committing a duplicate turn.
- **Import trust boundary:** runtime dataclass casts did not enforce the node
  kind/fact classifications. Unsupported Student records could reach a writer,
  and flattened attributes could overwrite identity fields. Validation now
  rejects those inputs before writing any shared graph data.
- **Source freshness:** the Neo4j importer writes date strings, but the adapter
  discarded them as naive datetimes. Date-only review values now survive as
  documented UTC-midnight date sentinels; unspecified timestamp zones stay unknown.
- **Graph read behavior:** CourseOffering was excluded by the initial query even
  though the query later tried to read offerings. Offerings are now included;
  course-code spacing is normalized, and pipe-separated imported aliases become
  Neo4j lists while legacy string aliases remain readable.

The graph/frontend owners were notified on their existing PRs before boundary
changes. Shared request/response types and UI design are unchanged.

## Verification

Python regression tests cover CORS preflight and rejected origins, privacy-safe
HTTP errors, import rejection, source dates and existing conversation isolation.
Frontend tests cover malformed cards, safe URLs, retained drafts/retry, API URL
normalization and the existing memory-only lifecycle. CI starts actual backend
and Vite processes, exercises both the frontend proxy and direct CORS requests,
and checks shutdown. An ephemeral Neo4j job verifies real import/query/engine
behavior with public seed or synthetic shared facts only.

## Distinguishing failures

`ERR_CONNECTION_REFUSED` means the browser could not establish a connection. A
CORS response header cannot start a missing listener. The same-origin Vite proxy
uses `/api/chat` without browser cross-origin access; direct port-8000 calls use
CORS. A 503 after a successful connection instead indicates extraction/retrieval
failure. A page that loads then crashes is a frontend issue. These are different
checks, and passing one does not establish the others.

The current agent execution sandbox rejects local socket binding with EPERM and
has rejected escalation. Its process-list access is also restricted, so it cannot
establish the state of a separately launched host terminal process. CI validates
startup on an unrestricted runner; that does not mean a local server is running.
Live Gemini credentials/account controls and a production Neo4j deployment are
not verified by these tests. Existing graph coverage/date-only/prerequisite
limitations remain documented in GRAPH_INTEGRATION.md and PROVIDERS.md.
