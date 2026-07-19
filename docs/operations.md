# Local Agents Studio — Operations Guide

Local Agents Studio is a Flask + LangGraph web app for orchestrating multi-agent teams on local LLMs (Ollama / LM Studio). It is single-user, fully local, and runs on port 5860 by default.

## Running Natively (Linux)

### Prerequisites

- **Python 3.10+** (venv will be created automatically)
- **Node 20+** — needed to rebuild the React frontend, and required by the
  `browser` tool's MCP server (`@playwright/mcp@latest`). On this machine Node
  22 LTS is installed system-wide in `/usr/local` (extracted from the official
  tarball; `/usr/local/bin/node`, ahead of the distro's Node 18 in `/usr/bin`,
  which stays as a fallback). To run the browser tool on Node 18 instead, set
  `PLAYWRIGHT_MCP_SPEC=@playwright/mcp@0.0.29`. First browser use downloads
  Chromium (`npx playwright install chromium`).
- **Ollama** (http://localhost:11434) or **LM Studio** (http://localhost:1234)
  - At least one must be running, or reachable at custom `OLLAMA_URL` / `LMSTUDIO_URL`
  - Download: [Ollama](https://ollama.ai) | [LM Studio](https://lmstudio.ai)

### Quick Start

```bash
cd ~/langgraph-local
./run.sh
# Opens http://127.0.0.1:5860
```

On first run, the script:
1. Creates `.venv` and installs `requirements.txt`
2. Builds the React frontend into `static/dist/` (if sources changed)
3. Checks if Ollama or LM Studio are reachable
4. Starts gunicorn with 1 worker, 16 threads (for SSE streaming), no timeout

If no provider is detected, the Setup page guides you to install Ollama automatically.

### Restart Script

For a clean restart (useful after model installation or if the app becomes unresponsive):

```bash
./restart.sh
```

This:
- Stops any running gunicorn process on the current PORT
- Waits up to 30 seconds for graceful shutdown
- Force-kills after timeout with `-9`
- Starts the app in the background, logging to `data/server.log`
- Waits up to 20 seconds for `/api/health` response
- Exits with status 1 if startup fails

> **Importing `app` has side effects.** `app.py` runs its startup work
> (`mark_stale_runs`, seeding, the image-queue worker) at module import — a
> bare `python -c "import app"` syntax check once marked a live team run
> "Interrupted by server restart". For tooling imports set
> `AGENTS_SKIP_STARTUP=1`, which skips all of it.

### Systemd User Service (Optional)

For persistent background operation without keeping a terminal open:

```bash
mkdir -p ~/.config/systemd/user
cp deploy/local-agents-studio.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now local-agents-studio
```

Check status and logs:
```bash
systemctl --user status local-agents-studio
journalctl --user -u local-agents-studio -f  # Follow logs
```

The service runs with `PORT=5860` and restarts automatically on failure (with 3-second delay between attempts).

### Desktop App (Pop!_OS / GNOME)

You can also click **Settings → Hardware tab → Install as app** in the running
app, which runs this same installer for you.

Install Agent Studio as a launcher entry so it opens like any other app:

```bash
./deploy/install-desktop-app.sh
```

This copies `deploy/agent-studio.svg` to `~/.local/share/icons/` and writes
`~/.local/share/applications/agent-studio.desktop` (no root needed). "Agent
Studio" then appears in the app launcher / dock. Clicking it runs
`deploy/agent-studio-launch.sh`, which starts the server via `run.sh` if it
isn't already answering `/api/health`, waits for it, then opens a dedicated
app window.

Browser used for the window, in order of preference:
1. A Chromium-family browser (`google-chrome`, `chromium`, `brave`, `edge`) in
   `--app=<url>` mode — a chromeless site-specific window, the most app-like.
2. This project's **Playwright Chromium** (`~/.cache/ms-playwright/chromium-*`),
   also in `--app` mode — so it works even with only Firefox installed
   system-wide (Playwright is a dev dependency here).
3. Firefox with a dedicated profile window.
4. `xdg-open` — the default browser in a normal tab (last resort).

The app-mode window uses its own profile at `~/.config/agent-studio-app`, so it
stays signed-in/independent of your main browser. `StartupWMClass=AgentStudio`
lets the shell match the window to the launcher icon.

## Running with Docker

Docker is the recommended way to run on Windows, macOS, or to avoid Python/Node dependency management. The bundled Ollama service means you don't need to install it separately.

### Quick Start

```bash
cd ~/langgraph-local
docker compose up -d
# Wait 30–60 seconds for Ollama to start, then open http://localhost:5860
```

The `docker-compose.yml` defines:
- **app**: Flask app built from the Dockerfile
- **ollama**: Official Ollama image with persistent model storage

Both services restart automatically unless stopped manually.

The app image bundles **Node 22** (copied from `node:22-slim`) and **Playwright
Chromium + its OS libraries**, so the `browser` tool works inside the container
with no extra setup. That browser layer adds ~400MB; if you never use the
`browser` tool, delete the `playwright ... install --with-deps chromium` block
in the Dockerfile to slim the image.

### Stop and Restart

```bash
docker compose down    # Stop all services
docker compose up -d   # Restart
```

### GPU Acceleration (NVIDIA)

If you have an NVIDIA GPU and `nvidia-container-toolkit` installed, enable GPU support:

```bash
# Edit docker-compose.yml: uncomment the deploy block under the ollama service
#   deploy:
#     resources:
#       reservations:
#         devices:
#           - driver: nvidia
#             count: all
#             capabilities: [gpu]

docker compose up -d
```

Verify GPU is detected:
```bash
docker exec langgraph-local-ollama-1 ollama run llama2 "Show system info"
```

### View Logs

```bash
docker compose logs -f app       # Flask app logs
docker compose logs -f ollama    # Ollama service logs
```

## Environment Variables

All paths default to subdirectories under the project root. In Docker, these are pre-configured to point to mounted volumes.

| Variable | Default | Purpose |
|----------|---------|---------|
| `PORT` | `5860` | HTTP port (also used in restart.sh and systemd service) |
| `OLLAMA_URL` | `http://localhost:11434` | Ollama HTTP API base URL |
| `LMSTUDIO_URL` | `http://localhost:1234/v1` | LM Studio OpenAI-compatible API endpoint |
| `LLM_IDLE_TIMEOUT` | `420` | Seconds to wait for a token before aborting a streaming call; prevents hangs when Ollama is overloaded |
| `AGENTS_DB` | `{project}/data/agents.db` | SQLite database for teams, runs, and events |
| `AGENTS_WORKSPACES` | `{project}/data/workspaces` | Directory containing per-run workspace directories |
| `AGENTS_KNOWLEDGE` | `{project}/data/knowledge` | Markdown vault (Obsidian/Logseq-compatible) for shared knowledge |
| `AGENTS_CUSTOM_TOOLS` | `{project}/custom_tools` | Directory of custom tool Python modules |
| `OLLAMA_MODELS` | (auto-detected) | Path to Ollama models directory; used by system info to estimate storage |
| `RUNNING_IN_DOCKER` | (unset) | Set to `1` inside Docker; disables native provider installer |
| `FOOOCUS_URL` | `http://localhost:8888` | Fooocus-API server base URL for image generation |
| `FOOOCUS_DIR` | `~/.local/share/local-agents-studio/fooocus-api` | Directory where Fooocus-API repo is cloned and venv is created |
| `IMAGES_DIR` | `{project}/data/images` | Directory for storing generated images |
| `IMAGEGEN_TIMEOUT` | `2400` | Timeout in seconds for polling image generation jobs; increase for low-VRAM GPUs |
| `IMAGEGEN_PERFORMANCE` | `Extreme Speed` | Default Fooocus performance preset (one of: `Extreme Speed`, `Lightning`, `Hyper-SD`, `Speed`, `Quality`) |
| `TOOL_DELEGATE_MODEL` | (auto-picked) | Executor model for tool delegation, `provider::model` or bare model name; auto-selects a tool-capable model when unset |
| `FOOOCUS_LORAS_DIR` | `<FOOOCUS_DIR>/repositories/Fooocus/models/loras` | Where downloaded style LoRAs are stored |
| `CIVITAI_API_KEY` | (unset) | Bearer token for Civitai LoRA downloads that require a logged-in account |

### Setting Environment Variables

**Natively:**
```bash
export PORT=5861 OLLAMA_URL=http://192.168.1.100:11434
./run.sh
```

**Systemd service:**
Edit `~/.config/systemd/user/local-agents-studio.service`, change the `Environment=PORT=5860` line, then:
```bash
systemctl --user daemon-reload
systemctl --user restart local-agents-studio
```

**Docker:**
Edit `docker-compose.yml` app service `environment:` section, or use `--env-file`:
```bash
docker compose up -d --env-file .env.production
```

## Data & Filesystem Layout

### Core Data (Persistent)

- **`data/agents.db`**  
  SQLite database. Stores:
  - Team definitions (agents, topology, settings)
  - Run history (inputs, outputs, events)
  - Run events (start, agent decisions, tool calls, tokens)

- **`data/workspaces/`**  
  One subdirectory per run ID. Agents read/write files here during execution.

- **`data/knowledge/`**  
  Markdown vault (`.md` files with YAML frontmatter and `[[wikilinks]]`).
  - Agents have `knowledge_search`, `knowledge_read`, `knowledge_write` tools
  - Agents auto-export findings to `runs/` subdirectory
  - Can be opened directly in Obsidian, Logseq, or Foam

- **`data/images/`**  
  Generated images from Fooocus-API (text-to-image). Images persist independently of the Fooocus-API process.
  Directory configured via `IMAGES_DIR` environment variable.

- **`custom_tools/`**  
  Python modules. Add `.py` files with `@tool` functions:
  ```python
  from langchain_core.tools import tool
  
  @tool
  def my_tool(arg: str) -> str:
      """Do something with arg."""
      return f"Result: {arg}"
  ```
  Agents see these automatically and can call them.

### Build Output (Can Rebuild)

- **`static/dist/`**  
  Built React frontend (output of `npm run build` in `frontend/`).
  Deleted when frontend sources change; rebuilt automatically by `run.sh`.

### Log Files

- **`data/server.log`**  
  Gunicorn access and error logs when using `restart.sh`.
  Not created by `run.sh` (logs go to stdout).

- **`data/model_catalog.json`**  
  Cached list of available models (populated on first Settings page load).

## Backup & Restore

### Backup

All user data lives in `data/` and `custom_tools/`. Back them up regularly:

```bash
tar czf ~/agents-backup-$(date +%Y%m%d).tar.gz \
  ~/langgraph-local/data \
  ~/langgraph-local/custom_tools
```

Or use your file manager / cloud sync (Synology, Nextcloud, Dropbox, etc.):
- Add `data/` to sync (includes teams, runs, knowledge, generated images)
- Add `custom_tools/` to sync
- Exclude `data/model_catalog.json` (ephemeral cache)

To also backup the Fooocus-API installation (large, optional):
```bash
tar czf ~/fooocus-backup-$(date +%Y%m%d).tar.gz ~/.local/share/local-agents-studio/
```

### Restore

```bash
cd ~/langgraph-local
tar xzf ~/agents-backup-20260707.tar.gz
```

Then restart the app. Teams, runs, knowledge, and custom tools are restored.

## Troubleshooting

### No Local Provider Detected

**Symptom:** "ℹ No local model provider detected (Ollama / LM Studio)" on startup, and Settings page shows no models.

**Fix:**
1. Ensure Ollama or LM Studio is running:
   ```bash
   curl http://localhost:11434/api/version  # Ollama
   curl http://localhost:1234/v1/models     # LM Studio
   ```
2. If running locally but on a different port, set `OLLAMA_URL` or `LMSTUDIO_URL`:
   ```bash
   export OLLAMA_URL=http://localhost:11434
   ./run.sh
   ```
3. If running on a different machine, use its IP:
   ```bash
   export OLLAMA_URL=http://192.168.1.100:11434
   ./run.sh
   ```
4. On first visit, the Setup page offers "Install Ollama automatically" (native only, not in Docker).

### Port Already in Use

**Symptom:** `Address already in use` when starting the app.

**Quick fix (native):**
```bash
./restart.sh              # Kills existing process and restarts
```

**Or change the port:**
```bash
export PORT=5861
./run.sh
```

**Check what's using port 5860:**
```bash
lsof -i :5860
netstat -tlnp | grep 5860
```

### Run Stalls or Hangs

**Symptom:** A run starts but makes no progress; "streaming" mode in the UI shows no updates.

**Cause:** The LLM (Ollama/LM Studio) stopped sending tokens for > `LLM_IDLE_TIMEOUT` seconds (default 420s = 7 minutes).
- On small GPUs, evaluating a long prompt can take minutes before the first token appears.
- On CPU-only machines, larger models (13B+) may take very long.

**Fix:**
1. Increase the watchdog timeout:
   ```bash
   export LLM_IDLE_TIMEOUT=900  # 15 minutes
   ./run.sh
   ```
2. Or use a smaller/faster model in Settings.

### Model Doesn't Support Tools

**Symptom:** Agent fails with "model does not support tools" or similar.

**Cause:** Not all local models support tool calling. Recommended models:
- **Ollama:** `llama2:latest`, `mistral:latest`, `neural-chat:latest` (all support tools)
- **LM Studio:** Any model labeled "3B" or larger usually works; check model card for tool support

**Fix:** Download a different model in Settings.

### Docker Container Won't Start

**Symptom:** `docker compose up -d` returns immediately with error or container is stuck restarting.

**Check logs:**
```bash
docker compose logs app
```

**Common issues:**
- Port 5860 already in use: change in docker-compose.yml `ports:` section
- Port 11434 (Ollama) already in use: uncomment the `ports:` under ollama service
- Out of disk space: run `docker system prune` to free cache
- Ollama takes time to start (30–60s): wait longer before opening the browser

### Data Persists Across Restarts (Docker)

Docker uses named volumes (`app_data`, `ollama_models`) that persist even when containers are stopped:

```bash
docker compose down      # Stops containers (data stays)
docker compose up -d     # Restarts; data is still there
```

To **wipe all data** and start fresh:
```bash
docker compose down -v   # -v removes volumes
```

---

For more information on teams, agents, and runs, see [knowledge-base.md](knowledge-base.md).
