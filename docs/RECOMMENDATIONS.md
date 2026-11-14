# Recommendation engine

Owner: Peri. Package: `src/trojan_compass/recommendations/`.

The engine turns one request's `RetrievalContext` into a short list of courses and events.
Each item is sourced, checked for feasibility, and comes with a reason, sources and an
evidence path. It consumes the **v2** contracts in `trojan_compass.contracts` and doesn't
redefine any of them.

## Wiring

```python
from trojan_compass.api import configured_extractor, create_app
from trojan_compass.recommendations import RecommendationEngine

engine = RecommendationEngine(repository=graph_adapter)   # optional: clock=, policy=
app = create_app(mode="production", extractor=configured_extractor(), recommendations=engine)
```

- `async def recommend(request: RecommendationRequest) -> RecommendationResult`. This
  matches the v2 `RecommendationService` protocol and is native async.
- Reads `request.context` (`RetrievalContext`): `interests[].value`, `skills[]`
  (name/status), `completed_courses[].value`, `target`, `constraints.modality.value`.
  Evidence quotes are never copied into output, logs or the graph.
- Clarifications request exactly one field, using the canonical paths `target`,
  `interests` or `skills.<name>`, and always include an "I'm not sure" option.
- Recommendations also fill v2's `modality` and `status` fields. `status` is the event's
  recorded status, or the best listed course term (`enrollment open`, `scheduled`,
  `offering unconfirmed`).
- One engine instance can be shared across requests. The no-persistence rule is covered
  below.

`tests/test_recommendation_integration.py` runs the engine through the real
`ChatService`, `AskBackPolicy` and `POST /api/chat`, plus the published
`docs/examples/recommendation_request.json`. Only the extractor is stubbed.

## Pipeline

| Step | Module | Key rules |
| --- | --- | --- |
| Resolve direction | `destination.py` | Company, role and team targets plus aliases. An ambiguous name gets one question while interests still produce provisional results. With no target, interests map to grounded directions. With no target and no interests, the engine asks one plain question **and** returns broad, clearly labeled starting points, so an "I'm not sure" reply never blocks results. |
| Analyze preparation | `preparation.py` | Statuses are known, learning, not_yet_learned and unknown, matched through graph aliases. **Unknown is never a gap.** Completed courses count as *exposure* only. Team-specific and role-baseline requirements are kept separate. |
| Retrieve | `retrieval.py` | Requirement skill → course/event, interest topic → course/event, prerequisite bridges (a blocked course → an action that teaches its missing prerequisite), and broad starters (intro courses with no listed prerequisites, plus events). |
| Feasibility | `feasibility.py` | Cancelled, postponed, past and registration-closed events are excluded. Courses are excluded only on recorded evidence. Anything else unknown is labeled, never assumed. Dates come from an injectable `Clock`. |
| Rank | `ranking.py` | Small integer weights in `RankingPolicy`: relevance + learning benefit + readiness + feasibility + freshness + requested kind. Scores are never returned. |
| Explain | `explain.py` | Courses *teach*. Events offer practice, exposure or networking and state that attendance isn't proficiency and networking isn't a job guarantee. |

## Data handling

The instance holds only collaborators and configuration. Student-derived data lives in
local variables during `recommend` and is released when the call returns. There are no
caches, persistence, logging or graph writes. Tests check that engine state is unchanged
after concurrent requests and that nothing is logged. Every request is computed from
scratch.

## How results change (each has a test)

| Change | Result |
| --- | --- |
| Student says Python is known instead of not yet learned | The intro Python course drops out. |
| Goal changes from SWE to Robotics Engineer | A different set, with evidence paths through the new role. |
| An event record becomes cancelled | The event is removed and the limitations say why. |
| A prerequisite is known to be unmet | The blocked course is skipped with a reason, and the course that teaches the prerequisite is shown with the path `requirement → blocked course → prerequisite → this course`. |

## Integration mismatches to resolve

### Abishek: `GraphRepository` (`feat/knowledge-graph-ingestion`, not on master yet)

The engine depends on the typed protocol in `recommendations/graph.py`. Abishek's
`trojan_compass.graph.GraphRepository` has a different shape. Once his branch merges,
the plan is a thin adapter **in this package** that wraps his repository; his code stays
unchanged.

| Gap | Abishek's branch | Engine needs |
| --- | --- | --- |
| Sync vs async | Sync methods | Async. The adapter will call his methods through `asyncio.to_thread`, as INTEGRATION.md specifies. |
| Cancelled/postponed actions | `find_actions` filters them out (Neo4j also filters past `end_date`) | **Return them with `status`.** Otherwise the engine can't explain "skipped: cancelled", which is a demo-acceptance case. |
| Course/event details | Untyped `GraphRecord.attributes` dict | Agreed keys for prerequisites (course codes and skills), restrictions, offered terms with status, modality, event start/end with offset, eligibility, registration required/url/deadline. |
| Action → skill relation | Only `evidence_paths` and tags | Skill id plus relation (`teaches`/`practices`/`exposes`/`networking`) and level. Without these, "courses teach, events expose" can't be stated reliably. |
| Destination aliases and links | `Destination(id, kind, name, company_id)`; substring name match | Aliases ("SWE"), team → base role, company → roles. |
| Interest → direction | Not present | `suggest_directions(interests)`, or a topic → destination edge. |
| Completed-course lookup | Not present | `find_courses(codes_or_titles)` to read exposure and prerequisites. |
| Vocabulary | `required`/`preferred`; `active` status; `checked_at: date` | `core`/`preferred`; `scheduled`; `datetime`. The adapter can map these. |

### Karthik: chat backend (merged)

- **Skill paths and aliases.** `AskBackPolicy` treats `skills.<x>` as answered only
  when an extracted skill name equals `<x>` exactly, ignoring case. The engine sends the
  casefolded graph name (`skills.python`, `skills.data structures`). If the extractor
  writes an alias ("DSA"), the policy may not see the question as answered. A suggested
  fix on his side is to let the extractor normalize to graph names.
- **`RetrievalContext.skill_status`** matches exact names only. The engine doesn't use
  it; it matches through graph aliases itself.
- **`Recommendation.status`** is free text. The values listed under Wiring need
  confirming with Riddhi before the UI styles them.
- **`ChatResponse`** has no separate clarification object. The question comes through as
  `message` plus `suggested_replies`, which works with the engine as is.

## Limitations

- The fixture data is synthetic (SYN course codes, fictional companies, example.org).
  Real USC data depends on Abishek's adapter.
- Course restrictions (major, D-clearance) are shown and labeled unknown, not evaluated.
- `constraints.time_window` isn't parsed. Course modality is compared with
  `constraints.modality` by exact text.
- `user_query` is only used to detect a request for courses or events.

## Checks run (same commands as CI)

```
pytest -q                      # 75 passed (36 chat + 39 recommendation)
mypy src tests                 # strict, no issues (20 files)
ruff check src tests           # passes
ruff format --check src tests  # passes
```
