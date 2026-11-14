# Shared graph and campus-data imports

## Setup and import

Python 3.11+ and Neo4j 5.28+ are supported. Install the package with `pip install -e .`, configure `NEO4J_URI`, `NEO4J_USERNAME`, `NEO4J_PASSWORD` and optionally `NEO4J_DATABASE`, then run:

```sh
trojan-compass-import data/seed/usc.json
trojan-compass-import path/to/campus-update.csv
trojan-compass-import path/to/campus-update.json
```

Templates are in `data/templates/import.json` and `data/templates/import.csv`. Importing the same file repeatedly merges on stable IDs and does not create duplicate nodes or evidence edges.

## Fields

JSON top-level arrays are `sources`, `nodes`, and `relationships`. Every source needs a stable `id`, public HTTP(S) `url`, `title`, ISO `checked_at` date, and supporting `excerpt`. Optional `valid_from` and `valid_until` record when a fact applies. Nodes require stable `id`, allowed `kind`, and `name`; optional `status` is `active`, `cancelled`, `postponed`, or `unknown`. Optional `attributes` accepts scalar values only. Use `Course` for the lasting course identity and `CourseOffering` for a specific term/section; offering attributes must include term or dates. Use `Event` for the recurring event and `EventOccurrence` for each dated instance; occurrence attributes must include dates or status.

Relationships require a stable `id`, allowed `kind`, existing `source_id` and `target_id`, `source_record_id`, and the relationship-specific supporting `excerpt`. Mark `fact_type` `explicit` or `inferred`; inferred links remain distinguishable. `HAS_REQUIREMENT` must declare `requirement_type` as `required` or `preferred`; encode scope by attaching the edge to Company, GeneralRole, or Team. `HAS_PREREQUISITE` must mark `prerequisite_type` as `formal` or `helpful`. `FEATURES` is accepted only for explicitly evidenced company/team facts. Unknown values should be omitted or status `unknown`, not guessed.

CSV uses one row per record with `record_type` set to `source`, `node`, or `relationship`; see the template header. Declare source rows before relationship rows. `attributes` is a JSON object cell. Empty optional values are left blank. Updates and corrections retain stable IDs; set an event occurrence's status to `cancelled` or `postponed` and update its dates or registration URL in `attributes`, keeping a fresh source excerpt. Re-import to update the shared record.

## Refresh process and limitations

Use official USC school, department, Career Center, and event pages first. A campus partner should review source pages on a regular cadence (suggested monthly during term and before each registration period), update `checked_at` and applicable dates, and import reviewed changes. The importer does not crawl pages or detect changes automatically. USC pages may change or move, event registration can be restricted to Handshake, and no live enrollment capacity is inferred. `checked_at` is the date the source was reviewed, not a guarantee that availability is current. The `Source.checked_at` API field currently requires a datetime, so date-only seed values use midnight UTC as a date sentinel, not as a claimed review time. Expired occurrences and unknown fields remain visible as stale/unknown; retrieval clients must respect status, dates, source freshness, and evidence.

The seed includes USC CSCI course identities (no invented section/term offering), the Viterbi Expo recurrence and its published February 2027 occurrence, and a BLS occupational skill fact to connect learning to a general career destination. The event source describes several sub-events across Feb 8–10; the occurrence represents this multi-day window, not a claim that every activity runs all three days. Seed sources were reviewed 2026-11-14.

## Personal-data boundary and query logs

This graph stores shared campus/career facts only. It has no Student type or profile endpoint. Do not send student messages, extracted profiles, inferred attributes, personalized recommendations, or user-specific query results to the importer/repository. Karthik extracts context per request and discards it. Peri should pass only canonical destination IDs/names and normalized shared skill/topic IDs to `GraphRepository`; do not pass a full prompt or profile. The adapters do not cache query results and do not log query parameters; Neo4j driver's client logging is disabled.

Deployments must also disable or redact Neo4j server query logging and query parameter capture (including `query.log`, debug logs, APM/tracing, audit plugins, and managed database query logs) so parameters are not retained. Configure server-side query logging at `OFF` or an approved sanitized setting, restrict log access/retention, and verify this with the database operator; client configuration cannot override server/database-side logs. Do not enable parameter logging in application observability.

## Adapter contract

The importer validates a course's explicit `attributes.course_code`; it does not infer an identifier from display text. The actual `GraphRepository` is async and is defined in `trojan_compass.recommendations.graph`. Its methods are `find_destinations`, `get_destination`, `suggest_directions`, `requirements_for`, `actions_for_skills`, `actions_for_topics`, and `find_courses`. Return values use its Pydantic `Destination`, `Requirement`, and `CampusAction` models, plus Karthik's shared `Source` model. `FakeGraphRepository` implements that same protocol. Database drivers and Cypher remain inside `Neo4jGraphRepository`.

See [Graph integration and contract mismatches](GRAPH_INTEGRATION.md) before wiring the recommendation and chat services. Karthik's API accepts a `RecommendationService` in `create_app`; it does not accept a raw `GraphRepository`. Source checked dates in this dataset are date-only and are normalized to UTC midnight for the shared `Source.checked_at` datetime field; that time component is a date sentinel, not a recorded review time.

Run checks with `pytest` and `mypy --strict`.
