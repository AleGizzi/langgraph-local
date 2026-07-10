# Personas
> Part of Local Agents Studio. Read docs/index.md for the doc map.

## What it is

A persona is a **reusable, saved agent definition**: name, icon, role,
description, system prompt, provider/model, hyperparameters, tools, and
skills. It's a template, not a running thing — applying a persona copies its
fields onto a team agent, a chat config, or a new persona draft. Twelve
builtin personas (Researcher, Writer, Reviewer, Coder, …) ship via
`seeds.py`.

## Key files

| Path | Role |
|------|------|
| `app.py` | `_validate_persona` + `/api/personas` CRUD routes. |
| `storage.py` | `personas` table (`_persona_row_to_dict`, CRUD functions). |
| `seeds.py` | `SEED_PERSONAS` — 12 builtin personas, created once when the table is empty. |
| `frontend/src/pages/Personas.jsx` | Grid + modal editor (`PersonaEditor`), CRUD. |
| `frontend/src/components/AgentFields.jsx` | The shared form (name/role/model/prompt/params/tools/skills) — used here **and** by `TeamEditor`, `Chat`, `FlowEditor`, `PixelStudio`. |

Persona "apply" / "save as persona" touchpoints live in the consuming
features, not here — see `docs/features/teams-runs/` (`TeamEditor`'s persona
strip + per-agent 💾), `docs/features/chat/` (`Chat.jsx`'s quick-load chips +
⚙️ panel 💾), and `docs/features/flow-canvas/` (`FlowEditor`'s drag-drop
palette).

## API

- `GET /api/personas` — all personas, builtins first (`ORDER BY builtin
  DESC, name`).
- `POST /api/personas` / `PUT /api/personas/<id>` — validated by
  `_validate_persona`: `name` required; `icon` truncated to 8 chars (default
  `🧑`); `provider` defaults to `ollama` if not `ollama`/`lmstudio`; `params`
  cleaned via `providers.clean_params` (same `PARAM_SPECS` as team agents);
  `tools`/`skills` filtered to currently-valid names, **silently dropped**
  if unknown.
- `DELETE /api/personas/<id>` → `{ok: true}`.

Response shape (`storage._persona_row_to_dict`):
```json
{"id": 1, "name": "Researcher", "icon": "🔎", "role": "Research analyst",
 "description": "...", "system_prompt": "...", "provider": "ollama",
 "model": "qwen2.5:7b", "params": {"temperature": 0.4, "top_p": 0.9},
 "tools": [], "skills": [], "builtin": true}
```
Note: **no top-level `temperature`** — unlike a team agent object, a persona
only ever carries hyperparameters inside `params`.

## How it works

- `personas.skills` is a lightweight-migrated column
  (`storage.init_db` adds it via `PRAGMA table_info` check if missing) — any
  persona created before that migration ran would read back `skills: []`
  until re-saved.
- **Apply persona** (used in `TeamEditor`, `Chat.jsx`, `FlowEditor`) copies
  `role`, `system_prompt`, `params`, `tools`, `skills` onto the target, but
  **only overwrites `provider`/`model` if the persona has a `model` set** —
  applying a model-less persona preserves whatever model the target agent
  already had.
- **Save as persona** (per-agent 💾 in `TeamEditor`, ⚙️ panel 💾 in
  `Chat.jsx`) is the reverse: `POST /api/personas` with the current
  agent/chat config as a brand-new persona.
- Builtin seeding: `seeds.seed_if_empty()` inserts `SEED_PERSONAS` with
  `builtin=True` exactly once, gated on `storage.count_personas() == 0` — if
  you delete every persona, restarting the app does **not** re-seed them
  (only an empty table at first ever launch triggers seeding).

## Gotchas

- **`builtin: true` is a UI flag only** — nothing in `app.py` prevents
  `PUT`/`DELETE` on a builtin persona, and `Personas.jsx`'s delete button has
  no builtin check either. Deleting a builtin is permanent (no re-seed on
  restart, see above).
- Applying a persona with no `model` set can look like "the persona did
  nothing" when it actually did apply every other field — only
  provider/model were preserved because the persona itself had none.
- Persona and team-agent objects are **not shape-identical**: team agents
  keep a legacy top-level `temperature`, personas never do. Code that
  handles both generically (e.g. a shared "apply persona" helper) must not
  assume the same key set.
- Tool/skill filtering drops unknown names silently — a typo'd tool name in
  a raw `POST /api/personas` body just vanishes with no error in the
  response.

## How to verify

1. `POST /api/personas` with a new persona; `GET /api/personas` and confirm
   it appears after the builtins (sorted by name).
2. Apply it from the Team Editor's persona strip on a fresh agent, confirm
   every field (prompt, params, tools, skills) populates.
3. Apply a persona with `model: ""` onto an agent that already has a model
   set, and confirm the model is unchanged (not blanked).
4. Edit its `params`/`tools` via `PUT`, confirm the response and a follow-up
   `GET` both reflect the change.
5. `DELETE` it, confirm `{"ok": true}` and that it's gone from
   `GET /api/personas`.
