# Personas
> Part of Local Agents Studio. Read docs/index.md for the doc map.

## What it is

A persona is a **reusable, saved agent definition**: name, icon, role,
description, system prompt, provider/model, hyperparameters, tools, and
skills — plus, since the Pokédex update, a generated **creature sprite** and
`sprite_meta`. It's a template, not a running thing — applying a persona
copies its fields onto a team agent, a chat config, or a new persona draft.
Twelve builtin personas (Researcher, Writer, Reviewer, Coder, …) ship via
`seeds.py`.

The Personas page shows a roster grid; clicking a persona opens its
**Pokédex-style card** (`PersonaCard`): specs column, sprite, level, playful
stat bars derived deterministically from real settings (params size, native
tool support, temperature), tools / abilities / status panels, and the
sprite-generation button. Editing still uses the unchanged `PersonaEditor`
with all original fields.

### Sprites: species & evolution (sprites.py)

- **Model family = species**, fixed in code (`sprites.SPECIES`): every
  qwen-based persona is a violet *Qwenix*, deepseek an *Abyssyn*, llama a
  *Llamon*, etc. An LLM never decides species traits — consistency is the
  point.
- **Parameter count = evolution stage** (≤3B cub → 3–9B adolescent → >9B
  final form with aura), via `sprites.stage_for`.
- Role adds an accessory (coder goggles, PMO cape…); the persona wizard may
  add one short "flavor".
- `POST /api/personas/<id>/sprite` builds the prompt deterministically,
  auto-attaches a local LoRA whose filename matches
  `pokemon|gba|sprite|pixel` (weight 0.8), generates via Fooocus, and stores
  `sprite` (image filename) + `sprite_meta` (species/family/stage/prompt/lora).

### AI wizard (`kind: "persona"`)

`POST /api/wizard {kind: "persona", request}` → `wizard.draft_persona`
returns validated persona fields + a `flavor` string. The Personas page
wizard flow: describe → draft fills the editor → save → the card opens ready
to generate the sprite (flavor carried through).

## Key files

| Path | Role |
|------|------|
| `app.py` | `_validate_persona`, `/api/personas` CRUD + `/api/personas/<id>/sprite`. |
| `storage.py` | `personas` table incl. `sprite`/`sprite_meta` columns (+ `set_persona_sprite`). |
| `sprites.py` | Species/evolution/accessory rules and the deterministic sprite prompt builder. |
| `wizard.py` | `draft_persona` (kind=persona). |
| `seeds.py` | `SEED_PERSONAS` — 12 builtin personas, created once when the table is empty. |
| `frontend/src/pages/Personas.jsx` | Roster grid, `PersonaCard` (Pokédex view), `PersonaEditor`, wizard entries. |
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
- **Sprite generation is slow and synchronous** (minutes on a weak GPU); the
  card button shows an "Evolving…" state while the request runs. It requires
  the Fooocus server to be running (Models page).
- **Species must stay code-decided.** If you touch `sprites.py`, keep family
  → species mapping deterministic; longest-family-key matching exists so
  `tinyllama` doesn't classify as `llama`.
- While Fooocus is up, Ollama runs CPU-only (`providers.image_server_running`
  guard) — persona wizard drafts are slower then; without the guard Ollama's
  runner crashes outright ("llama runner process has terminated").

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
