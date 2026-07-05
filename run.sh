#!/usr/bin/env bash
# Local Agents Studio — production launch (gunicorn, threaded for SSE streaming)
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
  python3 -m venv .venv
  .venv/bin/pip install -r requirements.txt
fi

# Build the React frontend if the bundle is missing or sources are newer.
if [ ! -f static/dist/index.html ] || \
   [ -n "$(find frontend/src frontend/index.html -newer static/dist/index.html 2>/dev/null | head -1)" ]; then
  echo "→ Building frontend…"
  (cd frontend && npm install --silent && npm run build)
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
