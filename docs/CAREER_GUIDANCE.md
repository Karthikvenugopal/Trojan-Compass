# Career guidance and optional background imports

Compass now builds a working career plan instead of ending at course results.
The five-field minimum intake stays in place. A student may answer manually or
add background directly to supply multiple facts together. Unknown and None
remain valid answers. Student state exists only in frontend memory and per-request
local variables; refresh, Start over or End chat clears it.

## Student journey

1. **Explore or choose a direction.** Undecided students compare sourced occupations;
   choosing a suggestion is an explicit student action. A clear goal skips this choice.
2. **Assess preparation.** The guide separates self-reported strengths, learning,
   explicitly not-yet-learned skills and unassessed skills. Unknown never means missing.
   One useful skill check appears at a time; a complete questionnaire is not required.
3. **Choose actions.** Skill priorities connect to source-text course matches,
   instructors listed for those courses, research program pathways and campus events.
4. **Sequence the work.** Review the baseline, choose a starting level, apply learning
   through people/research, then produce a small artifact and get feedback. Exercises
   are proposed coaching steps, not claims about university program requirements.
5. **Revise.** Student corrections and new self-assessments rebuild the plan from the
   active conversation. Completing a course or project does not automatically prove
   mastery. There is no saved progress tracker or invented readiness percentage.

## Evidence boundaries

The existing KG's scoped company/role/team requirements remain authoritative when
available. `data/seed/career_paths.json` supplements coverage with thirteen reviewed
occupation baselines from O*NET/BLS across science, engineering, business, social
research, communication, arts, music and architecture. These are not employer hiring
requirements. Unsupported targets are acknowledged instead of assigned invented gaps.
Licensed professions, degree requirements and professional eligibility need separate
advisor review. This is an initial set of baselines, not universal career coverage.

Course matching uses public descriptions and actual recorded prerequisites. A
keyword association is a learning candidate, not a new verified TEACHES edge. Known
prerequisite blocks and completed-course aliases are respected; enrollment and access
still need checking. Course completion records exposure only.

Faculty/instructor cards verify a teaching connection in a dated Schedule of Classes
snapshot. They do not establish professorial rank, current office hours, research
alignment, or availability to supervise students. Research cards link verified USC
program pathways with eligibility checks. They are explicitly **availability unknown**,
not confirmed open jobs, lab positions, funding awards, or invitations. The initial
pathways include USC student research, Dornsife SOAR, Viterbi CURVE, Annenberg research
and USC arts/humanities research routes. No outreach messages are sent automatically.

## Resume and LinkedIn inputs

The expanded scope accepts resume PDF/DOCX, public LinkedIn URLs, PDF exports and
pasted background. Uploading uses the document directly: there is no extracted-text
preview or mandatory review step. The conversation shows a compact background-added
message. Students can correct the resulting facts in the collapsed “What I’m using”
section, or send a correction normally.

`POST /api/import-linkedin` accepts a public `https://www.linkedin.com/in/name` URL
in its JSON body. A fresh, bounded request reads public structured profile text only.
It never logs in, sends cookies, follows redirects, bypasses restrictions or caches
profiles. LinkedIn often blocks automated access or exposes only a limited snippet;
missing public data is not inferred. Blocked, oversized or unreadable pages ask the
student to upload a profile PDF or paste background. The URL importer cannot promise
complete LinkedIn coverage or verify that a profile belongs to the student.

`POST /api/import-document?format=pdf|docx` accepts raw document bytes, never a server
filename. The privacy boundary caps the actual stream at 4 MiB. A fixed trusted worker
reads stdin and returns text through a pipe; there are no upload spools, temporary
files, profile files, document logs or provider calls. The worker receives no provider
credentials. DOCX archive expansion and XML entities are bounded/rejected. PDF input
is capped at 20 pages. Text beyond 20,000 characters, encrypted documents and empty
extractions are rejected, never silently truncated. Scanned images require the student
to paste text; OCR is not included.

The parser has an 8-second CPU limit, a 12-second parent timeout, a Linux address-space
limit, and disabled core dumps. Timeout/cancellation kills and awaits the worker.
POSIX environments (macOS/Linux) are supported. Parsing complex PDF layouts can lose
structure. Extracted facts can be corrected in the information panel. The reader uses `pypdf`; XML
parsing uses `defusedxml`.

File reading stays internal. The full text becomes a normal student message in the
active frontend conversation, so every subsequent request can derive the background
again. The imported-message cap is 20,400 characters including its short introduction;
ordinary messages remain capped at 4,000. The total 24,000-character / 65,536-byte
conversation cap still applies. Oversized input is rejected explicitly without
truncating earlier corrections or constraints. Ending/resetting chat or refreshing
clears background; closing an in-progress import aborts it. No backend copy persists.

Adding background sends its text with the active conversation to the configured AI
provider. [External provider retention](PROVIDERS.md) remains separate; no claim is
made that it is disabled. No provider threads or application student store are added.
Coursework and job descriptions do not automatically establish skill mastery or a
current career target. Other missing required facts are still asked one at a time.

## Setup and validation

Install updated dependencies with `pip install -e .` and restart `bash scripts/dev.sh`.
The launcher checks for the parser dependencies. The wheel includes shared career data.

Tests cover unknown versus confirmed gaps, explicit assessments and corrections,
request isolation, unsupported company targets, source-backed non-CS paths, research
eligibility labels, the full HTTP roadmap flow, DOCX/PDF parsing, oversized/malformed
uploads, XML entities/archive expansion, cancellation cleanup, response privacy,
direct imports, public-profile access failures, SSRF boundaries, clearing and unsafe evidence URLs. All test student data
is synthetic. Full CI installs `pypdf` and runs the real PDF-reader test.

## Intake reliability

Recognized UI choices and explicit panel edits are re-derived from the entire active
conversation without a provider call. This supplies only student-selected facts,
never fixture recommendations. If any turn requires free-form interpretation, the
entire conversation goes through the validated extractor, preserving corrections and
constraints. Retrieval still waits for the minimum checklist. Free-form provider
failures return safe categories (authentication, quota, rate limit, connection,
timeout, configuration or invalid output) rather than a repeated generic error.
These classifications reveal no student text or raw provider response.

## Extraction validation repair

Provider input includes explicit original message indices. Exact student quotations
may repair an index only when they match one student turn unambiguously; assistant
suggestions and elided negations cannot establish evidence. Duplicate snapshots use
the latest supported field, while conflicting same-turn values fail closed. No
relevant constraints are dropped. Non-answered fields carry no evidence.

Invalid structured output gets at most one same-provider re-extraction, with static
feedback and a larger output budget. It still passes every schema and provenance
check, under the request deadline. There is no retry of credentials, quota or network
failures, no cross-provider fallback and no application persistence. See the provider
retention and usage implications in [PROVIDERS.md](PROVIDERS.md). Remaining failures
identify structure, evidence, conflicts, truncation or refusal without student content.

The dev launcher watches backend source changes. An already-running server must be
restarted once to enable this; later Python changes reload automatically. Environment
configuration changes still require restarting the launcher.
