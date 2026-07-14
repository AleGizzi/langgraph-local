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
  **`builtin` has 9 entries**: `calculator`, `current_datetime`, `http_get`,
  `web_search`, `read_webpage`, `run_python`, `files`, `knowledge`,
  `generate_image` (verified against `tools.TOOL_CATALOG` — keep this list in
  sync when you add a builtin, it has gone stale before). Note `files` is a
  *bundle*: it expands to `write_file`, `edit_file`, `read_file`, `list_files`.
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

## The coding-agent skill pack (and what we refused to port)

Eight builtin skills, three builtin tools and one persona were ported from the
"10 must-have skills for coding agents" list, **adapted for local models**. The
adaptation is the whole point — porting all ten verbatim would have shipped
features that quietly fail on a 7B.

| Article skill | What shipped | Why |
|---|---|---|
| Code Reviewer | `Code Reviewer` skill | Concrete numeric rules; a 7B follows them |
| Frontend Design | `Frontend Design` skill | Pure directive; design-system-first |
| Antigravity bundle | `Brainstorming`, `API Design`, `Systematic Debugging` | The prompt-only members of the bundle |
| PlanetScale | `Database Schema Review` skill | Kept the schema/index reasoning, **dropped the hosted CLI** — plain SQL, no cloud account |
| Shannon (autonomous pentest) | `Security Audit` skill | **Defensive only**: finds and fixes vulnerabilities, never writes exploits or attacks anything |
| Excalidraw | `Diagram First` skill (Mermaid) | Excalidraw's loop is render→*look at the PNG*→fix. That needs vision. Mermaid is text, renders anywhere, and diffs |
| Browser Use + Valyu | `web_search` + `read_webpage` tools | A 7B cannot drive a visual click-loop. Text search + page reading delivers the actual value (current info, cited) with no API key |
| Remotion | **not ported** | Programmatic video via React + interpolation math; local models emit broken timing code and the Node toolchain is heavy |
| Google Workspace | **not ported** | 50+ cloud APIs behind OAuth — breaks invariant 6 (fully local) |

Rules of thumb this produced, worth reusing when writing any new skill:

- **Local models follow countable rules, not taste.** "Functions longer than 30
  lines" works; "write elegant code" does nothing.
- **Say what does *not* count as an excuse.** The Code Reviewer skill originally
  said "missing error handling on I/O, network, parsing" — qwen2.5-coder:7b
  read that literally and skipped an unguarded `d["value"]`, reasoning "this
  function does no I/O". The rule now names dict access, indexing, conversion
  and division explicitly.
- **Never give a model a phrase it can append unconditionally.** "If a pass
  finds nothing, say 'Pass 1: clean'" produced a review that listed four issues
  *and then declared itself clean*. Escape hatches must be spelled out as
  mutually exclusive with the finding list.

### Flask App Factory — a team whose output is *proven* to run

Seed team (`seeds.SEED_TEAMS`), pipeline: **Spec → Builder → Verifier**. From a
one-line prompt ("a URL shortener") it delivers `app.py`, `smoke_test.py` and
`requirements.txt`, and the Verifier does not get to *claim* the app works — it
has `run_python` and must show exit code 0.

The load-bearing trick: **a Flask app is a blocking server**, so an agent that
runs `app.run()` under `run_python` just hangs until the 30s timeout and learns
nothing. Instead the `Runnable Flask App` skill requires a `smoke_test.py` that
drives the app through `app.test_client()` — no port, no blocking, returns in
milliseconds, exercises every route. That is what makes "executable" *checkable*
by a machine instead of asserted by a model.

Four real bugs surfaced only by running this against real models, each fixed in
code rather than by nagging the prompt:

1. **`engine.salvage_tool_calls`.** qwen2.5-coder:7b advertises Ollama's `tools`
   capability but prints `{"name": "run_python", ...}` as *text*. Tools bound,
   nothing executed, agent reported success having done nothing. Now recovered —
   with a JSON scanner, not a regex: the arguments are usually a whole source
   file, and a non-greedy `{.*?}` truncates at the first `}` inside an f-string.
