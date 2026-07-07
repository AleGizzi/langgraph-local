import React, { useEffect, useRef, useState } from "react";
import { api, toast } from "../lib/api.js";

/* A Game-Boy-Advance-style animated view of a team. Agents are procedurally
 * drawn pixel sprites you can drag around and wire together; during a run they
 * animate (working / done / hand-offs) and a Pokémon-style dialogue box
 * narrates events. Everything is drawn on a <canvas> with nearest-neighbor
 * scaling for the crisp pixel look — no image assets, works offline. */

const TILE = 16;          // logical sprite size
const SCALE = 4;          // on-screen pixels per logical pixel
const GRID = 24;          // world grid cell for snapping

// GBA-ish palette
const PAL = {
  grassA: "#8bc96a", grassB: "#7ec05e", path: "#e8d9a0", pathEdge: "#d4c07f",
  ink: "#20304a", shadow: "rgba(20,30,40,.25)",
  box: "#f8f8e8", boxBorder: "#20304a", boxShade: "#c8c8a8",
};

function hashHue(s) {
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) % 360;
  return h;
}
const bodyColors = (name) => {
  const h = hashHue(name || "a");
  return { main: `hsl(${h} 62% 55%)`, dark: `hsl(${h} 62% 40%)`, light: `hsl(${h} 62% 70%)` };
};

/* draw a 16x16 robot sprite into ctx at (px,py) in *logical* px, given frame */
function drawSprite(ctx, px, py, name, mode, frame) {
  const c = bodyColors(name);
  const bob = mode === "working" ? [0, -1, 0, -1][frame % 4]
    : mode === "done" ? [0, -2, -3, -2][frame % 4] : [0, 0, -1, 0][frame % 4];
  const y = py + bob;
  const P = (x, yy, w, h, col) => { ctx.fillStyle = col; ctx.fillRect(px + x, y + yy, w, h); };
  // shadow
  ctx.fillStyle = PAL.shadow;
  ctx.fillRect(px + 3, py + 15, 10, 2);
  // antenna
  P(7, 0, 2, 2, c.dark);
  P(7, -1, 2, 1, mode === "working" && frame % 2 ? "#ffd23f" : c.light);
  // head
  P(3, 2, 10, 6, c.main);
  P(3, 2, 10, 1, c.light);
  P(3, 7, 10, 1, c.dark);
  // eyes (blink every ~2s)
  const blink = frame % 20 === 0;
  const eyeMode = mode === "error" ? "x" : blink ? "-" : "o";
  ctx.fillStyle = PAL.ink;
  if (eyeMode === "o") { P(5, 4, 2, 2, PAL.ink); P(9, 4, 2, 2, PAL.ink);
    ctx.fillStyle = "#fff"; ctx.fillRect(px + 5, y + 4, 1, 1); ctx.fillRect(px + 9, y + 4, 1, 1); }
  else if (eyeMode === "-") { P(5, 5, 2, 1, PAL.ink); P(9, 5, 2, 1, PAL.ink); }
  else { P(5, 4, 2, 2, "#e8503a"); P(9, 4, 2, 2, "#e8503a"); }
  // body
  P(4, 8, 8, 5, c.main);
  P(4, 8, 8, 1, c.light);
  // chest light
  const lit = mode === "working" ? (frame % 2 ? "#ffd23f" : "#b8862f")
    : mode === "done" ? "#47cd89" : mode === "error" ? "#e8503a" : "#5a7fae";
  P(7, 10, 2, 2, lit);
  // arms (animate when working)
  const armUp = mode === "working" && frame % 2;
  P(2, armUp ? 8 : 9, 2, armUp ? 2 : 3, c.dark);
  P(12, armUp ? 8 : 9, 2, armUp ? 2 : 3, c.dark);
  // legs
  P(5, 13, 2, 2, c.dark);
  P(9, 13, 2, 2, c.dark);
}

