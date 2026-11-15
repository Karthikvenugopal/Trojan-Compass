# Stateless integration contract v2

Abishek owns KG/data; Peri owns recommendations; Riddhi owns frontend. Chat owns
contracts, extraction, orchestration and application composition. Master had only
README; no AGENTS.md or owner implementations existed at inspection. The prior
chat-session branch supplies stack/conventions, but its session/profile API is
superseded here. Do not integrate its session repository.

The implementations now use this v2 boundary. The runtime composition is in
`trojan_compass.composition`; see the root README for campus/production startup.
This records code compatibility, not an assumption that every data limitation is resolved.

Shared interface:

- Riddhi: `POST /api/chat` with `ChatRequest.messages` (user/assistant only), then
  render `ChatResponse`. Keep active conversation in frontend memory only. Clear
  means discard that memory. No session IDs, local/sessionStorage, transcripts in
  analytics, or persisted profiles. Render sources, evidence paths, unknowns,
  access requirements and limitations. Show structured dates in their timezone.
- Peri: `async recommend(RecommendationRequest) -> RecommendationResult`. The
  request has `context`, `user_query`, `limit`. Context uses supported values
  (`{value,evidence:[{message_index,quote}]}`); skills have `name,status,evidence`.
  Unknown skills are never missing skills; completed courses never prove mastery.
  Return one material clarification field at a time; use canonical context paths,
  e.g. `skills.python`, `constraints.time_window`, `interests`, `target`.
  Ask only if it changes retrieval. Include an “I'm not sure” option. No caching,
  persistence or content logging of requests, context or results. Recommendations
  require sources and evidence paths. A clarification may accompany results.
- Abishek: construct your read-only graph adapter, inject it into Peri's service,
  then pass that service to `create_app(extractor=..., recommendations=...)`.
  Only shared campus graph data may persist. Do not create student nodes, log
  graph parameters, or write derived student facts. The factory now constructs
  this dependency chain using the async graph protocol shared by both owners.

Dependency shape: Abishek graph adapter → Peri RecommendationService → ChatService.
A synchronous adapter must be wrapped with `asyncio.to_thread` by its owner.
The default remains an explicit fixture/demo service. Campus mode connects the real
engine to the reviewed public seed through Abishek’s in-memory adapter; production
connects his Neo4j adapter. Missing production credentials fail startup. No graph
writes occur through the chat factory; Neo4j imports remain a separate command.
See GRAPH_INTEGRATION.md for data semantics that remain incomplete.

All models forbid extra fields. Nullable fields use null; lists default empty.
Examples are synthetic and generated from the Pydantic contracts. No student
information is returned as a profile. OpenAPI publishes the HTTP contract;
`docs/examples/contracts.schema.json` publishes all shared models.
