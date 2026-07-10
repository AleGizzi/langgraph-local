# Local Agents Studio — Frontend Guide

A React 18 + Vite single-page app (no TypeScript, no router library) that manages multi-agent LangGraph teams running on local LLMs. Builds to `static/dist/` which Flask serves at `/static/dist/`.

## Build & Dev Setup

**Vite config** (`frontend/vite.config.js`):
- Dev server on port 5173 with proxy `/api` → `http://127.0.0.1:5860` (Flask backend)
- Base path: `/static/dist/`
- Build output: `../static/dist` (relative to `frontend/`), empties on rebuild
- React plugin enabled

**package.json**:
- `npm run dev` — start Vite dev server (HMR enabled, proxies API calls)
- `npm run build` — production build to `static/dist/`
- `npm run preview` — preview production build locally
- Dependencies: React 18, ReactDOM 18, @xyflow/react (graph visualization)

**Entry point**: `main.jsx` renders `App.jsx` to `#root`, injects global styles from `styles.css`.

---

## Routing Model

Custom hook `useHashRoute()` watches `location.hash`:
```javascript
// Hash format: #/[page]/[id]
// Examples: #/teams, #/team/42, #/run/7
const { page, id } = useHashRoute();
```

**Route → Page mapping** in `App.jsx`:
| Hash | Page name | Component | Full viewport? |
|------|-----------|-----------|---|
| `#/teams` | teams | `Teams` | No |
| `#/team/:id` | team | `TeamPage` | No |
| `#/flow/:id` | flow | `FlowEditor` | **Yes** |
| `#/pixel/:id` | pixel | `PixelStudio` | **Yes** |
| `#/runs` | runs | `Runs` | No |
| `#/run/:id` | run | `RunDetail` | No |
| `#/models` | models | `Models` | No |
| `#/personas` | personas | `Personas` | No |
| `#/toolbox` | toolbox | `Toolbox` | No |
| `#/setup` | setup | `Setup` | No |
| `#/settings` | settings | `Settings` | No |
| `#/chat` | chat | `Chat` | No (but has `page-full` layout) |
| `#/knowledge` | knowledge | `Knowledge` | No |

**Full-viewport pages** (flow, pixel) bypass the normal page wrapper and sidebar—they return raw component inside `AppCtx.Provider`.

**Nav bar** lists routes; active tab is computed smartly: flow/pixel/team pages all highlight "teams", run pages highlight "runs".

---

## AppCtx (Global State)

Created in `App.jsx`, provides app-wide context via `useApp()`:

```javascript
const { models, tools, skills, paramSpecs, health, reloadCatalogs, theme } = useApp();
```

**State members**:
- `models` — object: `{ ollama: [string], lmstudio: [string] }` — discovered chat models
- `tools` — object: `{ builtin: [{name, description}], custom: [{name, file, description}] }`
- `skills` — array: `[{id, name, icon, description, instructions, builtin}]` — reusable prompt directives
- `paramSpecs` — array: `[{key, label, min, max, step, default, hint}]` — model hyperparameter definitions
- `health` — object: `{ providers: { ollama: {up, models, url, ...}, lmstudio: {up, models, url, ...} } }` — provider status, polled every 15s
- `reloadCatalogs()` — function: re-fetches `/tools` and `/skills` (called after creating/deleting tools)
- `theme` — string: `"dark"` or `"light"`, persisted in localStorage, toggles `data-theme` on `<html>`

**Initialization**:
- On mount, fetches `/models`, `/params`, `/tools`, `/skills`, and starts health poll
- Theme defaults to system preference or saved value

---

## Pages

