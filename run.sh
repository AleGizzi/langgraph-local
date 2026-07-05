#!/usr/bin/env bash
# Local Agents Studio — production launch (gunicorn, threaded for SSE streaming)
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
  python3 -m venv .venv
  .venv/bin/pip install -r requirements.txt
fi

PORT="${PORT:-5860}"
echo "→ Local Agents Studio on http://127.0.0.1:${PORT}"
exec .venv/bin/gunicorn \
  --bind "127.0.0.1:${PORT}" \
  --workers 1 \
  --threads 16 \
  --timeout 0 \
  --graceful-timeout 5 \
  --access-logfile - \
  app:app
