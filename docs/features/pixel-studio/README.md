# Pixel Studio
> Part of Local Agents Studio. Read docs/index.md for the doc map.

## What it is

A Game-Boy-Advance-style animated view of a team: agents are procedurally
drawn 16×16 pixel-robot sprites on a `<canvas>` (no image assets), draggable
and connectable like a lightweight graph editor, with GBA-style dialogue-box
narration and hand-off "packet" animations during a live run. It edits the
same `team.graph` data model as the flow canvas, through a different UX.

## Key files

| Path | Role |
|------|------|
| `frontend/src/pages/PixelStudio.jsx` | The entire feature — canvas rendering, drag/connect input handling, its own run-event wiring, save. |

There is no dedicated backend file: this page only consumes the teams-runs
API (`GET/PUT /api/teams/:id`, `POST /api/teams/:id/runs`,
`GET /api/runs/:id/events`) — see `docs/features/teams-runs/`.

## API

Owns no routes. Reuses:
- `GET /api/teams/:id` / `PUT /api/teams/:id` (graph read/write).
- `POST /api/teams/:id/runs` + a **raw `EventSource`** against
  `GET /api/runs/:id/events` (this page does not use `Timeline.jsx`'s
  `useRunStream` — it drives the SSE connection itself to control sprite
  state directly; see Gotchas).

## How it works

- **Sprites**: `drawSprite()` draws a 16×16 robot (antenna, head, eyes, body,
  chest light, arms, legs, shadow) with `ctx.fillRect` calls only — no image
  assets. Per-agent color is derived by hashing the agent name to a hue
  (`hashHue`/`bodyColors`), so the same agent always gets the same color.
  Animation state (`idle|working|done|error`) drives arm-wave, eye
  blink/error-X, and chest-light color; frames are read from a global
  `frame` counter (`requestAnimationFrame` loop) rather than per-sprite
  timers.
- **World model** lives in a mutable `useRef` (`stateRef`), not React state,
  for per-frame performance: `nodes` `{id, agent, x, y}`, `edges`, `sprites`
  (per-agent `{mode, since}`), `packets` (hand-off dots, `{from, to, t}`
  interpolated 0→1 over ~50 frames), `hud` text, `frame`, drag/connect state.
- Non-graph teams get the same straight-chain graph fallback as the flow
  canvas on load, and the page marks itself dirty.
- **Drag**: mouse-down on a node captures a drag offset; mouse-move writes
  directly into `stateRef.current.nodes[i].x/y` (bypassing React re-renders
  until the next animation frame draws it); mouse-up marks the page dirty.
- **Connect mode**: a toggle button; first click on a node sets
  `connectFrom`, second click on a different node pushes a new
  `{source, target}` edge (deduped) and clears `connectFrom`. Toggling
  connect mode off mid-gesture resets `connectFrom`.
- **Save** reconstructs the graph from the current node/edge state and
  infers `start`/`end` edges from connectivity: any node with **no incoming
  edge** gets a synthetic `start → node` edge; any node with **no outgoing
  edge** gets `node → end`. This is different from `FlowEditor`, which keeps
  explicit start/end terminal nodes at all times.
- **Run**: opens its own `EventSource`, independent from `Timeline.jsx`.
  `agent_start` → sprite `"working"` + HUD text + (if there was a previously
  finished agent) a packet animated from that agent's node to this one, as a
  visual (not graph-derived) hand-off cue. `agent_end` → sprite
  `"done"`/`"error"` (based on `meta.verdict === "revise"`). `decision` /
  `tool_call` / `error` events update the HUD dialogue box (2-line word-wrap,
  `wrapText`). `run_end` sets every sprite to `"done"` on success or shows a
  "stopped" HUD line on cancellation.

## Gotchas

- **Duplicate SSE handling.** This page reimplements run-event handling
  instead of reusing `Timeline.jsx`'s `useRunStream` — if a new event type or
  a `meta` shape changes in `engine.py`/`runmanager.py`, update **both**
  `Timeline.jsx` and `PixelStudio.jsx`'s `es.onmessage` handler, or they will
  silently drift apart.
- **Packet animation is not graph-derived.** The hand-off dot travels from
  "whichever agent last finished" to "whichever agent just started" — in a
  parallel/graph run this can visually suggest a hand-off between two agents
  that aren't actually connected by an edge.
- **Save infers start/end from connectivity, not intent.** A node with no
  edges at all gets *both* a synthetic `start→node` and `node→end` edge
  (since it has neither incoming nor outgoing), turning an accidentally
  disconnected node into a valid but pointless single-hop branch instead of
  causing a client-side error — any real problem only surfaces from the
  server-side `_validate_graph` check (`docs/features/flow-canvas/`).
- Shares `team.graph` with the flow canvas and `GraphEditor` — same
  "last save wins on positions/topology" caveat described in
  `docs/features/flow-canvas/`.

## How to verify

1. Open `#/pixel/<id>` for a seeded graph team (`Panel Discussion`).
2. Drag two agent sprites to new positions, toggle **Connect mode**, click
   one agent then another to link them, click **Save**, then
   `GET /api/teams/<id>` and confirm `graph.positions` and `graph.edges`
   reflect the change.
3. Type a task and **Run**; watch sprites cycle `idle → working → done`
   (arm-wave while working, blink cycle, chest-light color change) and the
   dialogue box update with agent/decision/tool text.
4. Give a task likely to trigger a reviewer `REVISE` or an error, and confirm
   the sprite shows the error pose (X eyes, red bubble) rather than "done".
5. Reload the team page after a run and confirm positions saved from Pixel
   Studio persist (and, per the shared-field gotcha above, that they weren't
   silently overwritten by a later Flow Canvas save).
