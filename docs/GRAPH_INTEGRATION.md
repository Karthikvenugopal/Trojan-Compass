# Graph integration and contract mismatches

## Current graph boundary

The adapter implements the canonical async `GraphRepository` from `trojan_compass.recommendations.graph`, now merged to `master` with Peri's recommendation engine. It returns the engine's typed Pydantic read models; driver objects and Cypher stay private. Neo4j blocking I/O runs through `asyncio.to_thread`, queries are parameterized, and request-derived results are not cached. The fake implements the same protocol for deterministic tests. The read API supports destination resolution, scoped requirements, interest-to-destination suggestions through explicit `HAS_REQUIREMENT → ABOUT → Topic` evidence, action retrieval by skills/topics, broad action browsing, and exact course lookup.

The integrated API boundary is `ChatService` → v2 `RecommendationRequest(context=RetrievalContext, user_query=...)` → Peri's `RecommendationEngine` → this GraphRepository. Production composition injects the recommendation engine as `RecommendationService` into `create_app(extractor=..., recommendations=..., mode="production")`; a raw GraphRepository is not an API service.

## Mismatches to resolve before composing branches

1. **Relationship evidence excerpts:** Neo4j preserves excerpts on `Evidence` nodes and relationship properties. `Requirement.statement` carries a requirement excerpt to Peri, but `CampusAction.sources` and Karthik's shared `Source` contract expose only URL, title and checked timestamp. Action excerpts therefore do not cross the recommendation boundary today; add an evidence field to a shared contract if downstream explanations need the exact excerpt.
2. **Networking semantics:** `SkillLink.relation` supports `networking`, while this dataset represents event networking as an evidenced `Topic` (Career networking). No networking skill edge is created without explicit skill evidence; keep topic exposure distinct from a networking skill claim.
3. **Prerequisite semantics:** ingestion stores formal versus helpful `HAS_PREREQUISITE` edges, but the current recommendation `Prerequisite` has no type field and the engine does not query prerequisites from the graph. The distinction is retained in storage but cannot currently inform explanations or filtering.
4. **Featured organizations:** the graph accepts `FEATURES` only with explicit source evidence, but `CampusAction` has no company/team feature field and the read adapter does not expose those edges. The current recommendation consumer cannot show an event's evidenced company or team participants.
5. **Occurrence schedule:** Karthik's `EventSchedule` and Peri's `EventInfo` use offset-aware datetimes. The import format accepts date-only occurrence dates, which are preserved in storage but omitted from the consumer model rather than assigned invented times. Add date-only schedule fields before exposing such dates through recommendations.
6. **Scoped requirement subjects:** ingestion can attach requirements to Skill or Topic, but the recommendation `Requirement` model contains only a `SkillNode`. The adapter currently returns skill requirements; topic requirements remain stored and evidenced but unavailable to recommendation analysis.

The campus seed has no company/team features or destination-wide action relevance edges. Interest-based directions only use an explicit requirement-about-topic path; no action is connected to every career destination. Course offerings remain unknown when no source lists an offering. Exact course lookup resolves course identities (including their linked learning edges), not a fabricated catalog of dated section offerings.

## Privacy and operational boundary

`RetrievalContext` is temporary. Graph calls may receive request-derived names/interests/skill IDs to retrieve shared facts, but those parameters are not cached or logged. Never persist them, add `Student` nodes, log Cypher parameter values, or attach them to traces. Neo4j server-side query, audit, APM and managed-service logs still require deployment-level redaction/retention controls described in [DATA_IMPORT.md](DATA_IMPORT.md).
