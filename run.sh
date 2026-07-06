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

# First-run guidance: no provider detected → the in-app wizard handles it.
if ! curl -sf --max-time 2 "${OLLAMA_URL:-http://localhost:11434}/api/version" > /dev/null 2>&1 \
   && ! curl -sf --max-time 2 "${LMSTUDIO_URL:-http://localhost:1234/v1}/models" > /dev/null 2>&1; then
  echo "ℹ No local model provider detected (Ollama / LM Studio)."
  echo "  Open http://127.0.0.1:${PORT} → Setup and click “Install Ollama automatically”."
fi

echo "→ Local Agents Studio on http://127.0.0.1:${PORT}"
exec .venv/bin/gunicorn \
  --bind "127.0.0.1:${PORT}" \
  --workers 1 \
  --threads 16 \
  --timeout 0 \
  --graceful-timeout 5 \
  --access-logfile - \
  app:app
