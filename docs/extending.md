# Extending Local Agents Studio

Step-by-step recipes for the common ways you'll grow this app. Each names the exact
files to touch. Read `CLAUDE.md` and `docs/architecture.md` first.

The recurring shape of a feature: **backend module** (logic) → **`app.py`** (route +
validation) → **frontend page/component** (UI) → **`seeds.py`** (defaults, if any) →
**verify with a real run**.

---

## Add a built-in tool

Tools are functions agents can call. Built-ins live in `tools.py`.

1. Write an `@tool`-decorated function in `tools.py`. The **docstring is the contract**
   the model reads to decide when to call it — describe purpose and each argument.
   Return a string.
   ```python
   @tool
   def word_count(text: str) -> str:
       """Count the words in a text. Use when asked how long a text is."""
       return f"{len(text.split())} words"
   ```
2. Register it: add a key to `TOOL_CATALOG` (name → short description) and a branch in
   `resolve_tools()`. For a *bundle* of related tools (like `files` or `knowledge`),
   map one catalog key to several functions in `resolve_tools`.
3. It now appears in every agent's tool picker automatically (the frontend reads
   `/api/tools`). No frontend change needed.

**Prefer custom tools for anything app-specific:** drop a `.py` file with `@tool`
functions into `custom_tools/` (or use the in-app wizard). It's auto-discovered by
`load_custom_tools()` with per-file error isolation — a broken file never breaks the app.

## Add an MCP-backed tool

To expose an external [MCP](https://modelcontextprotocol.io) server's tools instead of
writing them yourself, use `mcp_client.py`. It runs each MCP server on its own asyncio
loop in a daemon thread, keeps the session alive across calls, and bridges the async
`call_tool` to this app's **synchronous** tool loop (`fn.invoke(dict)`).

1. Add a server factory like `_playwright_server()` — an `_MCPServer(key, command, args)`
   singleton. It **must not start on import**; it starts lazily on the first `.call()`.
2. Write a small, **curated** set of `@tool`/`StructuredTool` wrappers whose functions call
   `srv.call("<mcp_tool_name>", {...})`. Do **not** auto-expose the server's whole tool
   surface — local 7B–14B models mis-select from large tool sets (same lesson as the
   router). The `browser` bundle wraps ~25 Playwright tools down to 2 (`browser_open`,
   `browser_snapshot`).
3. Register the bundle in `TOOL_CATALOG` + `resolve_tools` in `tools.py`, **lazy-importing**
   `mcp_client` inside the `resolve_tools` branch so safe imports never touch it.
4. If the server is a Node package (like `@playwright/mcp`), pin a version compatible with
   this machine's Node (currently 18 → `@playwright/mcp@0.0.29`, override via
   `PLAYWRIGHT_MCP_SPEC`). Return a friendly string, never raise, when `npx` is missing.

## Add a skill

Skills are prompt-instruction blocks, stored in the DB. No code needed to create one —
use the **Skills & Tools** page (manual or AI wizard). To ship one as a default, add it
to `SEED_SKILLS` in `seeds.py`. Skills are injected into the agent system prompt in
`engine.TeamRunner._agent_system_prompt` under a `## Skill: <name>` heading.

## Add an agent hyperparameter

1. Add a spec tuple to `providers.PARAM_SPECS`: `(key, label, min, max, step, default, hint)`.
2. Map it to the provider's kwarg in `providers.make_llm` (Ollama and/or LM Studio
   branch). `clean_params()` validates/clamps it automatically from the spec.
3. The frontend renders it automatically (`AgentFields`/`ParamsEditor` read `/api/params`).

## Add a topology

Topologies are graph builders in `engine.py`.

1. Write `_build_<name>(self)` returning a compiled `StateGraph`. Emit the standard
   events (`agent_start`, `agent_end`, `decision`, …) via `self.emit` so the UI and
   pixel view animate. Use `self._worker_node(agent)` for a standard agent node.
2. Dispatch to it in `TeamRunner.run()` (the `topology == ...` chain).
3. Add the name to `VALID_TOPOLOGIES` in `app.py`. If it needs structured config
   (like `graph` does), add validation in `_validate_team` and a storage column
   (follow how `graph` is handled in `storage.py` — nullable JSON + `init_db` migration).
