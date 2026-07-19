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
  When a run saves a note, `scheduler._NOTE_RE` scrapes the `knowledge_write`
  tool result ("Saved as <path>") and stores it on the run as `note_path`
  (column added to `schedule_runs`). The UI turns it into a "📄 Read the saved
  note →" deep link (`#/knowledge/<encodeURIComponent(path)>`, opened via the
  `Knowledge` page's `openNote` prop), and the finish notification links to the
  note rather than the run when one exists. Only runs after this shipped have a
  `note_path`; older runs show no link.
- Message-first cards: the card shows the agent's latest result body as the
  focus; the timestamp is small muted meta. Run-history rows and the run-log
  modal lead with the message too (date/time demoted).


## Scheduling a TEAM (not just an agent)

A schedule can run a whole **team** instead of a single agent: set `team_id`
(the editor's Agent/Team toggle). The team runs through `runmanager` exactly
like a manual run, so its full timeline lives on the **Runs** page — and the
schedule's run history links straight to it (`run_id`). `scheduler._run_team`
starts the run, waits for it to finish (bounded), and summarizes its events
into the schedule log.

## Debugging: per-run logs

Every scheduled run stores a full **log** (timestamps, tool calls, tool
results, errors) and the result. The Schedules page → a schedule's *run history
& logs* → **📋 log** on any row opens a viewer showing the execution log + the
result; team runs also show an "Open full team run #N" link to the Runs page.
Endpoint: `GET /api/schedules/runs/<run_id>` → `{log, result, run_id, ok, …}`.

## Editing

Schedules are editable (✏️ on the card): `PUT /api/schedules/<id>` with any
subset of fields, including switching between agent and team mode.

## Gotchas

- **Runs are serial and only while the app is up.** A missed window is not
  backfilled — `next_run` slides forward on the next execution.
- **A web task must have web tools** (`web_search`, `read_webpage`) on its
  agent — the editor defaults to them for that reason.
- The scheduler thread swallows all exceptions by design (must never die); a
  failing run is recorded with `ok: false` and its error as the result.


## Default templates + notifications

Four ready-made schedules are seeded **disabled** (opt-in — nothing runs
unattended without you enabling it): Daily AI news digest (web → summarize →
insights → save to knowledge, notify), USD/ARS rate tracker (track + notify),
PC health check (system_info, warns on low disk/RAM), Weekly knowledge gardener
(proposes connections between recent notes). Seeded once via
`seeds.seed_default_schedules` (meta-gated, so a deleted one stays gone).

Notifications: set a schedule's `notify` flag and it fires a desktop popup +
in-app bell notification on completion (critical if it failed, linked to the
run). Agents can also notify mid-task with the `notify` tool. See
`notifications.py` and the sidebar bell.

New builtin tools used by templates: `system_info` (CPU/RAM/GPU/disk) and
`notify`.

## How to verify

1. Trivial deterministic prompt ("what is 100+250, number only"),
   `track_number: true`, `POST /run` → a run stored with `value` set
   (verified: 350 → value 350.0).
2. Pause (`PUT {enabled:false}`) → `next_run` shows "paused", thread skips it.
3. Real one: "search the web for the USD/ARS blue rate, report the number"
   daily with a web-tool agent + a knowledge folder; watch the sparkline grow.
