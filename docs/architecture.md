# Architecture

A deep dive into how Local Agents Studio works. Read `CLAUDE.md` first for the
mental model and vocabulary; this document explains the machinery.

## Process & request topology

One Python process (gunicorn, 1 worker, 16 threads) serves everything:

- **Static SPA** — Flask serves `static/dist/index.html` and assets at `/` and
  `/static/dist/*`. The React app is a pure client; all state comes from `/api`.
- **JSON API** — synchronous request/response for CRUD and queries.
- **SSE streams** — two long-lived endpoints (`/api/runs/<id>/events`,
  `/api/chat`) stream `text/event-stream`. Threads (not async) handle these;
  that's why gunicorn runs with `--threads 16 --timeout 0`.

There is no auth, no session, no CSRF — it binds to `127.0.0.1` and is single-user
by design. Do not expose it to a network without adding your own front door.

## The run lifecycle (the heart of the app)

When you POST `/api/teams/<id>/runs`:

1. **`app.py`** validates the task and calls `runmanager.manager.start(team, task)`.
2. **`runmanager.RunManager.start`** creates a `runs` row (status `running`),
   builds an `ActiveRun` (holds subscribers + a cancel event), and spawns a
   **daemon thread** running `_execute`. It returns the `run_id` immediately.
3. **`_execute`** decides concurrency (1, or the hardware-assessed capacity if the
   team's `parallel` setting is on), then constructs a `TeamRunner` and calls
   `runner.run()`. Every event the runner emits goes through a local `emit()`:
   - durable event types (`runmanager.PERSISTED`) are written to the `events` table
   - **all** events are published to the `ActiveRun`'s subscriber queues
4. **`engine.TeamRunner.run`** compiles the team into a LangGraph `StateGraph` for
   its topology and invokes it. Node functions call the model via `_stream_call`,
   emitting `agent_start`, `token`, `tool_call`, `tool_result`, `agent_end`,
   `decision` events as they go.
5. On completion `_execute` writes the deliverable to the run workspace, archives it
   to the **knowledge vault** (`knowledge.export_run`), sets the run status, and
   emits `run_end`. The `ActiveRun` is closed (sentinel pushed to subscribers).

### Event fan-out & SSE

`ActiveRun` holds a list of subscriber `queue.Queue`s. Each SSE client that hits
`/api/runs/<id>/events` gets its own queue via `subscribe()`. The endpoint:

1. **Replays** persisted events from the `events` table first (so a client that
   connects late, or reconnects after a refresh, sees the whole run so far).
2. Then drains its live queue until the run-end sentinel.

This replay-then-live design is what makes the UI **refresh-safe**: durable events
are the source of truth, live tokens are a bonus layer on top. Tokens are
deliberately *not* persisted (`PERSISTED` excludes `token`) — replaying a finished
run shows agent outputs as rendered Markdown, not a token stream.

A finished run has no `ActiveRun`; the endpoint detects this and emits a synthetic
`run_end` from the stored final, so the same client code handles live and historical.

### Cancellation

`ActiveRun.cancel_event` is a `threading.Event`. `TeamRunner._check_cancel()` is
polled between tokens and tool rounds and raises `RunCancelled`. Because it only
checks between streamed chunks, a stop can lag a few seconds on CPU while the model
finishes prompt evaluation — this is expected and documented in the UI.

## The engine: compiling teams to graphs

`engine.py` turns a team dict into a compiled LangGraph. The shared state is
`TeamState`, whose `history` field uses an **add-reducer**:

```python
history: Annotated[list, operator.add]   # [{agent, content, ts}]
```

This matters for `graph` topology: parallel branches each return
`{"history": [one_entry]}` and LangGraph merges them by concatenation. Ordering is
reconstructed from each entry's `ts` (wall-clock), since concurrent appends have no
inherent order. All four topology builders:

- **`_build_single`** — one node, START → agent → END.
- **`_build_pipeline`** — agents chained in order. If `quality_loop` is on and there
  are ≥2 agents, the last agent becomes a **reviewer**: it emits `APPROVED`/`REVISE`,
  and a conditional edge loops back to the first worker (bounded by `max_revisions`)
  or finalizes. The reviewer's verdict is parsed defensively (starts-with `APPROVED`).
- **`_build_supervisor`** — agent[0] is the supervisor. It runs in a loop: each turn
  it emits JSON `{next, instruction}` choosing a worker or `FINISH`. `parse_route`
  extracts this defensively (regex for the JSON block, then fallbacks: literal
  `FINISH`, first worker name mentioned, else FINISH). Bounded by `max_steps`. On
  FINISH a synthesis node writes the final answer.
- **`_build_graph`** — an arbitrary DAG from `team["graph"]`. Incoming edges are
  grouped per target; a target with multiple sources becomes a LangGraph join (waits
  for all). `start`/`end` are virtual. A `_finalize` node collects the output(s) of
  whatever feeds `end`.

### The tool loop

`_stream_call` → `_tool_loop` runs a bounded (`MAX_TOOL_ROUNDS`) loop: stream the
model; if it emits tool calls, execute each resolved tool, append `ToolMessage`s, and
loop; otherwise return the content. Reasoning-model `<think>…</think>` blocks are
stripped from anything passed between agents (`_strip_reasoning`). The whole call is
wrapped by the **idle watchdog** (see below).

### Chat

`engine.chat_stream` is a standalone generator (not a graph) reusing the same
provider/tool/skill machinery for the Chat page: it takes a full message history and
yields the same event types for one assistant turn. `/api/chat` streams these as SSE.

## Concurrency & the watchdog

Two independent mechanisms keep parallel runs safe on modest hardware:

1. **LLM semaphore** (`TeamRunner.llm_gate`). Sized to 1 normally, or the
   hardware-assessed capacity (`sysinfo.assess()["parallel"]["capacity"]`) when the
   team's `parallel` setting is on. Every model call acquires it, so concurrency is
   capped regardless of how wide the graph fans out. Capacity is capped at 2 on GPUs
   whose VRAM is smaller than a typical model (partial-offload thrash) — this was
   found empirically; three concurrent 7B requests wedged a 4 GB GPU.
2. **Idle-stream watchdog** (`providers.LLM_IDLE_TIMEOUT`, default 420s). Passed as an
   httpx read timeout so a generation that produces no token for that long raises. The
   tool loop translates the timeout into a clear error and **retries once** (Ollama
   caches the evaluated prompt prefix, so the retry is cheap). Without this, a wedged
   Ollama could hang a run thread forever.

## Persistence model (SQLite)

`storage.py` uses **a fresh connection per operation** in WAL mode — deliberately, so
any run thread can call it safely without a shared handle. Tables:

- `teams` — includes a JSON `agents` list, `settings`, and a nullable `graph` (JSON).
- `runs` — one row per execution; `final`, `error`, timestamps, status.
- `events` — durable run events (`run_id, seq, type, agent, content, meta`), replayed
  for SSE.
- `personas`, `skills` — reusable agent definitions and prompt-injection blocks.
- `chats` — persisted chat conversations (agent config + message list).

Schema is created idempotently on startup; lightweight migrations (e.g. adding the
`graph` and `personas.skills` columns) run via `PRAGMA table_info` checks in
`init_db()`. On startup, `mark_stale_runs()` flips any run left `running` by a crash
to `error`.

## The catalog & installer subsystems (no-AI model discovery)

- **`catalog.py`** scrapes `ollama.com/library` with plain HTTP + regex (explicitly no
  AI): one request lists every model with sizes/capabilities/pulls; the top ~45 get
  exact per-tag sizes. Results cache to `data/model_catalog.json` and auto-refresh
  when older than 7 days. A built-in snapshot is the offline fallback. `annotate()`
  derives use-case **categories** (from capability tags + name heuristics) and a
  per-category **ranking** (popularity among models that run on this machine), and
  builds the **dream team**. `image_models()` assesses a curated image-gen list
  against VRAM (a separate ecosystem — ComfyUI/Fooocus, not Ollama).
- **`sysinfo.py`** detects CPU/RAM/GPU, locates provider installs (ports, paths,
  versions), and computes model **suitability verdicts** (`great`/`ok`/`tight`/`no`)
  from a Q4 sizing heuristic plus the parallel capacity.
- **`installer.py`** downloads models with live progress: Ollama via its streamed
  `/api/pull`, LM Studio via the `lms` CLI. It also handles **first-run provider
  install** — fetching the Ollama runtime user-level (no sudo) from the latest GitHub
  release (handles `.tgz`/`.tar.zst`), starting it, and health-checking; LM Studio via
  its AppImage. Installs run in background threads; the UI polls `/api/install/status`.

## Knowledge vault

`knowledge.py` is a folder of Markdown files with YAML frontmatter and `[[wikilinks]]`
— structurally an Obsidian/Logseq vault, no integration needed. Run deliverables
auto-archive here; agents get `knowledge_search`/`_read`/`_write` tools. Search is
token-ranked (not full-phrase). See `docs/knowledge-base.md`.

## Frontend

React 18 + Vite SPA, hash-routed, no router library, no build-time API client. The
full page/component inventory and shared mechanisms (the SSE streaming hook, the
markdown renderer, `AgentFields` as the reusable editor, the two canvas views) are in
`docs/frontend.md`.

## Data flow summary

```
Team (DB) ──► engine compiles ──► LangGraph StateGraph
                                        │ node calls
                                        ▼
                                  providers.make_llm ──► Ollama/LM Studio
                                        │ emits events
                                        ▼
runmanager: persist durable events (SQLite) + fan out to SSE subscribers
                                        │
                                        ▼
Browser: replay persisted + live tokens ──► rendered timeline / pixel sprites
                                        │ on run_end
                                        ▼
knowledge.export_run ──► Markdown note in the vault (Obsidian-ready)
```
