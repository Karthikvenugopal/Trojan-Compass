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
retried or sent to another provider. Normal ask turns use planning plus an independent semantic-review call; search
turns use planning plus composition. A review that resolves the last missing fact
can proceed to retrieval/composition in that turn. Bounded validation retries may
add calls; the overall request deadline still applies. Cloud requests are bounded by a 75-second lifecycle;
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

## Preventing repeated ask-backs with AI semantic review

Before an ask-back is returned, a separate focused LLM call reviews the proposed
question against the entire student conversation. It can identify additional facts
in a combined answer, interpret abbreviations and scoped short replies, remove
unsupported proposal facts and choose a different question or proceed to search.
Python applies explicit model edits and validates their evidence; it contains no
new abbreviation map or yes/no-to-profile decision rules. This extra AI call is a
reliability/latency tradeoff, not a claim that a small model cannot make mistakes.

AI-declared asked_field metadata accompanies assistant questions in the active
frontend conversation. Question/reply pairs are rebuilt for each request; metadata
is context, never evidence of student facts. Only actual user quotes support facts.
An extracted typed career target now resolves the target answered-state as well as
broad direction, fixing a bookkeeping omission that permitted repeated goal questions.

Run `bash scripts/check-system.sh --ollama` in the host terminal for an opt-in real
local-model semantic check. It uses a synthetic dialogue (combined academic answer,
career abbreviation, prior volunteering and a scoped negative work reply) and prints
only boolean checks, safe error codes and elapsed time. No student conversation or
raw model reply is printed/saved. Mocked CI tests verify the checks and wiring;
they do not prove that the installed local model passes this semantic evaluation.

## Fixed boundaries versus model decisions

This is a hybrid system, not an unrestricted autonomous career researcher.

| Stage | Current behavior |
| --- | --- |
| Language interpretation and dialogue | LLM extracts facts, interprets short replies, chooses question/order/options and search intent. The live path bypasses legacy scripted short-answer interpretation. |
| Minimum intake | Code and prompts require direction, study stage, program, work experience and completed courses. Provided, explicitly unknown and explicitly absent resolve a field. |
| Career coverage | A curated public dataset supplies 13 occupation baselines and their skills. The LLM chooses among them; it cannot invent another supported baseline. |
| Candidate retrieval | Graph traversal, lexical catalog search, feasibility filters, ranking weights, course-number ordering and candidate limits are deterministic. This limits what the LLM can select. |
| Guide composition | LLM selects supplied occupations/resources/skills, writes the plan and can ask one material follow-up. Code verifies IDs and step references. |
| Course memory aids | Public course records with programmed program/stage matching and ordering. They never establish course completion. |
| UI | Layout, manual edit dropdown states, labels and errors are fixed. Live conversational reply buttons are model-generated; fixed demo/diagnostic modes are separate. |
| Privacy and validity | Fixed request limits, provenance checks, no student persistence, source/ID checks and bounded retries. |

Legacy questionnaire strings still exist for explicitly injected legacy flows and
fixtures; their presence does not mean the current live AI service calls that
question selector. Candidate generation still uses deterministic code, including
the public-data matching inside the evidence guide.

## Composition validation repair

The guide composer gets exact allowed IDs grouped by recommendation, occupation,
skill and action. A fabricated/duplicate ID, unselected step reference, dependency
error, generated URL or repeated question is rejected before publishing. One
same-provider repair receives the original evidence and a static failure category,
not exception text or a logged draft. A second invalid response fails closed.
Retrieval is not repeated; auth, quota, network failures and timeouts are not retried.
The existing overall deadline still bounds the full turn.

Retrieved courses/events with sources and action URLs are projected into plan
resources even when no occupation baseline was selected. This makes the same
evidence available to both cards and plan steps. Actions use short request-local
handles in model input; validated selections and step references are resolved back
to original IDs before returning. This is identifier bookkeeping, not a semantic
match or a student fact. Sources/access checks remain on the original records.
The composer receives the relevant candidate facts without duplicated source URLs
or occupation baselines; original sources are attached to the validated response.

An optional uncertain answer must remain unknown on later turns and must not be
requested again. The LLM owns that semantic classification; there is no new phrase
dictionary. Prompts also tell it to avoid extending minimum intake for optional
preferences and to use plain-language reply buttons instead of internal enums.
