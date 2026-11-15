#!/usr/bin/env bash
# Local development only. Credentials load inside the backend process.
set -euo pipefail
compass_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$compass_root"
case "${1:-}" in
  --diagnostic) export COMPASS_MODE=diagnostic ;;
  "") ;;
  *) echo 'Usage: bash scripts/dev.sh [--diagnostic]' >&2; exit 2 ;;
esac

if [[ ! -f .env ]]; then
  echo 'Missing backend .env configuration.' >&2
  exit 1
fi
# Check the host first, before installing anything. Permission failures and busy
# ports have different remedies; neither means the application is already ready.
compass_bootstrap_python="$(command -v python3)"
"$compass_bootstrap_python" - <<'PY'
import errno
import socket
import sys
if sys.version_info < (3, 11):
    raise SystemExit('Python 3.11 or newer is required.')
for port in (8000, 5173):
    try:
        with socket.socket() as listener:
            # Match Uvicorn's reuse policy so a clean restart is not rejected
            # by sockets in TIME_WAIT. An active listener still fails this bind.
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind(('127.0.0.1', port))
    except OSError as error:
        if error.errno in (errno.EPERM, errno.EACCES):
            print(f'This execution environment forbids opening local port {port}. '
                  'No server was started. Launch this script in macOS Terminal.', file=sys.stderr)
        elif error.errno == errno.EADDRINUSE:
            print(f'Port {port} is already in use. Stop that server before launching.', file=sys.stderr)
        else:
            print(f'Local port {port} is unavailable (errno {error.errno}).', file=sys.stderr)
        raise SystemExit(1)
PY

# Always use a project environment, independent of Terminal/Conda/system Python.
if [[ ! -x .venv/bin/python ]]; then
  "$compass_bootstrap_python" -m venv .venv
fi
compass_python="$compass_root/.venv/bin/python"
if ! "$compass_python" - <<'PY'
import importlib.util
import sys
required = ('fastapi', 'pydantic', 'httpx', 'uvicorn', 'dotenv', 'pypdf', 'defusedxml')
sys.exit(any(importlib.util.find_spec(name) is None for name in required))
PY
then
  "$compass_python" -m pip install -e .
fi
if [[ ! -x frontend/node_modules/.bin/vite ]]; then
  (cd frontend && npm ci)
fi

compass_backend_pid=''
compass_frontend_pid=''
cleanup() {
  compass_exit_status=$?
  trap - EXIT INT TERM
  [[ -z "$compass_frontend_pid" ]] || kill "$compass_frontend_pid" 2>/dev/null || true
  [[ -z "$compass_backend_pid" ]] || kill "$compass_backend_pid" 2>/dev/null || true
  wait 2>/dev/null || true
  exit "$compass_exit_status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

# Start the backend first; Vite must never accept requests before its API is ready.
compass_wait_ready() {
  "$compass_python" - "$1" "$2" <<'PYTHON'
import sys
import time
import httpx
name, url = sys.argv[1:]
with httpx.Client(trust_env=False, timeout=0.5) as client:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        try:
            response = client.get(url)
            if response.status_code == 200:
                if name != 'backend' or response.json().get('status') == 'ok':
                    break
        except (httpx.HTTPError, ValueError):
            pass
        time.sleep(0.25)
    else:
        print(f'The {name} did not become ready. No working site is being advertised. '
              'Check the startup error above.', file=sys.stderr)
        raise SystemExit(1)
PYTHON
}

PYTHONPATH="$compass_root/src${PYTHONPATH:+:$PYTHONPATH}" \
  "$compass_python" -m uvicorn trojan_compass.api:app_from_environment \
  --factory --env-file "$compass_root/.env" --host 127.0.0.1 --port 8000 --no-access-log \
  --reload --reload-dir "$compass_root/src" &
compass_backend_pid=$!
compass_wait_ready backend http://127.0.0.1:8000/health

(cd frontend && export VITE_USE_MOCK_API=false && \
  exec node node_modules/vite/bin/vite.js --host 127.0.0.1 --port 5173 --strictPort) &
compass_frontend_pid=$!
compass_wait_ready frontend http://127.0.0.1:5173

echo 'Trojan Compass is ready: http://127.0.0.1:5173'
echo 'Backend health passed. Keep this terminal open; Ctrl+C stops both servers.'
while kill -0 "$compass_backend_pid" 2>/dev/null && kill -0 "$compass_frontend_pid" 2>/dev/null; do
  sleep 1
done
echo 'A development server stopped. Both servers are shutting down.' >&2
exit 1
