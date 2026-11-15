#!/usr/bin/env bash
# Local development only. Credentials load inside the backend process.
set -euo pipefail
compass_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$compass_root"

if [[ ! -f .env ]]; then
  echo 'Missing backend .env configuration.' >&2
  exit 1
fi
if [[ -x .venv/bin/python ]]; then
  compass_python="$compass_root/.venv/bin/python"
else
  compass_python="$(command -v python3)"
fi
"$compass_python" - <<'PY'
import importlib.util
import socket
import sys
missing = [name for name in ('fastapi', 'pydantic', 'httpx', 'uvicorn', 'dotenv')
           if importlib.util.find_spec(name) is None]
if missing:
    print(f'Install backend dependencies with: "{sys.executable}" -m pip install -e . python-dotenv', file=sys.stderr)
    raise SystemExit(1)
for port in (8000, 5173):
    try:
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', port))
    except OSError:
        print(f'Cannot open local port {port}. Run this script in your normal terminal; '
              'if another server uses the port, stop it first.', file=sys.stderr)
        raise SystemExit(1)
PY
if [[ ! -x frontend/node_modules/.bin/vite ]]; then
  (cd frontend && npm ci)
fi

compass_backend_pid=''
compass_frontend_pid=''
cleanup() {
  trap - EXIT INT TERM
  [[ -z "$compass_frontend_pid" ]] || kill "$compass_frontend_pid" 2>/dev/null || true
  [[ -z "$compass_backend_pid" ]] || kill "$compass_backend_pid" 2>/dev/null || true
  wait 2>/dev/null || true
}
trap cleanup EXIT INT TERM

PYTHONPATH="$compass_root/src${PYTHONPATH:+:$PYTHONPATH}" \
  "$compass_python" -m uvicorn trojan_compass.api:app_from_environment \
  --factory --env-file "$compass_root/.env" --host 127.0.0.1 --port 8000 --no-access-log &
compass_backend_pid=$!
(cd frontend && export VITE_USE_MOCK_API=false && \
  exec node node_modules/vite/bin/vite.js --host 127.0.0.1 --port 5173 --strictPort) &
compass_frontend_pid=$!

echo 'Starting Trojan Compass at http://127.0.0.1:5173'
echo 'Backend: http://127.0.0.1:8000/health — Ctrl+C stops both servers.'
while kill -0 "$compass_backend_pid" 2>/dev/null && kill -0 "$compass_frontend_pid" 2>/dev/null; do
  sleep 1
done
echo 'A development server stopped. Review the startup message above.' >&2
exit 1
