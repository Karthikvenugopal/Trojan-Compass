#!/usr/bin/env bash
# Read the backend .env locally; print only diagnostic metadata, never credentials.
set -euo pipefail
compass_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$compass_root"
if [[ -x .venv/bin/python ]]; then
  compass_python="$compass_root/.venv/bin/python"
else
  compass_python="$(command -v python3)"
fi
PYTHONPATH="$compass_root/src${PYTHONPATH:+:$PYTHONPATH}" \
  exec "$compass_python" -m trojan_compass.diagnostics "$@"