4. Frontend: add it to the topology `<select>` in `TeamEditor.jsx` and render any
   extra settings. If it's graph-shaped, the canvas/pixel editors may already cover it.

**Gotcha:** if your topology runs nodes concurrently, rely on the `history` add-reducer
(already in `TeamState`) and stamp each entry with `ts` for ordering.

## Add a provider (beyond Ollama / LM Studio)

1. In `providers.py`: add discovery to `list_models()` and `provider_status()`, and a
   branch in `make_llm()` returning a LangChain chat model. Map `PARAM_SPECS` to its
   kwargs.
2. If it has an install/detection story, extend `sysinfo.py` (`_<provider>_install`)
   and `installer.py`.
3. Accept the provider string wherever agents are validated in `app.py` (search for
   `("ollama", "lmstudio")` and extend the tuples).
4. The model dropdown (`AgentFields.ModelSelect`) groups by provider from `/api/models`
   automatically.

## Add an API route

All routes live in `app.py`. Follow the existing pattern:

1. Add `@app.<method>("/api/...")`. Validate input up front with `abort(400, "...")`;
   don't trust the body.
2. Delegate persistence to a `storage.py` function (add one if needed — keep the
   new-connection-per-op pattern). Delegate logic to the relevant module.
3. `jsonify(...)` a plain dict/list. For a stream, return a `Response(generate(),
   mimetype="text/event-stream", ...)` and yield `_sse(event)` — see `/api/chat`.
4. Document it in `docs/api.md`.

## Add a frontend page

1. Create `frontend/src/pages/YourPage.jsx`.
2. In `frontend/src/App.jsx`: import it, add a `NAV` entry `[route, icon, label]`, and a
   branch in the `view` selection. For a full-viewport page (no sidebar chrome), add an
   early `if (route.page === "yourpage")` return like `flow`/`pixel` do.
3. Read shared state with `useApp()` (models, tools, skills, health, theme). Call the
   API with `api()` from `lib/api.js`; show errors with `toast()`.
4. Reuse components: `AgentFields` for any agent/persona editor, `Timeline` +
   `useRunStream` for live run output, `Md` for Markdown. Style with the CSS variables
   in `styles.css` so dark mode works for free.

## Add a model to the catalog / dream team

The catalog is scraped live, so most models appear automatically. To adjust:

- **Text models**: `catalog.MODEL_CATALOG`-style curation isn't used anymore (the list
  is live). To change categorization or ranking, edit `classify()` /
  `annotate()` in `catalog.py`.
- **Image models**: edit the curated `catalog.IMAGE_MODELS` list and `image_models()`
  VRAM logic. These are static because they live in a different ecosystem.
- **Offline fallback**: `catalog.BUILTIN_SNAPSHOT` is what shows with no internet.

## Change where data lives

Everything is env-var driven (see `docs/operations.md`): `AGENTS_DB`,
`AGENTS_WORKSPACES`, `AGENTS_KNOWLEDGE`, `AGENTS_CUSTOM_TOOLS`. Point `AGENTS_KNOWLEDGE`
at an existing Obsidian/Logseq vault to merge.

---

## Verifying your change

There is no unit-test suite — verify by driving the app (see `CLAUDE.md` → Testing):

1. Restart cleanly: `./restart.sh`.
2. Exercise the backend directly (`.venv/bin/python -c "..."`) or via `curl`.
3. For anything that runs agents, do a **real run** on `qwen2.5:7b` and assert on the
   events/final — not just that imports succeed. Local models surface bugs (bad JSON,
   tool-call quirks) that mocks won't.
4. For UI, drive it with Playwright (in the venv) and check for zero console errors.
5. Clean up test artifacts (test teams, runs, knowledge notes) so you leave a clean
   state.

## House style

- Backend: defensive parsing of all model output; new-connection-per-op storage;
  best-effort side effects (knowledge export, catalog refresh) wrapped so they never
  break a run.
- Frontend: CSS variables (never hardcoded colors — dark mode depends on it); the
  hand-rolled `api()`/`toast()` helpers; hash routing.
- Comments explain *why* (constraints, gotchas), not *what*. Match the surrounding
  code's density.
