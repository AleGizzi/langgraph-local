#!/usr/bin/env bash
# Launcher for the Agent Studio desktop app: make sure the local server is up,
# then open it in a dedicated window that looks like a native app (no tabs / URL
# bar when a Chromium-family browser is available; a normal window otherwise).
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PORT="${PORT:-5860}"
URL="http://localhost:${PORT}/"

# 1. Start the server if it isn't already answering.
if ! curl -sf --max-time 2 "http://localhost:${PORT}/api/health" >/dev/null 2>&1; then
  notify-send "Agent Studio" "Starting the local server…" 2>/dev/null || true
  # run.sh backgrounds gunicorn and returns once it's healthy.
  (cd "$APP_DIR" && PORT="$PORT" ./run.sh >/dev/null 2>&1 &)
  # Wait up to ~90s for the model server + gunicorn to come up.
  for _ in $(seq 1 45); do
    curl -sf --max-time 2 "http://localhost:${PORT}/api/health" >/dev/null 2>&1 && break
    sleep 2
  done
fi

# 2. Find a browser that can run a dedicated app window.
#    Chromium-family: --app=<url> gives a chromeless SSB window (best).
CHROMIUM=""
for cand in google-chrome-stable google-chrome chromium chromium-browser brave-browser microsoft-edge; do
  if command -v "$cand" >/dev/null 2>&1; then CHROMIUM="$(command -v "$cand")"; break; fi
done
if [ -z "$CHROMIUM" ]; then
  # Playwright's bundled Chromium (installed for this project's UI tests).
  PW="$(ls -d "$HOME"/.cache/ms-playwright/chromium-*/chrome-linux64/chrome 2>/dev/null | head -1 || true)"
  [ -x "${PW:-}" ] && CHROMIUM="$PW"
fi

if [ -n "$CHROMIUM" ]; then
  exec "$CHROMIUM" --app="$URL" \
    --user-data-dir="$HOME/.config/agent-studio-app" \
    --class="AgentStudio" --no-first-run --no-default-browser-check
elif command -v firefox >/dev/null 2>&1; then
  # Firefox has no clean --app mode; a dedicated profile window is the closest.
  PROFILE="$HOME/.config/agent-studio-firefox"
  firefox -CreateProfile "agentstudio $PROFILE" >/dev/null 2>&1 || true
  exec firefox --profile "$PROFILE" --new-window "$URL"
else
  exec xdg-open "$URL"   # last resort: default browser, normal tab
fi
