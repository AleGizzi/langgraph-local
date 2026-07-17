#!/usr/bin/env bash
# Install Agent Studio as a Pop!_OS / GNOME desktop app: it then appears in the
# application launcher and dock like any other app. No root needed — everything
# goes under ~/.local. Run: ./deploy/install-desktop-app.sh
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
ICON_SRC="$APP_DIR/deploy/agent-studio.svg"
LAUNCH="$APP_DIR/deploy/agent-studio-launch.sh"

APPS="$HOME/.local/share/applications"
ICONS="$HOME/.local/share/icons/hicolor/scalable/apps"
mkdir -p "$APPS" "$ICONS"

chmod +x "$LAUNCH"
cp "$ICON_SRC" "$ICONS/agent-studio.svg"

cat > "$APPS/agent-studio.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Agent Studio
GenericName=Local AI Agent Teams
Comment=Build and run teams of AI agents on your local models
Exec=$LAUNCH
Icon=agent-studio
Terminal=false
Categories=Development;Utility;
StartupWMClass=AgentStudio
Keywords=AI;agents;LLM;Ollama;local;
EOF

chmod +x "$APPS/agent-studio.desktop"

# Refresh the desktop database + icon cache so it shows up immediately.
update-desktop-database "$APPS" >/dev/null 2>&1 || true
gtk-update-icon-cache -f "$HOME/.local/share/icons/hicolor" >/dev/null 2>&1 || true

echo "✓ Installed 'Agent Studio' to your applications menu."
echo "  Search for it in the launcher, or pin it to the dock."
echo "  Launching it starts the local server (if needed) and opens the app window."
