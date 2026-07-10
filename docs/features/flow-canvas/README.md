# Flow Canvas
> Part of Local Agents Studio. Read docs/index.md for the doc map.

## What it is

The visual node-based editor for a team's `graph` topology, built on
`@xyflow/react`. There are two independent views over the same data model: a
full-viewport page (`FlowEditor.jsx`, drag-and-drop palette, run panel) and a
lighter embedded editor (`GraphEditor.jsx`, used inside `TeamEditor`'s modal
for any team with `topology: "graph"`). Neither owns backend routes — graph
data travels inside the team object through the normal `/api/teams` routes
(see `docs/features/teams-runs/`); this feature's only unique backend logic
is the graph *validator*.

## Key files

| Path | Role |
|------|------|
| `app.py` (`_validate_graph`) | Validates `{nodes, edges, positions}` on team save: acyclic, reachable, connected to start/end. |
| `frontend/src/pages/FlowEditor.jsx` | Full-viewport page at `#/flow/:id`. Persona drag-drop palette, canvas, agent config panel, run panel with `Timeline`. |
| `frontend/src/components/GraphEditor.jsx` | Embedded graph viewer/editor used inside `TeamEditor`'s modal (no palette, no run panel — just nodes/edges). |
| `frontend/src/components/AgentFields.jsx` | Right-hand config panel for the selected node (shared editor). |
| `frontend/src/components/Timeline.jsx` | Run panel output in `FlowEditor`. |
| `storage.py` | `teams.graph` column (JSON, nullable). |

## API

This feature has no routes of its own. The graph lives at `team.graph` and
is validated by `_validate_graph` (in `app.py`) whenever `POST/PUT
/api/teams` is called with `topology: "graph"` — see
`docs/features/teams-runs/` for the full teams API. Validation rules,
enforced server-side (400 on failure, nothing is silently dropped like
tools/skills are):

- Every node needs a unique `id`, not `"start"` or `"end"` (those are
  virtual and never appear in `nodes`).
- Every node's `agent` must reference an existing agent name on the team.
- Every edge's `source`/`target` must be a known node id, or `"start"`/`"end"`.
- At least one edge from `"start"`, at least one edge to `"end"`.
- The graph must be acyclic (Kahn's algorithm) and every node reachable from
  `"start"`.
- `positions` entries are kept only for ids that still exist.

## Data model

```json
{"nodes": [{"id": "n1", "agent": "Researcher"}],
 "edges": [{"source": "start", "target": "n1"}, {"source": "n1", "target": "end"}],
 "positions": {"start": {"x": 20, "y": 220}, "n1": {"x": 240, "y": 200}, "end": {"x": 500, "y": 220}}}
```
`start`/`end` are virtual ids used only in `edges`/`positions`, never listed
in `nodes`. See `docs/features/teams-runs/` for how `engine._build_graph`
executes this at runtime (multi-source edges become an AND-join).

## How it works

- **`FlowEditor.jsx`**: `teamToFlow()` converts a team into React Flow
  nodes/edges (start/end terminal cards + one card per agent); `flowToTeam()`
  reconstructs the team object on save, **always forcing
  `topology: "graph"`**. If the loaded team's topology wasn't already
  `"graph"`, `teamToFlow` synthesizes a straight-chain graph for display and
  the page immediately marks itself dirty.
- Drag a persona (or "blank agent") from the left palette onto the canvas to
  add a node at the drop position; selecting a node opens the right-hand
  `AgentFields` panel.
- Save does `PUT /api/teams/:id` with the reconstructed graph; Run first
  saves if dirty, then `POST /api/teams/:id/runs` and streams via
  `useRunStream` into an embedded `Timeline`, same as `TeamPage`.
- **`GraphEditor.jsx`** is the same data model, different UX: a dropdown +
  "Add node" button (no drag-drop from a palette), connect by dragging
  between handles, delete via selection + Delete key. It only edits nodes
  currently in the team's `agents` list — it can't add a *new* agent, only
  wire existing ones. Used inline inside `TeamEditor`'s modal so
  `topology: "graph"` teams can be edited without leaving the modal.
- Branches that fan out from one node run as parallel LangGraph supersteps;
  actual LLM concurrency is still gated by the team's `parallel` setting and
  hardware capacity (see `docs/features/teams-runs/`), not by the canvas.

## Gotchas

- **Shared graph field**: `FlowEditor`, `GraphEditor` (inside `TeamEditor`),
  and the Pixel Studio (`docs/features/pixel-studio/`) all read/write the
  same `team.graph` — saving from any one of them overwrites node positions
  (and possibly topology) saved by another. There is no merge.
- **Opening the flow canvas can silently convert a team's topology.** Because
  `flowToTeam()` always sets `topology: "graph"`, merely opening a
  `pipeline`/`supervisor` team in `#/flow/:id` and clicking Save converts it
  to a graph team — even if you didn't intend to leave the linear topology.
- A node with multiple incoming edges is an **AND-join** at runtime
  (`engine._build_graph` groups edges by target and waits for all sources) —
  the canvas doesn't distinguish this from an "OR" merge, so a graph that
  visually looks like alternative paths converging actually blocks until
  every path completes.
- `_validate_graph` rejects unknown edge endpoints outright (400) rather than
  dropping them — unlike team-level `tools`/`skills` validation, which drops
  silently. A stale node id left in `edges` after a node was removed
  client-side will fail the whole save.

## How to verify

1. Open `#/flow/<id>` for the seeded `Panel Discussion` team (topology
   `graph`, 3 parallel branches into a synthesizer).
2. Drag a persona onto the canvas, connect it into the graph, then Save —
   `GET /api/teams/<id>` should show the new node/edge/position in `graph`.
3. Open the same team's `TeamEditor` modal (Teams page → ✏️ Edit) and confirm
   `GraphEditor` shows the same graph and that adding/removing a node there
   round-trips correctly on save.
4. Try to save a graph with a node not reachable from `start` (disconnect an
   edge) and confirm the API returns 400 with a clear reachability message.
5. Run the team from the flow panel and confirm `Timeline` shows the three
   branches running (interleaved `agent_start`/`token` events) before the
   synthesizer's `agent_start`.
