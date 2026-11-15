"""Tag each faculty profile with research areas (Professor -RESEARCHES-> Skill edges).

Reads data/usc/faculty_research.json (official USC directory text), asks the configured
OpenAI model for 2-6 research areas per professor using the same naming style as course
skills, and writes the areas back into the same file. Only public profile text is sent.

Usage: python scripts/tag_faculty_research.py
"""

from __future__ import annotations

import asyncio
import json
import os

import httpx
from dotenv import dotenv_values
from tag_course_skills import ROOT, tag_batch

FACULTY = ROOT / "data" / "usc" / "faculty_research.json"
PROMPT = """You tag professors with their research areas, to build a campus knowledge
graph that connects student interests to people doing research.

For each entry (code = an opaque id, title = name and position, description = official
biography or research summary) return 2 to 6 research areas. Rules:
- lowercase, 1-4 words, canonical field names a student would search for, e.g.
  "machine learning", "computer vision", "robotics", "natural language processing",
  "fluid dynamics", "tissue engineering", "wireless communication".
- Use only what the text supports. No awards, job titles or institutions.
- If the text has no research content return an empty list.
Return one entry per input, using the exact code given."""


async def main() -> int:
    env = {**dotenv_values(ROOT / ".env"), **os.environ}
    key, model = env.get("OPENAI_API_KEY"), env.get("OPENAI_MODEL")
    if not key or not model:
        raise SystemExit("OPENAI_API_KEY and OPENAI_MODEL are required (.env)")
    payload = json.loads(FACULTY.read_text(encoding="utf-8"))
    faculty = payload["faculty"]
    items = [
        {
            "code": f"{r['last_name']}|{r['first_name']}",
            "title": f"{r['name']}, {r['title']}"[:300],
            "description": r["research_text"][:900],
        }
        for r in faculty
        if r.get("research_text")
    ]
    batches = [items[i : i + 15] for i in range(0, len(items), 15)]
    semaphore = asyncio.Semaphore(6)
    merged: dict[str, list[str]] = {}
    async with httpx.AsyncClient(timeout=httpx.Timeout(90.0)) as client:

        async def run(batch: list[dict[str, str]]) -> None:
            async with semaphore:
                merged.update(await tag_batch(client, key, model, batch, PROMPT))

        await asyncio.gather(*(run(batch) for batch in batches))
    for record in faculty:
        record["areas"] = merged.get(f"{record['last_name']}|{record['first_name']}", [])
    FACULTY.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    tagged = sum(1 for r in faculty if r["areas"])
    print(f"tagged {tagged} of {len(faculty)} faculty with research areas")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
