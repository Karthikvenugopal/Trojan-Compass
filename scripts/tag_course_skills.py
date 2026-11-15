"""Tag every catalog course with the skills/topics it teaches (knowledge-graph edges).

Reads data/usc/catalog.json, sends official titles + descriptions in batches to the
configured OpenAI model with a strict JSON schema, and writes
data/usc/course_skills.json: {course code: [skill, ...]}.

These links are *inferred* from USC's official description text and are labeled as
such in the app. Only public catalog text is sent; no student data is involved.
Batches are cached under data/raw/skill-tags/ so an interrupted run resumes.

Usage: python scripts/tag_course_skills.py [--batch 30] [--workers 8]
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
from pathlib import Path

import httpx
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "data" / "usc" / "catalog.json"
OUTPUT = ROOT / "data" / "usc" / "course_skills.json"
CACHE = ROOT / "data" / "raw" / "skill-tags"

PROMPT = """You tag university courses with the skills and topics they teach, to build a
campus knowledge graph that connects student interests to courses.

For each course return 2 to 5 skills. Rules:
- lowercase, 1-4 words, canonical and widely used names a student would search for,
  e.g. "machine learning", "information retrieval", "organic chemistry",
  "film directing", "financial accounting", "public speaking", "human anatomy".
- Prefer the established general name over course-specific phrasing, so that related
  courses share the same skill names. Put the most central skill first.
- Use only what the title and description support. No course codes, no school names.
- Never use empty labels such as "research", "seminar", "thesis", "special topics",
  "independent study" or "internship". For courses with no topical content (directed
  research, dissertation, generic special topics) return an empty list.
Return one entry per input course, using the exact code given."""

SCHEMA = {
    "type": "object",
    "properties": {
        "courses": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "code": {"type": "string"},
                    "skills": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["code", "skills"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["courses"],
    "additionalProperties": False,
}


def clean_skill(value: str) -> str | None:
    text = re.sub(r"[^a-z0-9+#&/.' -]", " ", value.casefold())
    text = " ".join(text.split()).strip(" .-/")
    if not 2 <= len(text) <= 48 or len(text.split()) > 5:
        return None
    return text


async def tag_batch(
    client: httpx.AsyncClient,
    key: str,
    model: str,
    batch: list[dict[str, str]],
    prompt: str = PROMPT,
    most: int = 5,
) -> dict[str, list[str]]:
    digest = hashlib.sha1(json.dumps(batch, sort_keys=True).encode()).hexdigest()[:16]
    cache_file = CACHE / f"{digest}.json"
    if cache_file.exists():
        return json.loads(cache_file.read_text(encoding="utf-8"))
    last: Exception | None = None
    for attempt in range(5):
        try:
            response = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {key}"},
                json={
                    "model": model,
                    "store": False,
                    "temperature": 0,
                    "max_completion_tokens": 4096,
                    "messages": [
                        {"role": "system", "content": prompt},
                        {"role": "user", "content": json.dumps(batch, ensure_ascii=False)},
                    ],
                    "response_format": {
                        "type": "json_schema",
                        "json_schema": {"name": "course_skills", "strict": True, "schema": SCHEMA},
                    },
                },
            )
            if response.status_code == 429 or response.status_code >= 500:
                raise httpx.HTTPStatusError("retry", request=response.request, response=response)
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
            wanted = {item["code"] for item in batch}
            result: dict[str, list[str]] = {}
            for item in json.loads(content)["courses"]:
                if item["code"] in wanted:
                    skills = [s for s in (clean_skill(v) for v in item["skills"]) if s]
                    result[item["code"]] = list(dict.fromkeys(skills))[:most]
            CACHE.mkdir(parents=True, exist_ok=True)
            cache_file.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
            return result
        except (httpx.HTTPError, KeyError, json.JSONDecodeError) as exc:
            last = exc
            await asyncio.sleep(2 ** (attempt + 1))
    print(f"  ! batch failed: {type(last).__name__}", flush=True)
    return {}


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch", type=int, default=30)
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()

    env = {**dotenv_values(ROOT / ".env"), **os.environ}
    key, model = env.get("OPENAI_API_KEY"), env.get("OPENAI_MODEL")
    if not key or not model:
        raise SystemExit("OPENAI_API_KEY and OPENAI_MODEL are required (.env)")

    courses = json.loads(CATALOG.read_text(encoding="utf-8"))["courses"]
    items = [
        {
            "code": c["code"],
            "title": c["title"],
            "description": (c.get("description") or "")[:420],
        }
        for c in courses
        if c.get("title")
    ]
    batches = [items[i : i + args.batch] for i in range(0, len(items), args.batch)]
    print(f"{len(items)} courses in {len(batches)} batches", flush=True)

    semaphore = asyncio.Semaphore(args.workers)
    done = 0
    merged: dict[str, list[str]] = {}

    async with httpx.AsyncClient(timeout=httpx.Timeout(90.0)) as client:

        async def run(batch: list[dict[str, str]]) -> None:
            nonlocal done
            async with semaphore:
                merged.update(await tag_batch(client, key, model, batch))
            done += 1
            if done % 20 == 0 or done == len(batches):
                print(f"  {done}/{len(batches)} batches, {len(merged)} courses tagged", flush=True)

        await asyncio.gather(*(run(batch) for batch in batches))

    OUTPUT.write_text(
        json.dumps(dict(sorted(merged.items())), ensure_ascii=False, indent=0), encoding="utf-8"
    )
    skills = {s for values in merged.values() for s in values}
    missing = len(items) - len(merged)
    print(f"wrote {OUTPUT.relative_to(ROOT)}: {len(merged)} courses, {len(skills)} skills")
    print(f"untagged courses: {missing}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
