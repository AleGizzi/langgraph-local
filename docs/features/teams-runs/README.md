# Teams & Runs
> Part of Local Agents Studio. Read docs/index.md for the doc map.

## What it is

The core of the app: a **team** is a list of agents plus a **topology**
describing how they run; a **run** is one execution of a team on a task,
streamed live over SSE and persisted to SQLite. This covers team CRUD, the
LangGraph compilation of the four topologies, the run lifecycle (background
thread, event fan-out, cancellation), tool delegation for models that can't
call tools natively, file delivery into a run workspace, and the AI team
wizard.

## Key files

| Path | Role |
|------|------|
| `engine.py` | Compiles a team dict into a LangGraph `StateGraph` per topology; the tool loop; tool delegation; file extraction. |
| `runmanager.py` | Background run thread (`RunManager`/`ActiveRun`), SSE event fan-out, durable-event persistence, workspace creation, knowledge export on completion. |
| `storage.py` | `teams`, `runs`, `events` tables (see schema below). |
| `app.py` | `_validate_team`, `_validate_graph`, and every `/api/teams`, `/api/teams/<id>/runs`, `/api/runs*` route. |
| `wizard.py` | `draft_team` / `_normalize_team` — the team half of the AI wizard (see also `docs/features/skills-tools/`). |
| `seeds.py` | `SEED_TEAMS` — 5 default teams (one per topology, one graph) created on first launch. |
| `frontend/src/pages/Teams.jsx` | Team grid; create/edit/duplicate/delete. |
| `frontend/src/pages/TeamPage.jsx` | Single team: topology preview, task box, run launcher + live `Timeline`. |
| `frontend/src/pages/Runs.jsx` | Run history table. |
| `frontend/src/pages/RunDetail.jsx` | Single run: live or replayed timeline. |
| `frontend/src/components/Timeline.jsx` | Event → UI item reducer (`useRunStream`, `itemsFromPersistedEvents`), step/final/artifact cards. |
| `frontend/src/components/TeamEditor.jsx` | Modal: agents, topology, settings, persona apply/save, embeds `GraphEditor` for `graph` topology and `WizardPanel` (`kind="team"`). |

## API

### Teams — `/api/teams`

- `GET /api/teams` — list, most-recently-updated first.
- `POST /api/teams` / `PUT /api/teams/<id>` — validated by `_validate_team`:
  - `name` required; `topology` ∈ `single|pipeline|supervisor|graph` (default `pipeline`).
  - ≥1 agent; `supervisor` requires ≥2 agents.
  - Each agent: `name` required and unique (case-insensitive), `model` required,
    `provider` defaults to `ollama` if invalid, `temperature` clamped 0–2
    (legacy top-level field, see Gotchas), `params` cleaned against
    `providers.PARAM_SPECS` (clamped, coerced), `tools`/`skills` **silently
    dropped** if not in the current valid set.
  - `topology: "graph"` requires `graph` and runs it through `_validate_graph`
    (see `docs/features/flow-canvas/`).
  - `settings`: `quality_loop`/`parallel` bool, `max_revisions` clamped 0–5
    (default 2), `max_steps` clamped 1–20 (default 8).
- `GET/DELETE /api/teams/<id>`.

Team object shape (from `storage._team_row_to_dict`):
```json
{"id": 1, "name": "...", "icon": "🤖", "description": "...",
 "topology": "pipeline", "agents": [...], "settings": {...},
 "graph": {"nodes":[{"id","agent"}], "edges":[{"source","target"}],
           "positions": {"id": {"x","y"}}} | null,
 "created_at": 173..., "updated_at": 173...}
```

### Runs — `/api/teams/<id>/runs`, `/api/runs*`

- `POST /api/teams/<id>/runs` `{task}` → `{run_id}`. Calls
  `runmanager.manager.start(team, task)`, which creates the `runs` row and
  spawns a daemon thread — the endpoint returns immediately.
- `GET /api/runs?team_id=` — list (max 100, newest first).
- `GET /api/runs/<id>` — run row + `events: [{seq,type,agent,content,meta}]`.
- `POST /api/runs/<id>/stop` → `{stopped: bool}` — sets a `threading.Event`;
  cancellation is polled, so it can lag a few seconds.
- `GET /api/runs/<id>/events` — **SSE**. Replays persisted events from SQLite
  first (covers reconnects/finished runs — a finished run with no
  `ActiveRun` gets a synthetic `run_end` built from the stored `final`), then
  streams live events until `run_end`. Keepalive comment every 25s.
