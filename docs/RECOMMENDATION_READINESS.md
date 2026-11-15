# Recommendation readiness and editable information

The previous broad fallback could show cards after a course/event keyword or an
unanswered repeated question. Chat now checks explicit answer states instead.
All student-information values initially have value `None` (`null` in JSON).

| State | Value | Meaning |
| --- | --- | --- |
| `not_answered` | `None` | No supported answer; ask if the current search needs it. |
| `unknown` | `None` | Student explicitly does not know, cannot provide or declines the information. |
| `none` | `None` | Student explicitly reports absence or no preference. |
| `provided` | A sentence | Student supplied usable information. |

**Enough information includes knowing that there is nothing to provide.** Unknown
and none count as answered; they do not establish interests, skill gaps or mastery.
An assistant question alone never establishes an answer. An unconfirmed skill
remains unanswered until the student acknowledges uncertainty or supplies a status.
Completed courses never prove mastery.

## Minimum questions before any recommendation search

There are five fixed information requirements, not a forced number of turns:

| Requirement | Question | Complete when |
| --- | --- | --- |
| Area to explore | What interests you, or what would you like to explore? | A concrete area, or explicit unknown/none. |
| Study stage | Have you started at USC yet, and what level are you studying? | A supported answer, or explicit unknown/none. |
| Program/major | What program or major are you studying or considering? | A supported answer, undecided, or explicit unknown/none. |
| Experience | What work, internship, volunteer or project experience do you have? | Supported statements, or explicit unknown/none. |
| Completed courses | Which courses have you already completed? | Student-confirmed coursework, or explicit unknown/none. |

“Building things” is a useful broad preference, not yet a searchable domain. Ask
“What kind of things would you enjoy building?” with choices such as programming
(apps/websites), physical objects/design, or unknown. Record `direction_detail`
separately; do not invent a software career or programming ability from a broad
choice. A concrete answer resolves this refinement. Explicit inability to narrow
it also counts as answered and permits labeled general starting points.

Ask one concrete question at a time, skip answers already present, and collect
all five core answers before calling RecommendationService. If they are answered
in the first message, search immediately. Never repeatedly say “not enough info.”
Tell the student which question comes next instead.

Request-specific dates or format are asked after the fixed minimum only when the
request depends on them. Actual graph prerequisites/target distinctions can require
one further clarification before cards are returned. A previous unanswered question
is not an answer. Unknown/none is acknowledged and not repeatedly requested.

The sequence is validate → extract → apply corrections → collect area/refinement
and the other core answers → collect required request constraints → search → resolve any
material graph clarification → compose sourced results. All values are request-local.

## Grounded exploration and missing coverage

An interest search can match a sourced skill relation even if the graph has no
separate Topic node for it. Chat composition reuses the existing engine, feasibility,
ranking and card builder, then names the actual skill relation in the evidence path.
No graph edges, career goals, skill gaps or mastery are invented. Completed courses,
known skills and recorded access constraints still apply. A bounded supplemental
lookup examines up to 30,000 shared action records; primary engine queries are unchanged.

If there is no verified match after collecting the minimum answers, explain that
the **current data** lacks a match. Return a concise response and actionable sourced
areas instead of treating it as missing student information. Supplemental options
come from non-excluded records, with completed courses/known skill topics filtered.
There is no duplicate “answer the question above” placeholder.

Collecting answers is not proof every preference was verified. The current engine
does not automatically match personal availability or event-format preferences;
responses disclose those limits when applicable. Existing course prerequisite
and format checks are reused. General suggestions remain labeled as such.

## Optional editor

**What I’m using** is collapsed by default. Expanding it shows core checklist fields,
current request-specific questions, answer states and short extracted sentences.
Each dropdown has three fixed choices—Not answered, I don’t know, None—and a fourth
**Write an answer** choice with a text area. Save submits an explicit student edit
and refreshes the response. Not answered clears that field and restores its ask-back
if needed. Corrections replace older facts; later natural-language corrections can
replace an earlier edit. Display summaries are bounded to 1,000 characters; full
extracted facts and the supplied conversation remain available to retrieval.

A typed edit is part of a user message, never an assistant message. It is validated
and sent again in the active conversation. An edit is data, not executable code.
Failed saves can be retried with the edit intact; failed or late responses do not
replace accepted information. Ending or resetting chat clears editor state too.

## Privacy and validation

All values, answer states and evidence are rebuilt within each request. The backend
retains no student state; only frontend memory holds the active conversation and
editor. No database, file, browser storage, profile logs or provider threads are used
for student information. [External provider retention remains separate](PROVIDERS.md).

Shared Pydantic contracts publish `StudentAnswer`, `ContextRequirement`,
`InformationEdit`, `InformationSnapshot` and the additive `ChatResponse.information`
field. Existing recommendations and graph interfaces are unchanged. Examples:
[initial response](examples/chat_response.json) and [edit request](examples/information_edit_request.json).
Tests cover unanswered versus explicit absence, request-specific gates, prerequisites,
corrections and resets, assistant evidence rejection, isolation, safe failures,
collapsed editing, retry, response validation and clearing without browser storage.

See [university intake and public data](university-intake.md) for sourced course-history
examples, public refresh commands, coverage reporting and dataset limitations.
