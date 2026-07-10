# Skills & Tools
> Part of Local Agents Studio. Read docs/index.md for the doc map.

## What it is

Two independent systems sharing one page (`Toolbox.jsx`): **skills** are
named blocks of prompt instructions injected into an agent's system prompt
(behavior, not capability); **tools** are Python functions an agent can call
via function calling — builtins in `tools.py` plus auto-discovered custom
`@tool` functions in `custom_tools/*.py`. This also covers the AI wizard's
skill- and tool-drafting (the team-drafting half lives in
`docs/features/teams-runs/`).

## Key files

| Path | Role |
|------|------|
| `tools.py` | Builtin tools, `TOOL_CATALOG`, `custom_tools/*.py` loader, `validate_tool_code`, `resolve_tools` (name → LangChain tool objects, expands bundles). |
| `wizard.py` | `draft_skill`, `draft_tool` (team drafting documented separately). |
| `app.py` | `/api/skills` CRUD, `/api/tools*` routes, `POST /api/wizard` (`kind: skill\|tool`). |
| `storage.py` | `skills` table. |
| `seeds.py` | `SEED_SKILLS` — 5 builtin skills. |
| `custom_tools/create_file.py`, `custom_tools/word_count.py` | Example custom tool files (also live examples for the loader). |
| `frontend/src/pages/Toolbox.jsx` | Skills gallery + `SkillEditor` modal; custom tool file list + `ToolFileEditor` modal. |
| `frontend/src/components/WizardPanel.jsx` | Shared AI-draft panel (`kind="skill"\|"tool"\|"team"`), embedded in `Toolbox.jsx` and `TeamEditor.jsx`. |

## API

### Skills — `/api/skills`

- `GET /api/skills` — all skills, builtins first.
- `POST /api/skills` / `PUT /api/skills/<id>` — `{name, icon, description,
  instructions}`; `name` and `instructions` required, `icon` truncated to 8
  chars (default `✨`).
- `DELETE /api/skills/<id>` → `{ok: true}`.

### Tools — `/api/tools*`

- `GET /api/tools` → `tools.full_catalog()`:
  ```json
  {"builtin": [{"name": "...", "description": "..."}],
   "custom": [{"name": "...", "file": "...", "description": "≤200 chars"}],
   "files": [{"file": "...", "tools": ["..."], "error": "string|null"}],
   "template": "python source for a new custom tool file"}
  ```
  **`builtin` has 6 entries**: `calculator`, `current_datetime`, `http_get`,
  `files`, `knowledge`, `generate_image` — the old `docs/api.md` prose listed
  only the first 5 and omitted `generate_image`; fixed here (verified
  against `tools.TOOL_CATALOG`).
- `GET /api/tools/files/<filename>` → `{file, code}` (404 if missing).
- `PUT /api/tools/files/<filename>` `{code}` — writes the file, **reloads
  immediately** so the response reports load errors:
  `{file, loaded: [tool names], error: string|null}`. `filename` must match
  `[A-Za-z0-9_\-]+\.py`.
- `DELETE /api/tools/files/<filename>` → `{ok: true}`.

### Wizard — `POST /api/wizard`

`{kind: "skill"|"tool", request, provider, model, current?, current_code?, feedback?}`
→ `{kind, draft}`:
- `skill` → `{name, icon, description, instructions}` (falls back to using
  the model's whole raw answer as `instructions` if it didn't return valid
  JSON).
- `tool` → `{code, tools: [names], error: string|null, filename_suggestion}`
  — `draft_tool` validates the generated code with `validate_tool_code` and,
  on failure, does **one auto-fix round** by re-prompting the model with its
  own error message before giving up and returning the still-broken code +
  error for manual fixing.

## How it works

- **Skill injection**: both `engine.TeamRunner._agent_system_prompt` and
  `engine.chat_stream` append `\n\n## Skill: <name>\n<instructions>` per
  attached skill, in list order — a plain string concatenation, no template
  engine.
- **Tool bundles**: `"files"` and `"knowledge"` are not single tools —
  `resolve_tools()` expands `"files"` into 3 workspace-bound LangChain tools
  (`write_file`/`read_file`/`list_files`, path-traversal-safe) and
  `"knowledge"` into `knowledge_search`/`knowledge_read`/`knowledge_write`
  (see `docs/features/knowledge/`). An agent's `tools: [...]` list can name
  fewer entries than the tools actually bound to the LLM.
- **Custom tool discovery** (`load_custom_tools`): scans `custom_tools/*.py`
  (skipping `_`-prefixed files), imports each as its own module via
  `importlib`, and collects every module-level `@tool`-decorated
  (`BaseTool`) object. A broken file gets `{error: "..."}"}` recorded but
  never breaks the app or other files — this is what both
  `PUT /api/tools/files/<f>` and `GET /api/tools` (catalog) rely on.
- **`valid_tool_names()`** — used by `_validate_team`/`_validate_persona`/
  `_validate_chat` to filter `tools` lists — re-scans and re-imports
  `custom_tools/*.py` **on every call**, no caching. A file drop/edit takes
  effect immediately for validation, at the cost of a directory scan + import
  on essentially every team/persona/chat save.
- **Wizard auto-fix**: `draft_tool` calls the model once, validates; if it
  fails, re-prompts with the exact error text and validates the second
  attempt; if that also fails, returns the broken code + error rather than
  looping further.

## Gotchas

- **Custom tool code execution is not sandboxed.** `PUT /api/tools/files/<f>`
  writes arbitrary Python and immediately `importlib`-executes it in-process
  (module-level statements run). This is by design for a single-user,
  unauthenticated, localhost-only app (`CLAUDE.md`: "no auth… single-user by
  design") — do not expose this endpoint, or the app generally, to a
  network without adding your own front door.
- `docs/api.md`'s builtin tool list was stale (missing `generate_image`) —
  verify against `tools.TOOL_CATALOG` if you add/remove a builtin, since
  it's easy for prose docs to drift from the dict.
- Skills have no versioning — editing a skill's `instructions` changes
  behavior retroactively for every agent/persona referencing it by name;
  there's no per-team snapshot of what a skill said at run time.
- Tool/skill validation **silently drops** unknown names in
  `_validate_team`/`_validate_persona`/`_validate_chat` rather than erroring
  — a typo'd name in a raw API call just disappears with no error surfaced.
- Because `load_custom_tools()` re-imports every file on nearly every
  request that touches tools (catalog fetch, team/persona/chat save), a slow
  or side-effecting module-level statement in a custom tool file runs
  repeatedly, not once at startup — keep custom tool files free of import-time
  side effects (the wizard's system prompt explicitly instructs this).

## How to verify

1. Create a skill via the Toolbox, attach it to an agent in the Team Editor,
   run the team, and confirm the `## Skill: <name>` heading's instructions
   visibly affected the output.
2. Create a custom tool from the template (or reference `word_count.py`),
   enable it on an agent, run a task that should trigger it, and confirm
   `tool_call`/`tool_result` events show it firing.
3. Break the file (introduce a syntax error) and `PUT` again — confirm the
   response has `{error: "..."}"}`  and that the tool disappears from
   `GET /api/tools`'s `custom` list without any other tool breaking.
4. `POST /api/wizard {kind:"tool", request:"...", provider:"ollama",
   model:"qwen2.5:7b"}` against a local model and confirm the returned code
   loads cleanly (or that the one auto-fix round produced working code).
5. `POST /api/wizard {kind:"skill", ...}` and confirm the draft's
   `instructions` read as imperative directives, not a description.