| File | Route | Purpose |
|------|-------|---------|
| `Teams.jsx` | `#/teams` | Grid of team cards; create/edit/duplicate/delete; jump to team detail or editors |
| `TeamPage.jsx` | `#/team/:id` | Single team: flow preview, task input, run launcher, live timeline |
| `Runs.jsx` | `#/runs` | Table of all run history with status/duration/time |
| `RunDetail.jsx` | `#/run/:id` | Single run: task, live or persisted timeline of events |
| `Models.jsx` | `#/models` | Lists discovered models from Ollama and LM Studio; includes Fooocus image generation UI; links to Setup and Settings |
| `Personas.jsx` | `#/personas` | Grid of reusable agent templates (prompt, model, tools, skills); CRUD via modal |
| `Toolbox.jsx` | `#/toolbox` | Skills gallery + custom tool file editor; inline AI wizard for both |
| `Setup.jsx` | `#/setup` | Installation wizards for Ollama and LM Studio; system info and install guides |
| `Settings.jsx` | `#/settings` | Hardware assessment, model compatibility verdicts, dream team suggestions |
| `Chat.jsx` | `#/chat` | Direct chat with persona config (prompt, model, params, tools, skills). Persisted chat history sidebar with CRUD; load, save, rename, and delete past conversations from backend |
| `Knowledge.jsx` | `#/knowledge` | Markdown vault browser with search; displays frontmatter and content |
| `FlowEditor.jsx` | `#/flow/:id` (full viewport) | @xyflow/react canvas: drag agents, connect, edit config in right panel |
| `PixelStudio.jsx` | `#/pixel/:id` (full viewport) | GBA-style canvas: pixel sprites, drag nodes, connect mode, live run animation |

---

## Components

| File | Purpose | Pages that use it |
|------|---------|-------------------|
| `AgentFields.jsx` | Form block for agent-like objects: name, role, model picker, system prompt, hyperparams, tools, skills. Exported: `AgentFields` (default), `ModelSelect`, `ParamsEditor`, `ToolsPicker`, `SkillsPicker` | `Personas`, `Toolbox` (modal), `FlowEditor`, `PixelStudio`, `Chat`, `TeamPage`, `TeamEditor` |
| `CatalogTable.jsx` | Searchable model catalog table with category filters, install buttons, and dream team cards. Polls install status. | `Models`, `Settings` (both as `<CatalogTable />` and `<CatalogTable dreamOnly />`) |
| `GraphEditor.jsx` | Read-only @xyflow/react graph viewer used in TeamEditor for topology="graph" teams. Supports add/delete nodes and edges. | `TeamEditor` (modal) |
| `ImageGen.jsx` | Fooocus-API install/start/generate UI + gallery. Shows install progress, generation parameters (prompt, negative, aspect, performance), and displays recently generated images. | `Models` (as a section card) |
| `ImageModels.jsx` | Table of local image generation models (Stable Diffusion runners). | `Settings` |
| `TeamEditor.jsx` | Modal: create/edit teams. Handles all topologies (pipeline, supervisor, graph), agents list, settings (quality_loop, parallel). Includes integrated AI wizard (WizardPanel with kind=team) for drafting team from prose description. Uses `AgentFields` for each agent and `GraphEditor` for graph topology. | `Teams`, `TeamPage` (modal) |
| `Timeline.jsx` | Renders a sequence of event items (banners, step cards, decisions, artifact files, errors, final output). Powers live and persisted run display. Includes `StepCard`, `FinalCard`, `Artifacts` (with Download-all ZIP button). Exported: `Timeline` (default), `useRunStream`, `itemsFromPersistedEvents` | `TeamPage`, `RunDetail`, `FlowEditor`, `PixelStudio` |
| `WizardPanel.jsx` | Shared AI-wizard panel for generating drafts. `kind` prop selects: `skill` (draft a behavior instruction), `tool` (draft Python tool code), or `team` (draft multi-agent ensemble). Includes model picker and refinement feedback loop. | `Toolbox` (for skills/tools), `TeamEditor` (for team drafts) |

---

## Key Shared Mechanisms

### API Helper (`lib/api.js`)

```javascript
async function api(path, opts = {})  // → Promise<json>
```
- Fetches from `/api` (proxied in dev, served by Flask in prod)
- Auto-serializes `opts.body` to JSON; sets `Content-Type: application/json`
- On error: extracts text, strips HTML tags, throws Error with message (first 220 chars)
- Used everywhere for CRUD and event polling

