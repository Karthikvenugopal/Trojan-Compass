"""Refresh every public data set the app uses, in order, with one command.

Usage:  python scripts/refresh_data.py            # run everything (about 45 minutes)
        python scripts/refresh_data.py --dry-run  # list the steps only

Steps that call the LLM (skill and research tagging) need OPENAI_API_KEY and
OPENAI_MODEL in .env. Raw downloads are cached under data/raw/, so an interrupted run
resumes. Restart the server afterwards: the knowledge graph is rebuilt at startup.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STEPS = [
    ("USC Schedule of Classes -> data/usc/catalog.json", "fetch_usc_catalog.py"),
    ("Course skills (LLM) -> data/usc/course_skills.json", "tag_course_skills.py"),
    ("Viterbi faculty profiles -> data/usc/faculty_research.json", "fetch_faculty_research.py"),
    ("Faculty research areas (LLM)", "tag_faculty_research.py"),
    ("Official USC pages -> data/usc/campus_kb.json", "fetch_campus_kb.py"),
    ("Mock Handshake events -> data/mock/handshake_events.json", "generate_handshake_mock.py"),
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--dry-run", action="store_true", help="list the steps without running")
    args = parser.parse_args()
    for number, (label, script) in enumerate(STEPS, 1):
        print(f"[{number}/{len(STEPS)}] {label}", flush=True)
        if args.dry_run:
            continue
        # Run from scripts/ so tag_faculty_research can import tag_course_skills.
        result = subprocess.run([sys.executable, script], cwd=ROOT / "scripts")
        if result.returncode != 0:
            print(f"step failed: {script} (exit {result.returncode})", file=sys.stderr)
            return result.returncode
    print("done. Restart the server to rebuild the knowledge graph.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
