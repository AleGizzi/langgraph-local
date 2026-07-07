# CLAUDE.md — Local Agents Studio

> Onboarding for anyone (human or AI agent) maintaining this codebase. Read this
> first, then `docs/architecture.md` for the deep dive. Written as a handover so
> you can be productive without reverse-engineering the whole thing.

## What this is

A **fully-local, single-user web app for building and running teams of AI agents
on local LLMs** (Ollama and/or LM Studio). Think "Dify, but offline and on your
own hardware." No cloud, no API keys, no auth, no telemetry. You compose teams of
agents (each with a model, prompt, tools, skills, hyperparameters), wire them into
topologies, and run them on a task while watching the work stream live.

The whole product runs on one machine: a Flask backend serves a React SPA and
talks to a local model server over HTTP.

## The 30-second mental model

```
Browser (React SPA)  ──HTTP/SSE──►  Flask (app.py)  ──►  engine.py (LangGraph)
                                          │                     │
                                          │                     └─► providers.py ─► Ollama / LM Studio
                                          └─► storage.py (SQLite: teams, runs, personas, skills, chats)
```

A **team** is a list of **agents** plus a **topology** describing how they run.
`engine.py` compiles a team into a LangGraph `StateGraph` and executes it,
emitting events. `runmanager.py` runs each execution in a background thread and
fans events out to SSE subscribers while persisting the durable ones to SQLite.

## Repository map

| Path | Responsibility |
|------|----------------|
| `app.py` | **All** Flask routes + SSE endpoints. The single API surface. |
| `engine.py` | Compiles teams → LangGraph graphs; the 4 topologies; the chat generator. The brain. |
| `runmanager.py` | Background run threads, event fan-out (SSE), persistence, parallel-capacity gating. |
| `providers.py` | Model discovery + `make_llm()` factory + hyperparameter specs/validation. |
| `storage.py` | SQLite: teams, runs, events, personas, skills, chats. New-connection-per-op (thread-safe). |
| `tools.py` | Built-in agent tools + custom-tool loader (`custom_tools/*.py`) + knowledge tools. |
| `knowledge.py` | Markdown knowledge vault (Obsidian-compatible) + agent search/read/write. |
| `sysinfo.py` | Hardware detection, provider-install detection, model suitability verdicts. |
| `catalog.py` | Live Ollama-library scraper (no AI), model categories/ranking, dream team, image models. |
| `installer.py` | Model pulls (Ollama/LM Studio) + first-run provider install, all with progress. |
| `wizard.py` | LLM-assisted skill/tool drafting with validation + auto-fix. |
| `seeds.py` | Default teams, personas, skills created on first launch. |
| `frontend/src/` | React 18 + Vite SPA. See `docs/frontend.md`. |
| `docs/` | This handover library. |

## Core concepts (the vocabulary)

- **Agent**: `{name, role, provider, model, system_prompt, params, tools, skills}`.
  `params` are LLM hyperparameters (see `providers.PARAM_SPECS`). Agents are
  embedded in a team; they are not stored separately.
- **Persona**: a *reusable, saved* agent definition. Applying a persona copies its
  fields onto an agent. Stored in the `personas` table.
- **Skill**: a named block of prompt instructions injected into an agent's system
  prompt under a `## Skill` heading. Behavior, not capability. Stored in `skills`.
- **Tool**: a Python function an agent can call (function calling). Built-ins live
  in `tools.py`; custom tools are `@tool`-decorated functions in `custom_tools/*.py`,
  auto-discovered. The `knowledge` and `files` entries are *bundles* of tools.
- **Topology**: how a team runs. Four kinds, all built in `engine.py`:
  - `single` — one agent answers.
  - `pipeline` — agents in sequence; optional **quality loop** where the last
    agent reviews and can send work back (bounded revisions).
  - `supervisor` — first agent delegates dynamically to workers, then synthesizes.
  - `graph` — an arbitrary DAG (`{nodes, edges, positions}`) with fan-out/fan-in.
    This is what the visual canvas and pixel studio edit.
