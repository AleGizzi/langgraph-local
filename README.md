# Local Agents Studio

A Dify-inspired web UI for **LangGraph agent teams** running entirely on your machine,
powered by **Ollama** and/or **LM Studio**. No cloud, no API keys, no telemetry.

![stack](https://img.shields.io/badge/stack-Flask%20%2B%20LangGraph%20%2B%20vanilla%20JS-155eef)

## What it does

- **Teams**: compose multi-agent teams in the browser — each agent gets a name, role,
  local model (any Ollama or LM Studio chat model), system prompt, temperature and tools.
- **Topologies**:
  - `pipeline` — agents run in order, each seeing the task plus all prior work.
    Optional **quality loop**: the last agent acts as reviewer and sends work back
    with concrete feedback until it approves (bounded by *max revisions*).
  - `supervisor` — the first agent delegates dynamically to workers with specific
    instructions until it decides to finish, then synthesizes the final answer.
  - `single` — one agent, optionally with tools.
- **Live streaming**: token-by-token output per agent over SSE, with tool calls,
  routing decisions and revision loops visualized as they happen.
- **Tools**: calculator, current datetime, HTTP fetch, and sandboxed file read/write
  in a per-run workspace. The final deliverable is always saved as `final_output.md`.
- **History**: every run and its events are persisted in SQLite and replayable.

## Requirements

- Python 3.10+
- [Ollama](https://ollama.com) running on `localhost:11434` (default), and/or
- [LM Studio](https://lmstudio.ai) local server on `localhost:1234`

Recommended models for CPU machines:

```bash
ollama pull qwen2.5:7b          # general agents (default for seed teams)
ollama pull qwen2.5-coder:7b    # coding agents
```

## Run

```bash
./run.sh                        # production: gunicorn, http://127.0.0.1:5860
# or for development:
.venv/bin/python app.py
```

First launch creates the SQLite DB (`data/agents.db`) and seeds four example teams:
Research & Report, Code Squad, Task Force (supervisor demo) and Quick Assistant.

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
static/           vanilla JS SPA (no build step) — Dify-inspired UI
app.py            Flask routes + SSE endpoint
runmanager.py     background run threads, event fan-out, persistence
engine.py         LangGraph graph builder (pipeline / supervisor / single)
providers.py      model discovery + LLM factory (Ollama, LM Studio)
tools.py          safe agent tools (ast calculator, sandboxed files, http)
storage.py        SQLite (teams, runs, events)
seeds.py          default teams
```

Design notes:

- Local 7B models emit unreliable JSON, so supervisor routing parses defensively
  and always falls back to something sane (never crashes a run).
- `<think>…</think>` blocks from reasoning models (DeepSeek-R1) are stripped from
  outputs passed between agents.
- Tokens stream live but are not persisted; durable events (agent outputs, tool
  calls, decisions) are stored and replayed on reconnect — refresh-safe.
- Stopping a run takes effect at the next streamed token, so on CPU it can lag
  a few seconds while the model finishes prompt evaluation.

## License

MIT
