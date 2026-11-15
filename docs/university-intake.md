# University-wide intake and shared campus data

Before searching for recommendations, Compass collects these five core answers,
one question at a time:

1. Interests or direction (an explicit “I don't know” is valid).
2. Study stage: whether the student has started at USC and their study level.
3. Program or major, including undecided or unknown.
4. Work, internship, volunteering or project experience, including None.
5. Completed courses, including None or unknown.

An unanswered field has status `not_answered` and value `null`. Explicit `none`
and `unknown` also have null values, but count as answered. They are not evidence
of missing ability. Not having started at USC does not imply no previous coursework.
An answer supplied in the first message skips the corresponding question. A broad
choice such as “Building things” gets one focused refinement; declining that
refinement permits clearly labelled general exploration after the core answers.

The collapsed **What I’m using** panel exposes all core fields and an optional
skills/comfort field. Students can select Not answered, I don't know, None, or write
a sentence. Saving is a typed student correction in the active conversation;
later corrections replace earlier answers. Fixed answers remain relevant when
search interests change. Timing, modality, prerequisites and other request-specific
questions are asked only when material. No career target is compulsory.

When asking about completed courses, Compass can show a few real, sourced course
examples from the shared graph, narrowed by the stated program and study level.
These are memory aids, not an assertion that the student took or was eligible for
them. Nothing is preselected. Only confirmation or a student statement establishes
completion; completion never proves mastery. Students can type all relevant courses,
including courses absent from the graph. Course-history lookup helps answer intake;
recommendation retrieval remains blocked until the core checklist is answered.

The reviewed November 14, 2026 snapshot contains **4,646 courses across 26 schools**
and **2,396 unique calendar events / 3,477 dated occurrences**, including **357
upcoming or ongoing occurrences** as checked. These counts are deliberately distinct:
archived events are not upcoming suggestions. See the generated
[coverage report](../data/seed/university_report.json) for school counts and omissions.

## Public shared-data refresh

Run from the repository root:

```sh
python -m trojan_compass.public_import --term 20263
```

This reads only the official public Schedule of Classes school/subject/course API
and USC Calendar's public Localist API. No AI provider, credentials, student input,
rosters, attendee objects, creator IDs or instructor/contact objects are involved.
The output is a validated ingestion batch in `data/seed/university.json.gz` and an
aggregate report in `data/seed/university_report.json`. The report distinguishes
catalogue courses, unique events, dated occurrences, upcoming occurrences, skipped
records, school coverage and feed failures. Counts describe the snapshot, not all
USC opportunities. The importer refuses to replace the snapshot below its coverage
threshold. The manual GitHub workflow uploads an artifact; automated commits are
restricted to the development feature branch, never the default branch.

The default campus composition loads shared metadata once at startup, then delegates
career/skill queries to the existing KG adapter. It does not import or write any
student information. Production Neo4j remains explicit and never silently falls
back to the local snapshot. The compressed JSON uses the existing ingestion format
and can be passed to the normal shared-data importer after decompression if a graph
administrator chooses to populate Neo4j.

Course catalogue presence does not prove seats, future availability or eligibility.
Raw prerequisite/corequisite/restriction rules remain visible as unverified access
requirements; complex OR rules are not flattened into invented AND prerequisites.
Discipline tags inferred from public metadata are marked inferred in the batch and
disclosed as such. Topic matches do not imply a verified learning outcome or career
requirement. Event occurrences preserve published timestamps and offsets; recurring
parent events cannot reappear as undated alternatives. Archived occurrences are
retained for shared evidence and excluded from upcoming recommendations. All-day
or timezone-naive occurrences are skipped rather than assigned invented times.

Only frontend memory holds the active conversation and editable answers. Each chat
request derives context again, uses local variables, and discards them. No student
database, session store, profile cache, browser storage or content logs are added.
External LLM-provider retention remains separate; consult the existing provider
configuration documentation. Do not claim retention is disabled without verification.

Official public sources:
- [USC Calendar](https://calendar.usc.edu/)
- [Calendar feed guidance](https://calendarhelp.usc.edu/welcome/add-a-feed/)
- [Fall 2026 Schedule of Classes](https://classes.usc.edu/term/20263/catalogue)
- [Registrar course-number guidance](https://esdcomm.usc.edu/arr/glossary/c.html)

## Validation

Default-policy tests cover all five questions, explicit absence, request isolation,
corrections, source-backed course-history examples and expired event exclusion.
Focused legacy orchestration tests inject a static two-field policy to isolate
privacy, failures and graph behavior; they do not invent student facts. Frontend
tests cover collapsed fields, explicit course confirmation and unsafe-source rejection.
Live CI also starts the actual frontend/backend, checks the proxy and CORS, walks
the default checklist, and verifies clean shutdown.