- `GET /api/runs/<id>/artifacts` → `[{path, size}]` (workspace file list).
- `GET /api/runs/<id>/artifacts.zip` → zip of the whole workspace.
- `GET /api/runs/<id>/artifacts/<path>` → file content, **always served with
  `mimetype: text/plain`** regardless of actual file type (see Gotchas).

### Run events (`event.type`)

| type | agent | content | meta |
|------|-------|---------|------|
| `run_start` | — | task | `{team, topology, concurrency}` |
| `agent_start` | name | — | `{role, model, provider}` |
| `token` | name | one chunk | — (never persisted) |
| `tool_call` | name | `"name(args json, ≤300ch)"` | — |
| `tool_result` | name | result text (≤1000ch) | — |
| `decision` | name or null | free text (delegation, routing, revision) | — |
| `artifact` | name | relative path written into the workspace | — |
| `agent_end` | name | full output | `{verdict}` on the reviewer node only, `{decision}` on the supervisor node only — plain workers have no meta |
| `run_end` | — | final deliverable (empty on error/cancel) | `{status: done\|error\|cancelled}`; `done` also carries `knowledge_note` (path or `null`) |
| `error` | — | error message | — |

`final_output.md` is always written into the workspace on completion but
does **not** get its own `artifact` event (only files produced by
`extract_files` do); `Timeline.jsx` filters it out of the artifacts list
because it's rendered as the dedicated "Final deliverable" card instead.

### Team wizard

`POST /api/wizard {kind:"team", request, provider, model, current?, feedback?}`
→ `{kind:"team", draft}`. See `docs/features/skills-tools/` for the wizard's
shared mechanics; team-specific behavior is `wizard.draft_team` +
`_normalize_team`, which repairs a model-drafted team rather than rejecting
it: caps at 8 agents, dedupes names, replaces any model not in the live
`models` list with a sensible pick (coder model if the agent looks
code-related), degrades a broken/incomplete graph to `pipeline`, and always
forces `max_revisions=2`/`max_steps=8` regardless of what the model proposed.
The draft still goes through the normal `POST /api/teams` validation when
saved from the editor.

## How it works

