# Recommendation engine

Owner: Peri. Package: `src/trojan_compass/recommendations/`.

The engine turns one request's student context into a short list of courses and events.
Each item is sourced, checked for feasibility, and comes with a reason, sources and an
evidence path. It consumes Karthik's contracts from `trojan_compass.contracts` and doesn't
redefine any of them.

## Wiring (Karthik)

```python
from trojan_compass.recommendations import RecommendationEngine

engine = RecommendationEngine(repository=graph_adapter)   # optional: clock=, policy=
app = create_app(recommendations=engine)
```

- Signature: `async def recommend(request: RecommendationRequest) -> RecommendationResult`.
  This matches the async proposal in `docs/INTEGRATION.md`. The engine is native async, so
  no `asyncio.to_thread` is needed.
- The prompt calls the per-request input `RetrievalContext`. The current contracts carry it
  as `RecommendationRequest.profile` plus `user_query`, so the engine uses those and
  doesn't add a duplicate model. If a separate `RetrievalContext` contract lands, only
  `service.py` needs a one-line change.
- One engine instance can be shared across requests and sessions (see Data handling below).
- Clarification paths use the agreed format: `target`, `interests`, `skills.<slug>`.

## Graph boundary (Abishek)

`graph.py` defines the proposed `GraphRepository` protocol and the typed, read-only models
it returns: `Destination`, `Requirement`, `CampusAction`, `CourseInfo`, `EventInfo`,
`SkillNode` and `DirectionSuggestion`. The adapter converts query results into these
models. Cypher/SPARQL, driver records and node handles stay inside the adapter.

| Method | Returns |
| --- | --- |
| `find_destinations(name, kind?, company?)` | name/alias matches, case-insensitive |
| `get_destination(id)` | one destination or `None` |
| `suggest_directions(interests, limit)` | destinations linked to interests via topics |
| `requirements_for(destination_id)` | requirements declared on that node only (no inheritance) |
| `actions_for_skills(skill_ids)` / `actions_for_topics(topics)` | courses and events |
| `find_courses(codes_or_titles)` | courses, used to read completed coursework |

Data rules the engine relies on:
- Every `Requirement` must have at least one source.
- All datetimes need a UTC offset.
- `offered_terms=None` means unknown; `[]` means no upcoming offering is listed.
- `eligibility=None` means not published.
- Teams point to their general role through `base_role_id`.

`InMemoryGraphRepository` (in `fake_repository.py`) stands in for the real graph until the
adapter is ready. `synthetic_graph.py` holds clearly fake fixture data: SYN course codes,
fictional companies and example.org URLs. None of it should be shown as real USC data.

## Frontend notes (Riddhi)

Each `Recommendation` fills `why_relevant`, `benefits`, `prerequisites_or_access`,
`unknowns`, `sources` and `evidence_path`. `evidence_path` reads as a chain, for example
`Perception team at Nimbus Robotics (team-specific) → requires Computer vision → practiced at
Computer Vision Workshop`. There are no scores or match percentages to display.
`limitations` explains anything that was skipped, such as "Skipped Robotics Build Night:
the organizer cancelled it."

## Pipeline

| Step | Module | Key rules |
| --- | --- | --- |
| Resolve direction | `destination.py` | Company, role and team targets plus aliases. An ambiguous name gets one question while interests still produce provisional results. With no target, interests map to grounded directions, and with no interests the engine asks one plain question. No job title is required. |
| Analyze preparation | `preparation.py` | Statuses are known, learning, not_yet_learned and unknown. **Unknown is never a gap.** Completed courses count as *exposure* only. Team-specific and role-baseline requirements are kept separate. |
| Retrieve | `retrieval.py` | Requirement skill → course/event, interest topic → course/event, and prerequisite bridges (a blocked course → an action that teaches its missing prerequisite). |
| Feasibility | `feasibility.py` | Cancelled, postponed, past and registration-closed events are excluded. Courses are excluded only on recorded evidence: a prerequisite the student said they haven't learned, no listed offering, or every listed term closed. Anything else unknown is labeled, never assumed. Dates come from an injectable `Clock`. |
| Rank | `ranking.py` | Small integer weights in `RankingPolicy`: relevance + learning benefit + readiness + feasibility + freshness + requested kind. Courses and events are mixed only when the other kind scores within a set margin. Scores are never returned. |
| Explain | `explain.py` | Courses *teach*. Events offer practice, exposure or networking and state that attendance isn't proficiency and networking isn't a job guarantee. |

## Data handling

- The engine keeps only collaborators and configuration on the instance. Student-derived
  data lives only in local variables during `recommend`.
- No caches, persistence, logging or graph writes. A test checks that the engine's
  attributes are unchanged after concurrent requests and that nothing is logged.
- Every request is computed from scratch, so a corrected skill or an updated graph record
  shows up on the next call.

## How results change (each has a test)

| Change | Result |
| --- | --- |
| Student says Python is known instead of not yet learned | The intro Python course drops out: it would teach nothing new. |
| Goal changes from SWE to Robotics Engineer | A different set, with evidence paths through the new role. |
| An event record becomes cancelled | The event is removed and the limitations say why. |
| A prerequisite is known to be unmet | The blocked course is skipped with a reason, and the course that teaches the prerequisite is shown with the path `requirement → blocked course → prerequisite → this course`. |

## Limitations

- The fixture data is synthetic. Real USC courses and events depend on Abishek's adapter.
- Course restrictions (major, D-clearance) are shown and labeled unknown, not evaluated
  against `program`.
- `constraints.time_window` is free text and isn't parsed yet. Course modality is compared
  with `constraints.modality` by exact text.
- `user_query` is only used to detect a request for courses or events.

## Checks run

```
ruff check src/trojan_compass/recommendations tests   # passes
ruff format --check src/trojan_compass/recommendations tests
mypy                                                   # strict, no issues (15 files)
pytest                                                 # 33 passed
```

`ruff check src` also reports one E501 line in `contracts/__init__.py`. That line is
Karthik's and was left untouched.
