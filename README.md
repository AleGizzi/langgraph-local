# Local Agents Studio

A Dify-inspired web UI for **LangGraph agent teams** running entirely on your machine,
powered by **Ollama** and/or **LM Studio**. No cloud, no API keys, no telemetry.

![stack](https://img.shields.io/badge/stack-Flask%20%2B%20LangGraph%20%2B%20React-155eef)

> **Maintainers:** start with [`CLAUDE.md`](CLAUDE.md) and the [`docs/`](docs/) library
> (architecture, API, frontend, operations, extending).

## What it does

- **Teams**: compose multi-agent teams in the browser — each agent gets a name, role,
  local model, system prompt, tools and full generation hyperparameters
  (temperature, top-p, top-k, context window, max tokens, repeat penalty, seed).
  Or just **describe the team in plain language** ("a PMO orchestrator, a devops
  team and a QA team") and the **AI wizard drafts the whole thing** — agents,
  prompts, models and topology — for you to review, refine and save.
- **Personas**: a library of reusable agent definitions with tuned default prompts
  (Researcher, Writer, Coder, Reviewer, Critic, …). Apply one to any agent with one
  click, or save your own agents back into the library.
- **Topologies**:
  - `pipeline` — agents run in order. Optional **quality loop**: the last agent
    reviews and sends work back with concrete feedback until it approves.
  - `supervisor` — the first agent delegates dynamically, then synthesizes.
  - `graph` — **custom pipelines on a visual canvas** (React Flow): drag agent
    nodes, connect branches, fan out and join like a Dify workflow.
  - `single` — one agent, optionally with tools.
- **Parallel execution**: a per-team toggle runs parallel branches concurrently.
  Concurrency is capped automatically by a live hardware assessment so the machine
  is never oversubscribed.
- **Setup page**: install guides for Ollama and LM Studio plus live detection of the
  local installations — running status, port, version, binary path, models folder
  and disk usage.
- **Settings page**: hardware report (CPU / RAM / GPU / VRAM / disk) and a
  **"can my PC run it?" model assessment** — verdicts and speed estimates for every
  installed model and a curated catalog, with a recommended sweet-spot model.
- **Skills & Tools page**: skills are reusable prompt directives attachable to any
  agent; tools are Python functions agents call — builtin or custom `.py` files in
  `custom_tools/` with an in-UI editor that validates on save. Both can be created
  manually or with the **AI wizard**: describe what you need in plain language and
  a local model drafts it (tool code is load-validated with one auto-fix round);
  you review, refine and save.
- **Image generation**: install **Fooocus** (SDXL) from the Models page with one
  click and generate images locally — from the UI or via the `generate_image` agent
  tool. VRAM-assessed against your hardware; see [`docs/image-generation.md`](docs/image-generation.md).
- **Live streaming**: token-by-token output per agent over SSE, with tool calls,
  routing decisions and revision loops visualized as they happen.
- **Tools**: calculator, current datetime, HTTP fetch, and sandboxed file read/write
  in a per-run workspace. The final deliverable is always saved as `final_output.md`.
- **History**: every run and its events are persisted in SQLite and replayable.

## Requirements

- Python 3.10+
- Node 18+ (only to build the frontend once)
- [Ollama](https://ollama.com) on `localhost:11434`, and/or
  [LM Studio](https://lmstudio.ai) local server on `localhost:1234`
  (the in-app **Setup** page has full install steps)

## Run

### Docker — easiest, works on Windows / macOS / Linux

Install [Docker Desktop](https://www.docker.com/products/docker-desktop/) (on
Windows it uses WSL2), then:

```bash
docker compose up -d
```

Open http://localhost:5860 — a bundled Ollama service is included, so just pick
a model from the **dream team** in Settings and it downloads with one click.
(GPU acceleration: uncomment the `deploy:` block in `docker-compose.yml`.)

### Native (Linux)

```bash
./run.sh        # builds the frontend if needed, then serves on http://127.0.0.1:5860
```

First time on a clean machine? Just run it — the app detects that no model
provider is installed and the **Setup page offers one-click installation**:
Ollama installs user-level (no sudo) and starts automatically; LM Studio is
downloaded ready to launch.

Development mode (hot reload):

```bash
.venv/bin/python app.py            # API on :5860
cd frontend && npm run dev         # UI on :5173, proxies /api
```

First launch creates `data/agents.db` and seeds five example teams (including the
parallel-graph “Panel Discussion”) and twelve builtin personas.

## Configuration (environment variables)

| Variable            | Default                        | Purpose                    |
|---------------------|--------------------------------|----------------------------|
| `PORT`              | `5860`                         | HTTP port                  |
| `OLLAMA_URL`        | `http://localhost:11434`       | Ollama endpoint            |
| `LMSTUDIO_URL`      | `http://localhost:1234/v1`     | LM Studio endpoint         |
| `AGENTS_DB`         | `./data/agents.db`             | SQLite path                |
| `AGENTS_WORKSPACES` | `./data/workspaces`            | Per-run file workspaces    |

## Architecture

```
frontend/         React 18 + Vite SPA (React Flow canvas for custom pipelines)
  src/pages/      Studio, TeamPage, Runs, RunDetail, Models, Personas, Setup, Settings
  src/components/ TeamEditor, GraphEditor, AgentFields, Timeline (SSE streaming)
app.py            Flask API + SSE endpoint (serves the built bundle from static/dist)
runmanager.py     background run threads, event fan-out, persistence
engine.py         LangGraph builder (pipeline / supervisor / graph DAG / single)
sysinfo.py        hardware specs, install detection, model suitability, parallel capacity
providers.py      model discovery + LLM factory + hyperparameter validation
tools.py          safe agent tools (ast calculator, sandboxed files, http)
storage.py        SQLite (teams, personas, runs, events)
seeds.py          default teams + persona library
deploy/           systemd user service
```

Design notes:

- Local 7B models emit unreliable JSON, so supervisor routing parses defensively
  and always falls back to something sane (never crashes a run).
- Graph state uses a LangGraph add-reducer so parallel branches can append to the
  shared history concurrently; fan-in nodes wait for all incoming branches.
- Actual LLM concurrency is gated by a semaphore sized from the hardware
  assessment (RAM + cores), independent of graph shape.
- `<think>…</think>` blocks from reasoning models (DeepSeek-R1) are stripped.
- Tokens stream live but are not persisted; durable events are stored and
  replayed on reconnect — refresh-safe. Stopping a run takes effect at the next
  streamed token.

## License

MIT