export default function PixelStudio({ teamId }) {
  const canvasRef = useRef(null);
  const stateRef = useRef({
    nodes: [], edges: [], sprites: {}, packets: [], hud: "", frame: 0,
    drag: null, connectFrom: null, cam: { x: 0, y: 0 },
  });
  const [team, setTeam] = useState(null);
  const [dirty, setDirty] = useState(false);
  const [connectMode, setConnectMode] = useState(false);
  const connectModeRef = useRef(false);
  connectModeRef.current = connectMode;
  const [task, setTask] = useState("");
  const [running, setRunning] = useState(false);
  const esRef = useRef(null);
  const [, force] = useState(0);

  // ---- load team into world model ----
  useEffect(() => {
    api(`/teams/${teamId}`).then((t) => {
      setTeam(t);
      const S = stateRef.current;
      const agents = Object.fromEntries((t.agents || []).map((a) => [a.name, a]));
      let g = t.graph;
      if (t.topology !== "graph" || !g) {
        const ids = (t.agents || []).map((_, i) => `n${i}`);
        g = {
          nodes: (t.agents || []).map((a, i) => ({ id: ids[i], agent: a.name })),
          edges: [
            ...(ids.length ? [{ source: "start", target: ids[0] }] : []),
            ...ids.slice(1).map((id, i) => ({ source: ids[i], target: id })),
            ...(ids.length ? [{ source: ids.at(-1), target: "end" }] : []),
          ],
          positions: {},
        };
        setDirty(true);
      }
      const pos = g.positions || {};
      S.nodes = g.nodes.map((n, i) => ({
        id: n.id, agent: agents[n.agent] || { name: n.agent },
        x: pos[n.id]?.x ?? 120 + (i % 3) * 170,
        y: pos[n.id]?.y ?? 90 + Math.floor(i / 3) * 150,
      }));
      S.edges = (g.edges || []).filter((e) => e.source !== "start" && e.target !== "end");
      S.hud = `${t.name} — drag agents, connect them, then press Run.`;
    }).catch(() => (location.hash = "#/teams"));
  }, [teamId]);

  // ---- render + animation loop ----
  useEffect(() => {
    let raf;
    const loop = () => {
      const cv = canvasRef.current;
      if (cv) draw(cv);
      stateRef.current.frame++;
      // advance packets
      for (const p of stateRef.current.packets) p.t += 0.02;
      stateRef.current.packets = stateRef.current.packets.filter((p) => p.t < 1);
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
  }, []);

  const nodeCenter = (n) => ({ x: n.x + (TILE * SCALE) / 2, y: n.y + (TILE * SCALE) / 2 });
  const nodeAt = (mx, my) => {
    const S = stateRef.current;
    const w = TILE * SCALE, h = TILE * SCALE;
    return S.nodes.find((n) => mx >= n.x - 6 && mx <= n.x + w + 6 && my >= n.y - 6 && my <= n.y + h + 20);
  };

  function draw(cv) {
    const ctx = cv.getContext("2d");
    const S = stateRef.current;
    const W = cv.width, H = cv.height;
    ctx.imageSmoothingEnabled = false;
    // background tiles
    for (let y = 0; y < H; y += GRID) {
      for (let x = 0; x < W; x += GRID) {
        ctx.fillStyle = ((x / GRID + y / GRID) % 2) ? PAL.grassA : PAL.grassB;
        ctx.fillRect(x, y, GRID, GRID);
      }
    }
    // edges as paths
    for (const e of S.edges) {
      const a = S.nodes.find((n) => n.id === e.source);
      const b = S.nodes.find((n) => n.id === e.target);
      if (!a || !b) continue;
      const ca = nodeCenter(a), cb = nodeCenter(b);
      ctx.strokeStyle = PAL.path; ctx.lineWidth = 7; ctx.lineCap = "round";
      ctx.setLineDash([2, 6]); ctx.lineDashOffset = -S.frame * 0.5;
      ctx.beginPath(); ctx.moveTo(ca.x, ca.y); ctx.lineTo(cb.x, cb.y); ctx.stroke();
      ctx.setLineDash([]);
    }
    // packets (hand-offs) traveling along edges
    for (const p of S.packets) {
      const a = S.nodes.find((n) => n.id === p.from);
      const b = S.nodes.find((n) => n.id === p.to);
      if (!a || !b) continue;
      const ca = nodeCenter(a), cb = nodeCenter(b);
      const x = ca.x + (cb.x - ca.x) * p.t, y = ca.y + (cb.y - ca.y) * p.t;
      ctx.fillStyle = "#ffd23f"; ctx.strokeStyle = PAL.ink; ctx.lineWidth = 1;
      ctx.beginPath(); ctx.arc(x, y, 5, 0, 7); ctx.fill(); ctx.stroke();
      ctx.fillStyle = PAL.ink; ctx.font = "8px monospace"; ctx.fillText("✉", x - 3, y + 3);
    }
    // connect-mode highlight from source
    if (S.connectFrom) {
      const a = S.nodes.find((n) => n.id === S.connectFrom);
      if (a) { const c = nodeCenter(a);
        ctx.strokeStyle = "#155eef"; ctx.lineWidth = 2; ctx.setLineDash([4, 4]);
        ctx.beginPath(); ctx.arc(c.x, c.y, 30 + (S.frame % 20), 0, 7); ctx.stroke(); ctx.setLineDash([]); }
    }
    // sprites
    for (const n of S.nodes) {
      const sp = S.sprites[n.agent.name] || { mode: "idle" };
      ctx.save();
      ctx.translate(n.x, n.y);
      ctx.scale(SCALE, SCALE);
      drawSprite(ctx, 0, 0, n.agent.name, sp.mode, S.frame >> 3);
      ctx.restore();
      // name plate
      ctx.font = "bold 11px monospace"; ctx.textAlign = "center";
      const cx = n.x + (TILE * SCALE) / 2;
      const label = (n.agent.icon ? n.agent.icon + " " : "") + n.agent.name;
      const w = ctx.measureText(label).width + 10;
      ctx.fillStyle = PAL.box; ctx.strokeStyle = PAL.boxBorder; ctx.lineWidth = 1.5;
      ctx.fillRect(cx - w / 2, n.y + TILE * SCALE + 2, w, 15);
      ctx.strokeRect(cx - w / 2, n.y + TILE * SCALE + 2, w, 15);
      ctx.fillStyle = PAL.ink; ctx.fillText(label, cx, n.y + TILE * SCALE + 13);
      // status word bubble
      if (sp.mode && sp.mode !== "idle") {
        const tag = { working: "…", done: "✓", error: "!" }[sp.mode];
        ctx.font = "bold 12px monospace";
        ctx.fillStyle = sp.mode === "done" ? "#47cd89" : sp.mode === "error" ? "#e8503a" : "#fff";
        ctx.strokeStyle = PAL.ink;
        const bx = cx + 18, by = n.y + 2;
        ctx.fillStyle = PAL.box; ctx.fillRect(bx - 2, by - 12, 20, 16); ctx.strokeRect(bx - 2, by - 12, 20, 16);
        ctx.fillStyle = sp.mode === "done" ? "#2a9d5f" : sp.mode === "error" ? "#e8503a" : "#b8862f";
        ctx.fillText(tag, bx + 4, by);
      }
      ctx.textAlign = "left";
    }
    // GBA dialogue box
    const bh = 54, by = H - bh - 10, bx = 12, bw = W - 24;
    ctx.fillStyle = PAL.box; ctx.fillRect(bx, by, bw, bh);
    ctx.strokeStyle = PAL.boxBorder; ctx.lineWidth = 3; ctx.strokeRect(bx, by, bw, bh);
    ctx.strokeStyle = PAL.boxShade; ctx.lineWidth = 1; ctx.strokeRect(bx + 4, by + 4, bw - 8, bh - 8);
    ctx.fillStyle = PAL.ink; ctx.font = "14px monospace"; ctx.textAlign = "left";
    wrapText(ctx, S.hud || "", bx + 14, by + 22, bw - 28, 17);
    // blinking ▼
    if (S.frame % 30 < 20) { ctx.fillText("▼", bx + bw - 24, by + bh - 12); }
  }

  function wrapText(ctx, text, x, y, maxW, lh) {
    const words = String(text).split(" ");
    let line = "", yy = y, lines = 0;
    for (const w of words) {
      if (ctx.measureText(line + w).width > maxW && line) {
        ctx.fillText(line, x, yy); line = ""; yy += lh; if (++lines >= 2) break;
      }
      line += w + " ";
    }
    if (lines < 2) ctx.fillText(line, x, yy);
  }

  const setHud = (msg) => { stateRef.current.hud = msg; };
  const setSprite = (name, mode) => {
    stateRef.current.sprites[name] = { mode, since: Date.now() };
  };

  // ---- mouse: drag nodes / connect ----
  const relPos = (e) => {
    const r = canvasRef.current.getBoundingClientRect();
    return { x: (e.clientX - r.left) * (canvasRef.current.width / r.width),
             y: (e.clientY - r.top) * (canvasRef.current.height / r.height) };
  };
  const onDown = (e) => {
    const { x, y } = relPos(e);
    const n = nodeAt(x, y);
    const S = stateRef.current;
    if (connectModeRef.current) {
      if (!n) return;
      if (!S.connectFrom) { S.connectFrom = n.id; setHud(`Connect: pick where ${n.agent.name} sends its work.`); }
      else if (S.connectFrom !== n.id) {
        if (!S.edges.some((ed) => ed.source === S.connectFrom && ed.target === n.id)) {
          S.edges.push({ source: S.connectFrom, target: n.id }); setDirty(true);
        }
        const from = S.nodes.find((k) => k.id === S.connectFrom);
        setHud(`Linked ${from.agent.name} → ${n.agent.name}.`);
        S.connectFrom = null;
      }
      return;
    }
    if (n) S.drag = { id: n.id, dx: x - n.x, dy: y - n.y };
  };
  const onMove = (e) => {
    const S = stateRef.current;
    if (!S.drag) return;
    const { x, y } = relPos(e);
    const n = S.nodes.find((k) => k.id === S.drag.id);
    if (n) { n.x = x - S.drag.dx; n.y = y - S.drag.dy; }
  };
  const onUp = () => {
    const S = stateRef.current;
    if (S.drag) { S.drag = null; setDirty(true); }
  };

  // ---- save ----
  const save = async () => {
    const S = stateRef.current;
    const positions = {};
    for (const n of S.nodes) positions[n.id] = { x: Math.round(n.x), y: Math.round(n.y) };
    const body = {
      ...team, topology: "graph",
      agents: S.nodes.map((n) => n.agent),
      graph: {
        nodes: S.nodes.map((n) => ({ id: n.id, agent: n.agent.name })),
        edges: [
          // reconnect start/end: start → nodes with no incoming, nodes with no outgoing → end
          ...S.nodes.filter((n) => !S.edges.some((e) => e.target === n.id))
            .map((n) => ({ source: "start", target: n.id })),
          ...S.edges,
          ...S.nodes.filter((n) => !S.edges.some((e) => e.source === n.id))
            .map((n) => ({ source: n.id, target: "end" })),
        ],
        positions,
      },
    };
    try {
      await api(`/teams/${teamId}`, { method: "PUT", body });
      setDirty(false); toast("Pixel layout saved");
      return true;
    } catch (e) { toast(e.message, true); return false; }
  };

  // ---- run with animation ----
  const run = async () => {
    if (!task.trim()) { toast("Type a task first", true); return; }
    if (dirty && !(await save())) return;
    const S = stateRef.current;
    S.sprites = {};
    try {
      const { run_id } = await api(`/teams/${teamId}/runs`, { method: "POST", body: { task: task.trim() } });
      setRunning(true);
      let lastFinished = null;
      const es = new EventSource(`/api/runs/${run_id}/events`);
      esRef.current = es;
      es.onmessage = (msg) => {
        let ev; try { ev = JSON.parse(msg.data); } catch { return; }
        const nodeFor = (agent) => S.nodes.find((n) => n.agent.name === agent);
        if (ev.type === "run_start") setHud("▶ A wild task appears! The team springs into action…");
        else if (ev.type === "agent_start") {
          setSprite(ev.agent, "working");
          setHud(`${ev.agent} is working…`);
          const to = nodeFor(ev.agent);
          const from = lastFinished && nodeFor(lastFinished);
          if (from && to) S.packets.push({ from: from.id, to: to.id, t: 0 });
        } else if (ev.type === "agent_end") {
          setSprite(ev.agent, ev.meta?.verdict === "revise" ? "error" : "done");
          setHud(`${ev.agent} finished its part!`);
          lastFinished = ev.agent;
        } else if (ev.type === "decision") {
          setHud(`🧭 ${ev.agent ? ev.agent + ": " : ""}${(ev.content || "").slice(0, 90)}`);
        } else if (ev.type === "tool_call") {
          setHud(`${ev.agent} uses a tool: ${(ev.content || "").slice(0, 70)}`);
        } else if (ev.type === "error") {
          setHud(`💥 ${(ev.content || "").slice(0, 90)}`);
        } else if (ev.type === "run_end") {
          es.close(); esRef.current = null; setRunning(false);
          if (ev.meta?.status === "done") {
            for (const n of S.nodes) setSprite(n.agent.name, "done");
            setHud("🎉 The team completed the task! Check Runs for the full deliverable.");
          } else if (ev.meta?.status === "cancelled") setHud("■ Run stopped.");
        }
      };
      es.onerror = () => {};
    } catch (e) { toast("Failed to start: " + e.message, true); }
  };

  const stop = () => { esRef.current?.close(); esRef.current = null; setRunning(false); };

  if (!team) return null;
  return (
    <div className="pixel-page">
      <div className="flow-topbar">
        <button className="btn ghost" onClick={() => (location.hash = `#/team/${teamId}`)}>←</button>
        <span style={{ fontSize: 18 }}>👾</span>
        <b style={{ fontSize: 15 }}>{team.name}</b>
        <span className="chip topo">pixel studio</span>
        <button className={"btn" + (connectMode ? " primary" : "")}
          onClick={() => { setConnectMode(!connectMode); stateRef.current.connectFrom = null; }}>
          {connectMode ? "🔗 Connecting… (click two agents)" : "🔗 Connect mode"}
        </button>
        <span className="spacer" style={{ flex: 1 }} />
        {dirty && <span className="help">unsaved</span>}
        <button className="btn" onClick={save}>💾 Save</button>
      </div>
      <div className="pixel-body">
        <canvas
          ref={canvasRef} width={1000} height={640} className="pixel-canvas"
          onMouseDown={onDown} onMouseMove={onMove} onMouseUp={onUp} onMouseLeave={onUp}
        />
        <div className="pixel-runbar">
          <input value={task} onChange={(e) => setTask(e.target.value)}
            placeholder="Give the team a task and watch them work…"
            onKeyDown={(e) => { if (e.key === "Enter") run(); }} />
          {running
            ? <button className="btn danger" onClick={stop}>■ Stop</button>
            : <button className="btn primary" onClick={run}>▶ Run</button>}
        </div>
      </div>
    </div>
  );
}
