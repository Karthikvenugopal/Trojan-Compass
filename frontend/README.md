# Trojan Compass frontend

React + strict TypeScript frontend for the stateless Trojan Compass chat API.

## Run the frontend

```sh
cd frontend
cp .env.example .env.local
npm install
npm run dev
```

The copied example configuration uses the actual backend API. Run the backend from the repository root (`uvicorn trojan_compass.api:app_from_environment --factory --no-access-log`), using the mode configuration in the root README. `frontend/.env.local` should contain:

```dotenv
VITE_USE_MOCK_API=false
VITE_API_BASE_URL=
```

For explicitly labeled frontend-only synthetic fixtures, set `VITE_USE_MOCK_API=true`. Without a copied environment file the existing adapter still defaults to mock mode. Never put provider or database credentials in frontend variables.

The Vite development server proxies same-origin `/api` requests to `127.0.0.1:8000`, so the browser does not need cross-origin access. Restart Vite after changing environment variables.

## Shared API contract

The real adapter sends the full active transcript on every request:

```http
POST /api/chat
Content-Type: application/json
```

```json
{
  "messages": [
    { "role": "user", "content": "I'm interested in public health." },
    { "role": "assistant", "content": "What part of public health interests you?" },
    { "role": "user", "content": "I like data and community work." }
  ]
}
```

The request and response interfaces match `src/trojan_compass/contracts/__init__.py`. Recommendation cards render the current fields in `src/trojan_compass/contracts/__init__.py`: `kind`, `title`, `summary`, `why_relevant`, `benefits`, `prerequisites_or_access`, `unknowns`, `action_url`, `sources`, `evidence_path`, `event`, `course`, `modality`, and `status`. `ChatResponse` renders `message`, `suggested_replies`, `recommendations`, and `limitations`. The frontend displays only supplied dates, access details, status, sources, and links.

**Contract mapping gap:** the shared model has no separate event `benefit_type` or `registration_url`. The UI uses the shared `benefits` list for event benefits and `action_url` for an event or registration action. If downstream services need these to remain distinct, Karthik should add agreed fields to the shared Pydantic model and schema; the frontend does not invent them. The default backend demo has a fixed course example. `COMPASS_MODE=campus` connects OpenAI extraction, the recommendation engine and the reviewed USC seed; `production` connects Neo4j. Empty results remain valid when graph coverage is insufficient. See the root README for configuration and limitations.

The backend accepts 1–64 messages, up to 4,000 characters per message, 24,000 total characters, and 65,536 serialized request bytes. The frontend checks these bounds before sending and offers a fresh start instead of truncating. It handles the backend's sanitized `{"error":{"code":"conversation_too_large","message":"…"}}` (413), `invalid_conversation` (422), and `chat_unavailable` (503) responses. The current API does not configure CORS: use the Vite same-origin proxy locally and route `/api` through the same origin in production, or have the backend owner configure the required CORS origins.

## Conversation lifecycle and privacy

There is no session identifier, profile object, or browser persistence. Conversation, draft, recommendations, and active request live only in React state/refs. Each successful user and assistant turn is appended in memory. A failed user turn remains in the composer and is not added to history until a retry succeeds, preventing duplicate turns. **End chat** aborts the active request and clears the transcript, recommendations, draft, and pending state; late replies from the cleared request are ignored. Refreshing clears the page memory. The UI does not claim to control external model-provider retention.

No analytics or error-reporting hooks are installed. Message text is not written to localStorage, sessionStorage, IndexedDB, cookies, URL parameters, service-worker caches, or logs.

## Checks

```sh
npm test
npm run build
```

Vitest covers keyboard submission, suggested replies, cards and evidence disclosure, preserved drafts/retry without duplicate turns, abort/late-response behavior, oversized requests, end-chat clearing, and no browser storage writes.

## Team ownership

- **Karthik:** stateless API, contracts, and chat orchestration.
- **Abishek:** knowledge graph and USC source data.
- **Peri:** recommendation service, matching, and evidence.
- **Frontend:** onboarding, conversation, suggested replies, cards, source disclosures, and recoverable errors.