**Utility functions**:
- `fmtTime(ts)` — Unix timestamp → locale string (month, day, hour, minute)
- `fmtDur(a, b)` — Duration between two timestamps → "5m 23s" format
- `toast(msg, isErr)` — Ephemeral notification (3.2s, red if error); creates `#toast-root` div on demand

### Markdown Renderer (`lib/markdown.jsx`)

Tiny dependency-free renderer. Supports:
- Inline: backticks, `**bold**`, `*italic*`, `***bold-italic***`, `[link](https://...)`
- Block: headings (`#`–`######`), lists (ul/ol), blockquotes, tables (`|...|`)
- Code fences (stores blocks separately, replaces with placeholder, restores with `<pre data-lang>`)
- Copy button auto-wired: `window.__copyCode(btn)` copies code to clipboard

**Exported**:
- `renderMd(src)` — returns HTML string
- `<Md text={...} className={...} />` — React component wrapper

### SSE Streaming Patterns

**Live run events** (`Timeline.jsx::useRunStream`):
- Opens `EventSource('/api/runs/:id/events')`, listens for server-sent events
- Parses JSON from `data:` lines
- Handles event types: `run_start`, `agent_start`, `token`, `tool_call`, `tool_result`, `agent_end`, `decision`, `error`, `run_end`
- Builds array of timeline items (banners, steps, decisions)
- Returns `{ items, live }` for Timeline to render

**Chat streaming** (`Chat.jsx`):
- Fetches `/api/chat` with AbortController
- Reads response body as stream via `resp.body.getReader()`
- Decodes chunks with `TextDecoder`, buffers by `\n\n` boundaries
- Parses SSE format (looks for `data:` prefix), updates UI incrementally
- Supports `type`: `token` (append to content), `tool_call`/`tool_result` (push to tools array), `done`/`error` (finalize message)

**Persisted events** (`Timeline.jsx::itemsFromPersistedEvents`):
- Reconstructs timeline from `run.events` array (stored in DB)
- Matches `agent_end` events to their preceding `agent_start` to extract metadata and step content
- Used when viewing completed runs without live stream

### AgentFields Component

Reusable form for configuring agent-like objects (team agents, personas, chat persona).
Exports sub-components:
- `<ModelSelect provider={prov} model={m} onChange={(prov, model) => ...} />` — dropdown from AppCtx models
- `<ParamsEditor params={obj} onChange={next} />` — collapsible grid of hyperparameter sliders (from AppCtx.paramSpecs)
- `<ToolsPicker selected={[...]} onChange={next} />` — tag chips for builtin and custom tools
- `<SkillsPicker selected={[...]} onChange={next} />` — tag chips for skills from AppCtx

Main export `<AgentFields value={agent} onChange={setAgent} namePlaceholder={...} />` composes all fields above.

### GraphEditor Component

Lightweight @xyflow/react graph viewer (different from the full FlowEditor):
- Converts `graph` object `{nodes: [{id, agent}], edges: [{source, target}], positions: {id: {x, y}}}` to React Flow nodes/edges
- Renders agent dropdown to add nodes, delete/connect UI
- Used in TeamEditor modal to visualize and edit graph topology teams
- Less featureful than FlowEditor (no drag-to-add from palette, no run panel)

### FlowEditor Page

Full-viewport @xyflow/react-based team graph editor:
- Left sidebar: persona palette (drag onto canvas to add agents)
- Center canvas: interactive graph with START/END terminals
- Right panel (when node selected): `<AgentFields />` for editing the agent
- Bottom-right (when run open): task input + Timeline

**Data flow**:
1. Load team → `teamToFlow()` converts to React Flow format
2. User edits → mark dirty
3. Save → `flowToTeam()` reconstructs team object, `/teams/:id` PUT
4. Run → POST `/teams/:id/runs` with task, stream events via `useRunStream`

### PixelStudio Page

