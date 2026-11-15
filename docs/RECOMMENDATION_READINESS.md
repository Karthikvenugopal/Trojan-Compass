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

## Fixed checklist and changing requirements

The chat encourages sharing **direction/interests** and **skills/experience**.
These fixed checklist fields are always available in the optional editor. They
are not a mandatory full questionnaire: a usable direction can be supplied in the
first message, and no career target is universally required. An explicit absence
of direction is also an answer and permits general exploration.

Extra requirements change with the request: background for level-sensitive
recommendations, availability when schedule fit is requested, format when it
matters, and skill/target clarifications returned by the recommendation engine.
The extractor must cite the student request that makes an extra requirement
necessary. Graph questions determine which prerequisite or target distinction
changes retrieval. An unanswered required field holds back all recommendation
cards. Context discovery before retrieval uses no graph matches as student facts.

The sequence is validate conversation → extract supported facts and answer states
→ apply explicit corrections → check minimum answers → ask one targeted question
or retrieve → resolve any material graph clarification → compose sourced results.
A prior unanswered question can be asked again; turn count is not readiness.
Explicit unknown/none is acknowledged and is not asked repeatedly. If direction
is unavailable, results say they are **general starting points, not personalized
matches**. Other unavailable required details appear in limitations; no fit or
eligibility is asserted for those details. If retrieval finds no supported matches,
say so without claiming USC has no relevant opportunities.

Collecting an answer is not proof that every preference was verified. The current
engine does not automatically match personal availability or event-format
preferences; responses explicitly disclose those limits when applicable. Course
prerequisites and course-format preferences still use the existing engine checks.

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
