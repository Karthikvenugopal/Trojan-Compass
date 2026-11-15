# Trojan Compass

**Find your path at USC: courses, professors, research and the skills to learn, connected.**

Team: Periyakaruppan Nagappan, Riddhi Gupta, Karthik, Abhishek Nair

## The problem

"What should I take next?" is the most common question a student has, and USC already holds
the answer. It is just scattered: 7,306 courses across 26 schools in the Schedule of Classes,
faculty research on department sites, events in Handshake, and hours, deadlines and services
on a dozen office websites.

Search doesn't fix this. A keyword search finds courses that contain your words, but students
don't use catalog words. Someone who says "agentic RAG" needs *information retrieval*, and no
course description says "RAG". Students who aren't sure what they want are served even worse.

## Our solution

Trojan Compass treats the campus as a **knowledge graph** and walks it from what a student
says to what they should do next.

- **Three ways in.** "I'm not sure where to start", "I have an interest to explore", or "I
  know what I want". Every question is optional and "I don't know" is always a valid answer.
  A resume can be pasted or uploaded; it is read in the browser and never stored.
- **A path through the graph.** The student's words are linked to skill nodes, then the
  graph is walked: skills → courses → prerequisites → professors → research → events.
- **A few recommendations at a time,** each with why it fits, seats and meeting times for
  next term, and links to the official source.
- **The graph itself,** drawn so the student can select any node and trace its path, with an
  accessible list view of the same data.
- **A roadmap to keep:** what I know → what to learn → courses and research to explore, plus
  **one concrete next step** ("Add CSCI 572 to your Spring 2027 plan: 177 of 360 seats open").
  It saves as a file or prints.
- **Everyday questions,** like "Is any library open right now?" or "Who teaches CSCI 572?",
  answered only from live and official sources, with the source linked.

## How we built it

**Data (real, public USC data).**
- 7,306 courses for Spring 2026, Fall 2026 and Spring 2027 from USC's public Schedule of
  Classes: descriptions, prerequisites, sections, seats, instructors, syllabus links.
- 10,558 skills and 20,020 course→skill links, inferred by an LLM from each official course
  description and labeled "inferred" in the app.
- 5,180 instructors, with research areas for Viterbi faculty from official directory profiles.
- About 200 official USC pages (registrar, health, dining, transit, OIS, housing…) and live
  library hours.
- Handshake's API is private, so events are **mock data** in Handshake's export format, with
  fictional employers, labeled as sample data everywhere.

The graph has 39,115 edges: TEACHES, HAS_PREREQUISITE, TAUGHT_BY, RESEARCHES, COVERS.

**Pipeline per message (about 3 seconds).**
1. *Listen.* An LLM extracts interests, skills and background as structured JSON. Every fact
   must quote the student's own words, and that is checked mechanically.
2. *Link.* The student's phrases are matched to skill nodes. The LLM may only choose nodes
   that exist in the graph.
3. *Walk.* Skills → courses → prerequisites → professors → events, ranked by fit, level and
   whether the course runs next term.
4. *Show.* Cards, the walked subgraph, a roadmap and one next step.

**Tech stack.** React, TypeScript and Vite (hand-built SVG graph view); Python, FastAPI and
Pydantic; OpenAI GPT-4.1-mini or Google Gemini with structured output; an in-memory knowledge
graph with BM25 retrieval that builds in 1.3 seconds, in a format that also imports into
Neo4j; Playwright for browser tests, screenshots and the demo video.

**Trust and privacy.** The service is stateless: no login, no student database, no
conversation logs. Every card and answer links its official source. Limits are stated in the
reply: seats are a snapshot, skill links are inferred, eligibility must be confirmed.

## Challenges

- **No official course API.** We found the public JSON endpoints behind classes.usc.edu and
  fetched every school and program politely, with caching.
- **Students don't speak catalog.** Exact matching returned "no match" for most real
  phrasing. Linking phrases to graph nodes fixed it.
- **Keeping the LLM honest.** Strict schemas, verbatim-quote checks and graph-only choices,
  plus fallbacks so one bad model reply never fails a turn.
- **Private data sources.** Handshake could not be integrated, so we mocked it in its own
  format and labeled it clearly.

## What's next

- Live Handshake and USC events feeds through official partnerships.
- Research coverage beyond Viterbi: labs, papers and open positions.
- Degree requirements, so a path also counts toward graduation.
- Nightly data refresh and a Neo4j deployment for campus-wide use.

## Links

- Code: https://github.com/Karthikvenugopal/Trojan-Compass (branch `feat/knowledge-graph-roadmap`)
- Slide deck: `docs/submission/TrojanCompass-deck.pdf`
- Demo video: `docs/submission/TrojanCompass-demo.webm`
- Screenshots: `docs/submission/screenshots/`
