#!/usr/bin/env bash
# Restart the Local Agents Studio server cleanly (waits for the port to free).
set -euo pipefail
cd "$(dirname "$0")"
PORT="${PORT:-5860}"

PIDS=$(pgrep -f "gunicorn.*${PORT}" || true)
if [ -n "$PIDS" ]; then
  echo "→ Stopping gunicorn ($PIDS)…"
  kill $PIDS 2>/dev/null || true
  for _ in $(seq 1 60); do
    pgrep -f "gunicorn.*${PORT}" > /dev/null || break
    sleep 0.5
  done
  pkill -9 -f "gunicorn.*${PORT}" 2>/dev/null || true
fi

echo "→ Starting Local Agents Studio on http://127.0.0.1:${PORT}"
setsid nohup .venv/bin/gunicorn \
  --bind "127.0.0.1:${PORT}" \
  --workers 1 --threads 16 --timeout 0 --graceful-timeout 5 \
  app:app > data/server.log 2>&1 < /dev/null &

for _ in $(seq 1 40); do
  curl -sf "http://127.0.0.1:${PORT}/api/health" > /dev/null 2>&1 && { echo "→ Up."; exit 0; }
  sleep 0.5
done
echo "!! Server did not come up; see data/server.log" >&2
exit 1