GBA-style animated pixel canvas (no libraries for rendering—pure `<canvas>` with `ctx.fillRect` etc.):
- **Sprites**: procedurally drawn 16×16 pixel robots (head, eyes, body, arms, legs); sprite sheet colors hash from agent name
- **World**: grid of nodes (agents) and edges (connections); drag to reposition
- **Animation**: blinks, arm waves when working, color changes for states (idle/working/done/error)
- **Packets**: small yellow circles travel along edges during agent hand-offs (visual feedback of work flow)
- **Dialogue box**: GBA-style text box at bottom narrates events ("Agent X is working…", "Run completed!")
- **Connect mode**: toggle to visually link agents (highlights source with pulsing circle)

**Event handling** (from `/api/runs/:id/events` EventSource):
- `agent_start` → set sprite to "working", animate arms
- `agent_end` → set sprite to "done" or "error", stop animation
- `run_start/run_end` → update HUD message
- Display decision/error/tool_call events in the dialogue box

---

## Theming

**CSS Variables** (`styles.css`):
- Dark/light mode toggle at `App.jsx` bottom-right
- Theme stored in localStorage, read on mount (falls back to system preference)
- Root element gets `data-theme="dark"` or `data-theme="light"`
- All colors defined as CSS custom properties (e.g., `--bg`, `--text-1`, `--text-3`, `--blue`, `--green`, `--red`)

**Implementation**:
```javascript
// App.jsx
const [theme, setTheme] = useState(initialTheme());
useEffect(() => {
  document.documentElement.dataset.theme = theme;
  localStorage.setItem("theme", theme);
}, [theme]);
```

**In CSS**: use `@media (prefers-color-scheme: dark)` as fallback for new color definitions; components access colors via `var(--color-name)`.

---

## File Structure

```
frontend/
├── src/
│   ├── App.jsx                    # Router, AppCtx, nav, layout
│   ├── main.jsx                   # React entry point
│   ├── styles.css                 # Global styles + theme vars
│   ├── lib/
│   │   ├── api.js                 # HTTP client, toast, formatters
│   │   └── markdown.jsx           # renderMd + <Md /> component
│   ├── pages/                      # 13 page components
│   │   ├── Teams.jsx
│   │   ├── TeamPage.jsx
│   │   ├── Runs.jsx
│   │   ├── RunDetail.jsx
│   │   ├── Models.jsx
│   │   ├── Personas.jsx
│   │   ├── Toolbox.jsx
│   │   ├── Setup.jsx
│   │   ├── Settings.jsx
│   │   ├── Chat.jsx
│   │   ├── Knowledge.jsx
│   │   ├── FlowEditor.jsx
│   │   └── PixelStudio.jsx
│   └── components/                 # 6 shared components
│       ├── AgentFields.jsx
│       ├── CatalogTable.jsx
│       ├── GraphEditor.jsx
│       ├── ImageModels.jsx
│       ├── TeamEditor.jsx
│       └── Timeline.jsx
├── vite.config.js
├── package.json
└── index.html

static/dist/              # Build output (generated)
├── index.html
├── assets/
│   └── [chunks].js
└── ...
```

---

## Common Development Patterns

**Adding a new page**:
1. Create `src/pages/NewPage.jsx`, export default component `NewPage({ param })`
2. Import in `App.jsx`
3. Add route case in the render logic
4. Update NAV array if it should appear in sidebar

**Modifying team structure**:
1. Teams have `topology: "pipeline" | "supervisor" | "graph" | "single"`
2. `graph` topology has explicit `graph: {nodes: [{id, agent}], edges: [...], positions: {...}}`
3. Non-graph topologies compute a default linear graph on-the-fly
4. FlowEditor and PixelStudio both convert between team and graph representation

**Streaming long outputs**:
- Use `useRunStream(runId)` if the run is live, or `itemsFromPersistedEvents(run)` for completed runs
- Both return items array compatible with `<Timeline items={...} />`
- Chat also streams directly via fetch reader (not SSE); see Chat.jsx send() for the pattern

**Styling new components**:
- Use BEM-like class naming (`card`, `btn`, `primary`, `ghost`, `danger`, etc.)
- Access theme colors via `var(--color)` CSS variables
- Dark mode automatically applies if user has toggled theme or system prefers dark
