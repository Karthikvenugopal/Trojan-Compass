# Extraction providers and external data handling

For the current AI-led workflow and local Ollama option, see [AI_WORKFLOW.md](AI_WORKFLOW.md).
`LLM_PROVIDER=ollama` selects native local structured generation without cloud credentials
or automatic cloud fallback. Every live conversation turn invokes the chosen provider.
Local daemon logging/retention is separate; it has not been audited or reconfigured.


Provider selection is server-side and does not change `POST /api/chat`, the
frontend, retrieval contracts or the student-data lifecycle. No provider choice
creates a session/profile repository. Each call re-derives context from the
frontend's active conversation; the result remains request-local.

Set these variables in your server environment (the reference `.env.example`
is not automatically loaded):

```dotenv
COMPASS_MODE=campus
LLM_PROVIDER=gemini
GEMINI_API_KEY=<server-managed secret>
GEMINI_MODEL=<plain model ID supporting generateContent and structured JSON output>
```

Use `COMPASS_MODE=production` plus the Neo4j configuration for a database-backed
graph. Demo mode is offline regardless of provider selection. Gemini requires no
new package: the native HTTPS implementation uses the existing `httpx` dependency.
For OpenAI use `LLM_PROVIDER=openai` (the default), `OPENAI_API_KEY`, `OPENAI_MODEL`.
Invalid providers or missing selected-provider credentials fail startup; there is
no fallback that sends student content to another provider.

The Gemini extractor uses a standalone `generateContent` call with the shared
Pydantic JSON Schema. The full conversation is encoded as untrusted user data;
the extraction rules remain in system instructions. Only user quotations can
support facts. Local Pydantic validation still enforces schema keywords that the
provider may not constrain. Blocked/truncated/malformed responses or invalid
provenance are validated locally. Exact quotes with a uniquely identifiable student
source may have a miscounted index repaired. Repeated fields are reduced to their
latest supported evidence; same-turn conflicts, ambiguous quotations and assistant-only
claims are rejected. Unanswered fields carry no facts or evidence. HTTP and connection
failures use safe actionable categories without raw provider content. Thinking parts
are ignored; tool outputs are not accepted. The API key is sent in a header, not
the URL. No Interactions/chat sessions, previous-response IDs, explicit context
caching, search grounding, tools, model-generated code, prompt logging or transport retries
are configured. For invalid extraction output only, one additional call to the same
provider re-extracts the complete indexed conversation with static validation feedback.
No exception payload or prior invalid output is replayed. The second output must pass
all checks; there is no provider failover. Authentication, quota, network failures and
refusals are not retried. The chat request has a 65-second overall deadline, enough for both bounded
25-second extraction attempts plus retrieval. Optional intent routing is capped at
3 seconds and falls back to intake. Simple program answers (including CS) and
explicit course-picker confirmations are handled without a provider call; unsupported
turns still send the entire conversation for extraction.
A validation repair can increase provider usage and sends the conversation twice.

## Provider retention is separate from application persistence

The application does not save student data. This does **not** establish zero
provider retention, prevent provider abuse logging, or control account settings.

Google's [unpaid-service terms](https://ai.google.dev/gemini-api/terms) allow submitted content and responses to be used
for product/model improvement and human review, and prohibit sending personal,
sensitive or confidential information. Paid-service data-use terms differ; paid
service does not itself establish zero retention. [Google documents](https://ai.google.dev/gemini-api/docs/zdr) limited abuse
logging and default implicit in-memory caching. This adapter does not configure
those account controls or disable implicit caching. **Use synthetic conversations
for free-tier demonstrations; verify an appropriate paid-service configuration
and provider terms before real student use.** No Google retention settings have
been verified or changed by this project.

OpenAI calls set `store=false`; that does not disable all external retention.
No OpenAI zero-retention account controls have been verified or configured either.
Provider changes require reviewing the relevant account's settings. Do not put
credentials in `VITE_*` variables or copy student content into observability tools.

References checked 2026-11-14:

- [Gemini generateContent API](https://ai.google.dev/api/generate-content)
- [Gemini structured output](https://ai.google.dev/gemini-api/docs/structured-output)
- [Gemini data-use terms](https://ai.google.dev/gemini-api/terms)
- [Gemini retention and caching](https://ai.google.dev/gemini-api/docs/zdr)
- [OpenAI data controls](https://developers.openai.com/api/docs/guides/your-data)

Tests use mocked HTTP and synthetic conversations; no live Gemini call or account
retention verification is claimed.

## Campus questions

Campus mode routes factual questions using the same configured provider. A direct
campus answer uses a second structured call with request-local evidence; a
free-form recommendation turn routes first and then extracts context. Fully recognized
guided intake choices are re-derived locally from the conversation without a model call. Each call is awaited
within the request lifecycle; cancellation leaves no background extraction task.
Typed edits and ordinary checklist answers bypass routing. No provider-managed
threads or student caches are used. OpenAI calls use `store=false`; this does not
claim that provider retention is disabled. Public library HTML may be cached for
10 minutes; it contains no student request information. Empty evidence or no valid
citation yields a static unavailable response. Deadline answers must respect the
published term/year and ask when it is ambiguous.
