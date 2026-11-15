# Career guidance and optional background imports

Compass now builds a working career plan instead of ending at course results.
The five-field minimum intake stays in place. A student may answer manually or
review imported background to supply multiple facts together. Unknown and None
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

The original POC excluded ingestion. The expanded scope explicitly permits **resume
PDF/DOCX and pasted LinkedIn text or PDF exports**, with review before use. LinkedIn
URLs, authenticated scraping and account credentials are not supported.

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
structure, so the result is always editable. The PDF parser is `pypdf`; hardened XML
parsing uses `defusedxml`.

The review UI holds the text in component memory. Closing it, ending/resetting chat,
or refreshing clears it and aborts an active upload. **Use this reviewed background**
adds only the student's confirmed text as a normal user message. The 4,000-character
chat-message cap includes its introduction; excessive text requires an explicit edit,
not automatic deletion of earlier facts or constraints. Normal context extraction
then identifies supported facts and asks only for missing required answers.

Parsing calls no LLM. Confirming background sends it in the normal active conversation
to the configured provider. [External provider retention](PROVIDERS.md) remains separate;
no claim is made that it is disabled. No provider threads or application student store
are introduced.

## Setup and validation

Install updated dependencies with `pip install -e .` and restart `bash scripts/dev.sh`.
The launcher checks for the parser dependencies. The wheel includes shared career data.

Tests cover unknown versus confirmed gaps, explicit assessments and corrections,
request isolation, unsupported company targets, source-backed non-CS paths, research
eligibility labels, the full HTTP roadmap flow, DOCX/PDF parsing, oversized/malformed
uploads, XML entities/archive expansion, cancellation cleanup, response privacy,
review confirmation, draft clearing and unsafe evidence URLs. All test student data
is synthetic. Full CI installs `pypdf` and runs the real PDF-reader test.
