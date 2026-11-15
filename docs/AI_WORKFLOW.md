# AI-led Trojan Compass

Live campus/production chat now uses `AIChatService`. Every turn, including greetings,
buttons, program abbreviations and course confirmations, invokes the configured AI.
There is no local questionnaire bypass, keyword-selected occupation or canned career
fallback in this path. Demo/diagnostic modes remain explicitly offline fixtures.
The older `ChatService` is retained for explicitly injected compatibility tests; AI
failure never selects it. Default application composition is tested separately.

## Request lifecycle

1. Validate the active frontend conversation and its byte/character limits.
2. Make a structured AI decision from the complete indexed conversation. The model
   emits compact, quoted student facts, applies corrections, chooses one useful next question
   or search, writes semantic retrieval terms and selects possible occupation IDs
   from the shared public evidence catalog. It chooses the order and wording of
   questions, handles uncertain students and skips discovery when facts are supplied.
3. Check quotation provenance, typed corrections and readiness. The student's fixed
   minimum checklist remains direction, study stage, program, experience and completed
   courses. Provided/unknown/none all count as answered; not_answered does not. The
   model chooses additional material fields. A career target cannot become mandatory.
   Code rejects early searches and repeated questions; it does not choose the question.
4. Ask turns return the AI's question/choices. Search turns call the existing owners'
   typed, read-only recommendation/graph/catalog interfaces. Model-selected occupation
   scopes retrieve source-backed skills, learning, teaching faculty and research
   pathways. A proposed occupation is never written into student context as a goal.
5. A second structured AI call chooses/ranks supported resources and writes the
   explanation, comparisons and ordered next steps. Code checks every selected ID,
   action/skill/step reference and question field. Titles, URLs, sources, prerequisites,
   availability and self-reported skill statuses come from validated evidence, not
   generated identifiers or invented openings. Unknown skills remain unknown.
6. Return the existing ChatResponse; discard request-local objects. All active history,
   document background, edits and plans remain in frontend memory only.

Direct factual campus questions use the same AI decision followed by the existing
source-constrained AI campus answer. They do not require career intake first.

## What the AI controls

Interpretation of natural answers/documents; question selection, order and prose;
semantic search terms; relevant occupation selection; resource selection/ranking;
explanations, comparisons and the working roadmap. The thirteen reviewed occupation
baselines are an evidence catalog, not a set of scripted outcomes. Unsupported
occupations are a coverage limitation, not permission to substitute unrelated ones.

Code remains responsible for privacy, request validation, readiness/evidence checks,
read-only data access, source IDs, eligibility filters, cancellation and deadlines.
Internal evidence builders may construct candidate metadata; their canned headings,
steps and fallback suggestions are not published by AIChatService.

## Reliability and limits

An invalid planning decision may get one same-provider validation repair using the
original conversation and static feedback. Auth/quota/connection/timeouts are not
retried or sent to another provider. Normal ask/search turns use one/two model calls;
a planning repair adds one. Cloud requests are bounded by a 75-second lifecycle;
local Ollama requests have a 180-second lifecycle to allow local inference. A provider
or validation failure returns a safe error, never a scripted imitation of AI advice.

Source IDs and quotation provenance are checked mechanically. Semantic accuracy and
relevance still depend on the model; mocked tests cannot establish live model quality.
The catalog/KG is incomplete and snapshots can be stale. Faculty teaching association
does not prove research fit or mentorship availability. Research routes are not open
positions. Degree, licensure and access requirements need separate verification.

## Local Ollama

Use an installed **local** model with structured JSON support:

```dotenv
COMPASS_MODE=campus
LLM_PROVIDER=ollama
OLLAMA_MODEL=qwen3:4b
OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_CONTEXT_LENGTH=32768
```

The native `/api/chat` adapter sends JSON Schema, disables streaming, requests no
thinking output for Qwen3 and uses no API key, provider thread, conversation handle or
cloud fallback. It accepts only loopback HTTP endpoints, rejects cloud-tagged models,
and never pulls models automatically. Before sending conversation content it checks
public model metadata, rejecting remote/cloud aliases and advertised context windows
smaller than the requested budget. `keep_alive=0` requests unloading after each
call; the isolation tradeoff is additional loading latency. It uses a conservative
UTF-8 budget (for Qwen byte tokenization) and rejects excess input explicitly rather
than silently dropping earlier constraints. Large background/evidence requests can
exceed this local budget even when they fit the HTTP request limit. Increase context
only within the installed model's supported window and available memory.

Local inference avoids the selected cloud LLM API, but does not mean the whole app is
offline: LinkedIn/public campus lookups still use their documented sources. Ollama's
own cloud settings, logs and OS memory/swap are separate; this project has not audited
or configured them. For daemon-level local-only operation set `OLLAMA_NO_CLOUD=1` in
**Ollama's environment** and restart Ollama, or use its documented server setting.
Setting this only in the backend's `.env` does not reconfigure an already-running
daemon. Do not enable prompt/debug capture. No zero-retention guarantee is claimed.

Ollama is already installed/running on the development Mac and `qwen3:4b` is present.
Live inference speed/quality is not verified from the restricted agent environment.
Small local models can be slower or less reliable; test with synthetic conversations.
Restart `bash scripts/dev.sh` after changing provider settings.

Official references checked 2026-11-15:
- https://docs.ollama.com/capabilities/structured-outputs
- https://docs.ollama.com/api/chat
- https://docs.ollama.com/faq
- https://ollama.com/library/qwen3

## Local planner contract and latency fix

The planner now emits a flat list of evidenced facts and one question/action instead
of a full nested profile with empty values. Unasked fields are omitted and initialized
as not_answered/null by the domain layer. Explicit unknown/none facts still cite a
student statement; their wire value is ordinary text that maps to domain null. This
removes conditional status/value combinations that JSON Schema allowed but Python
validators rejected. The compatibility decision model also normalizes non-provided
values before nested validation. A regression test reproduces the former rejection
through the native Ollama transport.

The planner prompt and occupation index are roughly two-thirds smaller, and its
output schema is 2.4 KB instead of 6.7 KB. The local adapter requests a context window
sized to each actual prompt plus a conservative template/output reserve, bounded by
OLLAMA_CONTEXT_LENGTH and the model's advertised maximum. A short greeting no longer
requires a 32K KV allocation. No student history is truncated. keep_alive=0 remains
unchanged; avoiding retained prompt state still incurs model-loading overhead.
These are measured request-size reductions, not verified live latency claims.

Policy errors (such as a premature search or repeating an answered question) now use
an invalid-next-step error with a static check code. The repair receives the exact
rule and unanswered field names, not just 'invalid schema'. No student values or raw
model output appear in errors/logs. Provenance is checked before applying ordered
fact corrections, so output ordering or a repairable index mistake cannot reinstate
an old program value.
