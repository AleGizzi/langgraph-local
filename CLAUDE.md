# CLAUDE.md — Local Agents Studio

A **fully-local, single-user web app for building and running teams of AI agents
on local LLMs** (Ollama / LM Studio). Think "Dify, but offline on your own
hardware." No cloud, no auth, no telemetry. Flask API + SSE serving a React SPA;
LangGraph executes the teams.

```
Browser (React SPA) ──HTTP/SSE──► Flask (app.py) ──► engine.py (LangGraph)
                                       │                  └─► providers.py ─► Ollama / LM Studio
                                       └─► storage.py (SQLite) · knowledge.py (MD vault) · imagegen.py (Fooocus)
```

## Where to read next — load only what you need

**`docs/index.md` is the router.** Find the feature you're touching there and
read *only that feature folder's README* (files, API, mechanics, gotchas,
verification — self-sufficient). Cross-cutting: `docs/architecture.md` (system
mechanics), `docs/extending.md` (add a tool/skill/topology/provider/page),
`docs/operations.md` (run/deploy/env), `docs/handover.md` (state, roadmap,
non-negotiables). Do not preload everything.

## Repo map (one line each)

| Path | Role |
|------|------|
| `app.py` | ALL Flask routes + SSE; validation lives here |
| `engine.py` | Team → LangGraph compilation; topologies; tool loop + delegation; file extraction; chat |
| `runmanager.py` | Background run threads, event fan-out, persistence |
| `providers.py` | Model discovery, `make_llm()`, hyperparameter specs |
| `storage.py` | SQLite (teams/runs/events/personas/skills/chats), new-connection-per-op |
| `tools.py` | Builtin tools + `custom_tools/*.py` loader + knowledge/image tools |
| `knowledge.py` | Markdown vault (Obsidian-compatible) |
| `sysinfo.py` / `catalog.py` / `installer.py` | Hardware assessment / live model catalog / installs |
| `wizard.py` | LLM drafting of skills, tools, whole teams (normalize, never trust) |
| `imagegen.py` | Fooocus install/launch/generate over HTTP |
| `seeds.py` | Default teams/personas/skills on first launch |
| `frontend/src/` | React 18 + Vite SPA, hash routing, no router lib |

## Invariants (violating these reintroduces solved bugs)

1. **Parse all model output defensively** — repair with fallbacks, never bare
   `json.loads`. See `wizard._normalize_team`, `engine.parse_route`.
2. **Keep the watchdog & concurrency caps** (`LLM_IDLE_TIMEOUT`, GPU-aware
   parallel capacity) — real hardware wedged without them.
3. **Tokens stream, only durable events persist** (`runmanager.PERSISTED`);
   replay-then-live makes the UI refresh-safe.
4. **Storage opens a new SQLite connection per op** — don't share handles.
5. **File delivery is the `File: path` + fenced-block convention** parsed by
   `engine.extract_files` — don't break it when editing agent rules.
6. **Fully local** — only outbound calls: model inference, downloads,
   ollama.com catalog scrape.
7. **Frontend uses CSS variables only** (dark mode) and the `api()`/`toast()`
   helpers; full-viewport pages follow the `flow`/`pixel` pattern in `App.jsx`.

## Working here

- Run: `./run.sh` · restart: `./restart.sh` · Docker: `docker compose up -d` ·
  dev: `python app.py` + `cd frontend && npm run dev`.
- **Verify by driving the app against a real model** (`qwen2.5:7b` is the
  workhorse; tinyllama is too weak for tools) — imports passing ≠ verified.
  UI checks: Playwright in the venv. Clean up test teams/runs/notes after.
- **Docs same-commit rule**: your change updates the owning feature README in
  the same commit (`docs/index.md` § keeping documentation current).
