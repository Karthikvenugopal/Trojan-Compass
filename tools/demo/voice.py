"""Generate voice-over clips for the demo video from narration.json (OpenAI text-to-speech).

Usage (from the repo root): .venv/Scripts/python.exe tools/demo/voice.py
Writes tools/demo/out/voice/<id>.mp3 and durations.json. Only the narration text is sent.
"""

import json
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
from dotenv import dotenv_values

HERE = Path(__file__).resolve().parent
OUT = HERE / "out" / "voice"
FFMPEG = HERE / "node_modules" / "ffmpeg-static" / "ffmpeg.exe"
KEY = dotenv_values(HERE.parents[1] / ".env")["OPENAI_API_KEY"]
STYLE = "Warm, confident and clear, like a calm documentary narrator. Unhurried, with natural pauses."


def speak(segment: dict[str, str]) -> tuple[str, float]:
    path = OUT / f"{segment['id']}.mp3"
    response = httpx.post(
        "https://api.openai.com/v1/audio/speech",
        headers={"Authorization": f"Bearer {KEY}"},
        json={
            "model": "gpt-4o-mini-tts",
            "voice": "onyx",
            "input": segment["text"],
            "instructions": STYLE,
            "response_format": "mp3",
        },
        timeout=120,
    )
    response.raise_for_status()
    path.write_bytes(response.content)
    probe = subprocess.run([str(FFMPEG), "-i", str(path)], capture_output=True, text=True)
    match = re.search(r"Duration: (\d+):(\d+):(\d+\.\d+)", probe.stderr)
    assert match, probe.stderr[-300:]
    hours, minutes, seconds = match.groups()
    return segment["id"], int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    segments = json.loads((HERE / "narration.json").read_text(encoding="utf-8"))
    with ThreadPoolExecutor(5) as pool:
        durations = dict(pool.map(speak, segments))
    (OUT / "durations.json").write_text(json.dumps(durations, indent=1), encoding="utf-8")
    for name, seconds in durations.items():
        print(f"{name:10s} {seconds:5.1f}s")
    print(f"total speech {sum(durations.values()):.1f}s")


if __name__ == "__main__":
    main()