- **Run**: one execution of a team on a task. Streams events live; persists to the
  `runs` + `events` tables. The final deliverable auto-archives to the knowledge vault.

## Conventions & invariants (respect these)

1. **All routes go in `app.py`.** There is no blueprint split. Validation happens
   in `app.py` (`_validate_team`, `_validate_persona`, etc.) before touching storage.
2. **`storage.py` opens a new SQLite connection per operation** (WAL mode). This is
   deliberate — it makes storage safe to call from any run thread. Don't introduce a
   shared connection.
3. **Local 7B models produce unreliable JSON.** Every place that parses model output
   for control flow (supervisor routing, review verdicts) parses *defensively* and
   falls back to something sane. Never `json.loads()` a model response without a
   fallback. See `engine._build_supervisor.parse_route`.
4. **Tokens stream but are not persisted.** `runmanager.PERSISTED` lists the durable
   event types; `token` is intentionally excluded. Durable events are replayed on
   reconnect, so the UI is refresh-safe. Keep this split.
5. **LLM calls are gated by a semaphore** (`engine.TeamRunner.llm_gate`) sized from
   the hardware assessment when the team's `parallel` setting is on. Concurrency is
   independent of graph shape.
6. **An idle-stream watchdog** (`providers.LLM_IDLE_TIMEOUT`, default 420s) aborts a
   stalled generation and retries once. This exists because parallel 7B requests can
   wedge Ollama on small GPUs. Don't remove it.
7. **History state uses an add-reducer** (`Annotated[list, operator.add]`) so parallel
   graph branches can append concurrently. Order is recovered via each entry's `ts`.
8. **The frontend has no build-time API client** — it uses a hand-rolled `api()`
   helper (`frontend/src/lib/api.js`). Routing is hash-based, no router library.
9. **Everything is offline-first.** The only outbound network calls are: model
   inference (local), the Ollama library scrape (`catalog.py`), and model downloads
   (`installer.py`). No analytics, no fonts, no CDNs.

## Running it

```bash
./run.sh            # native: builds frontend if stale, launches gunicorn on :5860
./restart.sh        # clean restart (waits for the port to free)
docker compose up -d # containerized, bundles Ollama
```

Dev with hot reload: `python app.py` (API on :5860) + `cd frontend && npm run dev`
(UI on :5173, proxies `/api`). Full details in `docs/operations.md`.

## Testing / verifying changes

There is no unit-test suite; this app is verified by **driving it**. The pattern used
throughout its history (see git log) is:
- Backend logic: exercise the module directly with `.venv/bin/python -c "..."`.
- API: `curl` the endpoint and inspect JSON.
- A real run: POST a run, poll `/api/runs/<id>` until done, assert on events/final.
- UI: Playwright (installed in the venv, not in requirements) drives the real page and
  screenshots it; assert on DOM + zero console errors.

Always verify against a **real model run**, not just imports. `qwen2.5:7b` is the
workhorse; `tinyllama` is fast but too weak for tool use.

## Extending the app

See `docs/extending.md` for step-by-step recipes: adding a tool, a skill, a topology,
a provider, an API route, or a frontend page. The short version: most features touch
`app.py` (route) + one backend module + one frontend page/component, and are wired
through `seeds.py` if they need defaults.

## Known sharp edges

- **LM Studio automation is best-effort.** Its `lms` CLI is less predictable than
  Ollama's HTTP API; Ollama is the reliable default everywhere.
- **The Ollama library scraper parses HTML** (`catalog.py`). If ollama.com changes
  its markup, the scraper degrades to the built-in snapshot — check `_state["error"]`.
- **Model asset naming changes.** `installer.py` resolves the latest Ollama release via
  the GitHub API and handles both `.tgz` and `.tar.zst`; if a new format appears, extend
  `_resolve_ollama_asset` / `_extract_archive`.
- **The pixel studio and flow canvas both edit the same `graph` field.** Saving from one
  overwrites positions; they share the graph model in the team object.