**Four topologies** (`engine.py`, `TeamState` with an add-reducer `history`
field so parallel branches can append concurrently — order is recovered from
each entry's `ts`):
- `single` — one node, START → agent → END.
- `pipeline` — agents chained in order. If `quality_loop` is on and there are
  ≥2 agents, the last agent becomes a reviewer: its output must start with
  `APPROVED` or `REVISE` (checked case-insensitively after stripping
  `<think>` blocks); `REVISE` loops back to the first worker with the
  reviewer's feedback appended to state, bounded by `max_revisions`.
- `supervisor` — agent[0] loops: emit JSON `{next, instruction}` choosing a
  worker or `FINISH`. `parse_route` is defensive: regex-extract a `{...}`
  block, else look for a literal `FINISH`, else the first worker name
  mentioned in the text, else `FINISH`. Bounded by `max_steps`; on `FINISH` a
  synthesis node (same agent) writes the final answer.
- `graph` — arbitrary DAG from `team["graph"]`. Incoming edges are grouped
  per target; a target with >1 source becomes a LangGraph join (**waits for
  all** sources — an "OR" merge is not representable). A `_finalize` node
  collects the latest output of whichever node(s) feed `end`.

**Parallel semaphore.** `TeamRunner.llm_gate` is a `threading.Semaphore` sized
to 1, or to `sysinfo.assess()["parallel"]["capacity"]` when the team's
`parallel` setting is on (computed once in `runmanager._execute`, passed into
`TeamRunner`). Every model call acquires it — concurrency is capped
independent of how wide the graph fans out.

**Idle-stream watchdog.** Each streamed call is wrapped in an httpx read
timeout (`providers.LLM_IDLE_TIMEOUT`, default 420s). A stall raises; the
tool loop emits a `decision` event and **retries once** (Ollama caches the
evaluated prompt prefix, so retry is cheap), then raises a clear
`RuntimeError` if it stalls again.

**File delivery.** Agents can't be trusted to call a `write_file` tool for
every deliverable, so `engine.extract_files` scans the agent's raw output for
fenced code blocks that name a file — either in the fence info string
(` ```python app.py `) or a header line right above it (`File: app.py`,
`**app.py**`, `### app.py`) — and writes each into the run workspace,
rejecting any path that would escape it. The system-prompt rules block
(`_agent_system_prompt`) is what tells agents to use this convention; if
files stop appearing, check that convention survived a prompt edit before
suspecting the tool system.

**Tool delegation** (`engine._delegate_loop`). Some local models (reasoning
models like DeepSeek-R1) can't bind tools. `_model_supports_tools` first
consults the model catalog's `tools` capability tag (cached per
`(provider, model)`); if a provider then rejects `bind_tools` at runtime with
"does not support tools", that's caught, the cache entry is corrected
(`_mark_no_tools`), and the call falls back to delegation from then on. In
delegate mode, the agent's system prompt is augmented with the tool list and
told to end a turn with a `DELEGATE: <instruction>` line (or a fenced
` ```delegate ` block — small models follow one convention or the other, not
consistently both). A separate **executor model** actually runs the tools:
resolved from `TOOL_DELEGATE_MODEL` (env, `"provider::model"` or a bare
model assumed `ollama`), or auto-picked as the first available `qwen2.5:*`
model, or the first tool-capable non-reasoning model found. Each delegation
round emits a `decision` event; bounded by `MAX_TOOL_ROUNDS` (5) like the
native tool loop.

**Cancellation.** `ActiveRun.cancel_event` is polled by
`TeamRunner._check_cancel()` between streamed chunks and tool rounds, raising
`RunCancelled`, caught in `runmanager._execute` to mark the run `cancelled`.

**Recursion limit.** `graph.invoke` is called with
`recursion_limit = 10 + 6*(max_steps + max_revisions) * num_agents` — scales
with team size and settings so large supervisor/quality-loop teams don't hit
LangGraph's default recursion ceiling.

## Gotchas

- **Team agents keep a legacy top-level `temperature` field** alongside
  `params` for back-compat (`engine._llm_for` only reads it if `params` has
  no `temperature`). The current UI (`AgentFields`) never writes it — new
  agents only ever set `params.temperature`. Don't assume both are kept in
  sync; only old data or direct API calls populate the top-level field.
- **Tokens are never persisted** (`runmanager.PERSISTED` excludes `token`).
  Reconnecting to a *finished* run replays durable events plus a synthetic
  `run_end`, not the original token stream — the UI renders agent output as
  rendered Markdown on replay, never a live token stream.
- `GET /api/runs/<id>/artifacts/<path>` is served with a hardcoded
  `mimetype: text/plain` regardless of actual content — binary artifacts
  download fine but with the wrong content-type header.
- The visual **flow canvas** and **pixel studio** both read/write the same
  `team.graph` field — saving from one overwrites node positions saved by
  the other (see `docs/features/flow-canvas/` and `docs/features/pixel-studio/`).
- Supervisor routing and reviewer verdicts are parsed **defensively** from
  free-text model output on purpose (7B models produce unreliable JSON) —
  never tighten `parse_route` or the `APPROVED`/`REVISE` check into a strict
  `json.loads()` without a fallback; that's the documented invariant in
  `CLAUDE.md`.
- Tool delegation only engages when an agent actually has `tools` attached
  **and** the model is believed not to support them — a first call against a
  model the catalog got wrong will still hit the provider's native tool-bind
  path once and fail before the cache self-corrects and later calls delegate.

## How to verify

1. `curl -s -X POST localhost:5860/api/teams/1/runs -d '{"task":"..."}' -H 'Content-Type: application/json'`
   against a seeded team (`Research & Report` is topology `pipeline` with a
   quality loop), then poll `GET /api/runs/<id>` until `status != running`.
2. `curl -N localhost:5860/api/runs/<id>/events` — confirm event types match
   the table above, and that `token` events never reappear after replay.
3. Force a `REVISE` cycle: give a vague task to `Research & Report` and check
   for a `decision` event with "Revision N requested" before the final
   `agent_end`/`run_end`.
4. Verify parallel graphs: run the seeded `Panel Discussion` team (topology
   `graph`, `settings.parallel: true`) and check `run_start`'s
   `meta.concurrency` is >1 on hardware that supports it.
5. Verify tool delegation: put a reasoning model (e.g. `deepseek-r1:7b`) with
   `tools: ["knowledge"]` on an agent, run a task that needs the tool, and
   look for the "can't use tools natively — delegating" `decision` event
   followed by a `🤝 delegated to <model>` decision and normal
   `tool_call`/`tool_result` events from the executor.
6. Verify file delivery: run the seeded `Code Squad` team, then
   `GET /api/runs/<id>/artifacts` and confirm files beyond
   `final_output.md`, and that `/artifacts.zip` downloads them all.