2. **`MAX_TOOL_ROUNDS` was 5.** One fix cycle costs three rounds (run → read →
   write), so a verifier could not complete two attempts and silently gave up
   mid-repair. Now 14, env-tunable.
3. **`run_python` truncated stderr from the front.** A traceback's *last* line
   names the cause; the head is framework frames. The model was handed 2000
   characters of Flask internals with the cause cut off, so it re-ran the same
   failing test forever. stderr now keeps the **tail**.
4. **A bad `edit_file` could corrupt the file.** An edit landing at the wrong
   indentation left `app.py` unparseable, and every later run failed on the
   SyntaxError instead of the real bug. `write_file`/`edit_file` now `compile()`
   any `.py` before writing and **refuse** the write, leaving the last good
   version on disk. This fires in practice — the passing run shows one refused
   edit, after which the model re-read the file and got it right.

Plus a **loop guard** in `_tool_loop`: repeating a tool call with identical
arguments appends a warning to the result, because small models otherwise re-run
a failing test indefinitely without changing anything.

Honest limits: this is a 7B doing a multi-step repair loop, so it is
probabilistic, not deterministic — a run takes 10–20 minutes and can still end
short of green, in which case the Verifier reports the last traceback rather than
faking success. The Builder tends to reach for sqlite when left alone, which is
why the Spec agent is instructed to specify an in-memory dict unless persistence
was actually requested; simple state is what a 7B can get right first time.

`run_python` deserves its own warning: it executes real Python with the user's
permissions. It is confined to the run workspace and killed after 30s, but a
script it runs can still do anything Python can. It is opt-in per agent for that
reason — the point is letting a coding agent *verify its own code runs* instead
of hallucinating that it does.

Known gap: `Diagram First` emits a ```` ```mermaid ```` block that the UI renders
as a fenced code block, not a picture — the Markdown renderer has no Mermaid
support yet. The output is still valid and pasteable; wiring an actual renderer
is a follow-up.

## Gotchas

- **Custom tool code execution is not sandboxed.** `PUT /api/tools/files/<f>`
  writes arbitrary Python and immediately `importlib`-executes it in-process
  (module-level statements run). This is by design for a single-user,
  unauthenticated, localhost-only app (`CLAUDE.md`: "no auth… single-user by
  design") — do not expose this endpoint, or the app generally, to a
  network without adding your own front door.
- **New builtin skills/personas need `seeds.backfill_builtins()`, not just a
  `SEED_*` entry.** `seed_if_empty()` only fires on a virgin database, so
  anything added to `SEED_SKILLS`/`SEED_PERSONAS` later would never reach an
  existing install. `backfill_builtins()` inserts what's missing by name and
  records what it has already offered in the `meta` table — so a builtin the
  user *deletes* stays deleted instead of resurrecting on every restart, and one
  they *edited* is never overwritten. The same applies to the one-shot
  `personas_skills_attached` flag, which attaches new skills to pre-existing
  builtin personas (Architect, Code Reviewer, Brainstormer) exactly once.
- **Check `SEED_PERSONAS` for a name collision before adding one.** Personas are
  matched by name; `Architect`, `Code Reviewer` and `Brainstormer` already
  existed, and adding second entries with the same names would have created
  duplicate rows on a fresh DB.
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
6. **Skill pack** (as verified on 2026-07-13, real models, no mocks):
   - `Code Reviewer` on `qwen2.5-coder:7b` against a function with an unguarded
     `d["value"]` and a `total / len(result)` — it must flag the division and
     the dict access, return corrected code and an Issue/Severity/Fix table, and
     must **not** print "Pass 1: clean" while listing issues.
   - `Web Researcher` persona on `qwen2.5:7b` — confirm `tool_call:web_search`
     fires and the answer carries real URLs. (It typically answers from search
     snippets without calling `read_webpage`; that is a known local-model
     shortcut, not a bug.)
   - `Diagram First` on `qwen2.5:7b` — output must open with a valid ```mermaid
     block with labelled edges.
   - `tools.make_run_python(ws)` — a good script returns `exit code: 0` +
     stdout, a raising script returns the traceback on stderr, and
     `../../../etc/passwd` returns "path escapes the workspace".
