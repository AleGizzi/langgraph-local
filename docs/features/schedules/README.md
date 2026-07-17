# Scheduled agent tasks

Cron for local agents: run an agent unattended on an interval — a daily web
check, a tracked metric, recurring research.

## What it is

A **schedule** pairs an agent config (model, prompt, tools, skills) with an
interval. One background thread (`scheduler.py`, started at app boot) wakes
every ~20s, runs each *due, enabled* schedule once — serially, so the 4GB GPU
is never hit by several scheduled agents at once — records the result, and sets
the next run. Optionally it extracts the first number from each result and
stores it as a time series to chart (e.g. a currency rate day over day), and/or
appends the finding to a knowledge folder so it accumulates.

Honest limitation: it only runs **while the app process is up**. Pair it with
the systemd user service or the desktop app (`docs/operations.md`) for 24/7.

## Key files

| Path | Role |
|------|------|
| `scheduler.py` | The thread, `run_schedule(id)` (also used by "Run now"), number extraction |
| `storage.py` | `schedules` + `schedule_runs` tables and their CRUD |
| `app.py` | `/api/schedules*` routes; `scheduler.start()` at boot |
| `frontend/src/pages/Schedules.jsx` | List, create modal, per-schedule sparkline + history |

## API

- `GET /api/schedules` → `{schedules: [{…, runs: [{ran_at, ok, result, value}]}]}`
- `POST /api/schedules {name, prompt, agent, interval_seconds, track_number,
  knowledge_folder}` → the schedule. `agent.model` required.
- `PUT /api/schedules/<id>` — partial update (e.g. `{enabled: false}` to pause).
- `DELETE /api/schedules/<id>` — removes it and its run history.
- `POST /api/schedules/<id>/run` — run immediately in a background thread.

## How it works

- Execution reuses `engine.chat_stream` headlessly (single user message =
  prompt), collecting the `done` event's content. Runs in a shared
  `data/workspaces/scheduler` workspace.
- `track_number`: `scheduler._extract_number` pulls the first numeric token,
  handling both `1,234.56` and `1.350,75` groupings (decimal separator decided
  by which appears last). Charted as an inline SVG sparkline.
- `knowledge_folder`: the agent is given the `knowledge` tool (if absent) and
  the prompt is appended with an instruction to save its finding as a dated
  note in that folder — a daily check builds a real Obsidian-readable log.

## Gotchas

- **Runs are serial and only while the app is up.** A missed window is not
  backfilled — `next_run` slides forward on the next execution.
- **A web task must have web tools** (`web_search`, `read_webpage`) on its
  agent — the editor defaults to them for that reason.
- The scheduler thread swallows all exceptions by design (must never die); a
  failing run is recorded with `ok: false` and its error as the result.

## How to verify

1. Trivial deterministic prompt ("what is 100+250, number only"),
   `track_number: true`, `POST /run` → a run stored with `value` set
   (verified: 350 → value 350.0).
2. Pause (`PUT {enabled:false}`) → `next_run` shows "paused", thread skips it.
3. Real one: "search the web for the USD/ARS blue rate, report the number"
   daily with a web-tool agent + a knowledge folder; watch the sparkline grow.
