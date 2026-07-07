import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ReactFlow, Background, Controls, MiniMap, Handle, Position,
  useNodesState, useEdgesState, addEdge, useReactFlow, ReactFlowProvider,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { api, toast } from "../lib/api.js";
import { useApp } from "../App.jsx";
import AgentFields from "../components/AgentFields.jsx";
import Timeline, { useRunStream } from "../components/Timeline.jsx";

/* ---------------- canvas nodes ---------------- */

function AgentCard({ data, selected }) {
  const a = data.agent;
  return (
    <div className={"flow-node-card" + (selected ? " selected" : "")}>
      <Handle type="target" position={Position.Left} />
      <div className="fnc-head">
        <span className="fnc-icon">{a.icon || "🤖"}</span>
        <div className="fnc-title">
          <div className="fnc-name">{a.name}</div>
          <div className="fnc-role">{a.role || "agent"}</div>
        </div>
      </div>
      <div className="fnc-meta">
        <span className="chip">{a.model || "no model"}</span>
        {(a.tools || []).length > 0 && <span className="chip">🛠 {a.tools.length}</span>}
        {(a.skills || []).length > 0 && <span className="chip">✨ {a.skills.length}</span>}
      </div>
      <Handle type="source" position={Position.Right} />
    </div>
  );
}
function StartCard() {
  return (
    <div className="rf-node-terminal start">🏁 START
      <Handle type="source" position={Position.Right} /></div>
  );
}
function EndCard() {
  return (
    <div className="rf-node-terminal"><Handle type="target" position={Position.Left} />
      ⏹ END</div>
  );
}
const nodeTypes = { agent: AgentCard, start: StartCard, end: EndCard };

/* ---------------- helpers ---------------- */

let nid = 0;
const newId = () => `n${Date.now() % 1000000}_${++nid}`;

function teamToFlow(team) {
  const agents = Object.fromEntries((team.agents || []).map((a) => [a.name, a]));
  let graph = team.graph;
  if (team.topology !== "graph" || !graph) {
    // Convert: straight chain through the agents.
    const ids = (team.agents || []).map(() => newId());
    graph = {
      nodes: (team.agents || []).map((a, i) => ({ id: ids[i], agent: a.name })),
      edges: [
        ...(ids.length ? [{ source: "start", target: ids[0] }] : []),
        ...ids.slice(1).map((id, i) => ({ source: ids[i], target: id })),
        ...(ids.length ? [{ source: ids.at(-1), target: "end" }] : []),
      ],
      positions: Object.fromEntries([
        ["start", { x: 20, y: 220 }], ["end", { x: 320 + ids.length * 260, y: 220 }],
        ...ids.map((id, i) => [id, { x: 240 + i * 260, y: 200 }]),
      ]),
    };
  }
  const pos = graph.positions || {};
  const nodes = [
    { id: "start", type: "start", position: pos.start || { x: 20, y: 220 }, data: {}, deletable: false },
    ...graph.nodes.map((n, i) => ({
      id: n.id, type: "agent",
      position: pos[n.id] || { x: 240 + i * 260, y: 200 },
      data: { agent: { ...(agents[n.agent] || { name: n.agent }) } },
    })),
    { id: "end", type: "end", position: pos.end || { x: 900, y: 220 }, data: {}, deletable: false },
  ];
  const edges = (graph.edges || []).map((e, i) => ({
    id: `e${i}`, source: e.source, target: e.target, animated: true,
  }));
  return { nodes, edges };
}

function flowToTeam(draft, nodes, edges) {
  const seen = new Set();
  const agents = [];
  const nameOf = {};
  for (const n of nodes.filter((x) => x.type === "agent")) {
    let name = (n.data.agent.name || "Agent").trim() || "Agent";
    let i = 2;
    while (seen.has(name.toLowerCase())) name = `${n.data.agent.name} ${i++}`;
    seen.add(name.toLowerCase());
    nameOf[n.id] = name;
    agents.push({ ...n.data.agent, name });
  }
  const positions = {};
  for (const n of nodes) positions[n.id] = { x: Math.round(n.position.x), y: Math.round(n.position.y) };
  return {
    ...draft,
    topology: "graph",
    agents,
    graph: {
      nodes: nodes.filter((n) => n.type === "agent").map((n) => ({ id: n.id, agent: nameOf[n.id] })),
      edges: edges.map((e) => ({ source: e.source, target: e.target })),
      positions,
    },
  };
}

/* ---------------- main editor ---------------- */

function Editor({ teamId }) {
  const { models, theme } = useApp();
  const [draft, setDraft] = useState(null);
  const [nodes, setNodes, onNodesChange] = useNodesState([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);
  const [selected, setSelected] = useState(null);
  const [personas, setPersonas] = useState([]);
  const [dirty, setDirty] = useState(false);
  const [runOpen, setRunOpen] = useState(false);
  const [task, setTask] = useState("");
  const [runId, setRunId] = useState(null);
  const [running, setRunning] = useState(false);
  const rf = useReactFlow();

  useEffect(() => {
    api(`/teams/${teamId}`).then((t) => {
      setDraft(t);
      const { nodes: n, edges: e } = teamToFlow(t);
      setNodes(n);
      setEdges(e);
      if (t.topology !== "graph") setDirty(true);
    }).catch(() => (location.hash = "#/teams"));
    api("/personas").then(setPersonas).catch(() => {});
  }, [teamId]);

  const { items } = useRunStream(runId, () => setRunning(false));

  const markDirty = () => setDirty(true);

  const onConnect = useCallback((c) => {
    if (c.source === c.target) return;
    setEdges((eds) => addEdge({ ...c, animated: true }, eds));
    markDirty();
  }, [setEdges]);

  const selNode = nodes.find((n) => n.id === selected && n.type === "agent");

  const updateSelAgent = (agent) => {
    setNodes((ns) => ns.map((n) => n.id === selected ? { ...n, data: { agent } } : n));
    markDirty();
  };

  const defaultModel = () => {
    const pick = (l) => l.find((m) => /^(qwen|llama|mistral|gemma)/i.test(m) && !/r1|coder|think/i.test(m)) || l[0] || "";
    return { provider: (models.ollama || []).length ? "ollama" : "lmstudio",
             model: pick(models.ollama || []) || pick(models.lmstudio || []) };
  };

  const addAgentNode = (persona, position) => {
    const base = defaultModel();
    const agent = persona ? {
      name: persona.name, icon: persona.icon, role: persona.role,
      provider: persona.model ? persona.provider : base.provider,
      model: persona.model || base.model,
      system_prompt: persona.system_prompt,
      params: { ...(persona.params || {}) },
      tools: [...(persona.tools || [])], skills: [...(persona.skills || [])],
    } : { name: "New Agent", icon: "🤖", role: "", ...base, system_prompt: "", params: {}, tools: [], skills: [] };
    const id = newId();
    const pos = position || rf.screenToFlowPosition({
      x: window.innerWidth / 2, y: window.innerHeight / 2 - 60 });
    setNodes((ns) => [
      ...ns.map((n) => ({ ...n, selected: false })),
      { id, type: "agent", position: pos, data: { agent }, selected: true },
    ]);
    setSelected(id);
    markDirty();
  };

  const onDrop = useCallback((e) => {
    e.preventDefault();
    const pid = e.dataTransfer.getData("application/x-persona");
    const pos = rf.screenToFlowPosition({ x: e.clientX, y: e.clientY });
    if (pid === "blank") { addAgentNode(null, pos); return; }
    const p = personas.find((x) => x.id === +pid);
    if (p) addAgentNode(p, pos);
  }, [personas, rf, nodes]);

  const save = async () => {
    const body = flowToTeam(draft, nodes, edges);
    try {
      const saved = await api(`/teams/${teamId}`, { method: "PUT", body });
      setDraft(saved);
      setDirty(false);
      toast("Flow saved");
      return true;
    } catch (e) { toast(e.message, true); return false; }
  };

  const run = async () => {
    if (!task.trim()) { toast("Describe a task first", true); return; }
    if (dirty && !(await save())) return;
    try {
      const { run_id } = await api(`/teams/${teamId}/runs`, { method: "POST", body: { task: task.trim() } });
      setRunId(run_id);
      setRunning(true);
    } catch (e) { toast("Failed to start: " + e.message, true); }
  };

  if (!draft) return null;

  return (
    <div className="flow-page">
      <div className="flow-topbar">
        <button className="btn ghost" onClick={() => (location.hash = `#/team/${teamId}`)}>←</button>
        <span className="fnc-icon" style={{ fontSize: 18 }}>{draft.icon}</span>
        <input className="flow-name" value={draft.name}
          onChange={(e) => { setDraft({ ...draft, name: e.target.value }); markDirty(); }} />
        <span className="chip topo">custom pipeline</span>
        <label className="switch-row" style={{ marginLeft: 10 }}>
          <input type="checkbox" checked={!!draft.settings?.parallel}
            onChange={(e) => { setDraft({ ...draft, settings: { ...draft.settings, parallel: e.target.checked } }); markDirty(); }} />
          parallel branches
        </label>
        <span className="spacer" style={{ flex: 1 }} />
        {dirty && <span className="help">unsaved changes</span>}
        <button className="btn" onClick={save}>💾 Save</button>
        <button className="btn primary" onClick={() => setRunOpen(!runOpen)}>
          {runOpen ? "Hide run panel" : "▶ Run"}
        </button>
      </div>

      <div className="flow-body">
        <div className="flow-palette">
          <div className="flow-palette-head">Drag onto the canvas</div>
          <div className="palette-item" draggable
            onDragStart={(e) => e.dataTransfer.setData("application/x-persona", "blank")}
            onClick={() => addAgentNode(null)}>
            ＋ <span>Blank agent</span>
          </div>
          {personas.map((p) => (
            <div key={p.id} className="palette-item" draggable title={p.description}
              onDragStart={(e) => e.dataTransfer.setData("application/x-persona", String(p.id))}
              onClick={() => addAgentNode(p)}>
              {p.icon} <span>{p.name}</span>
            </div>
          ))}
        </div>

        <div className="flow-canvas" onDrop={onDrop} onDragOver={(e) => e.preventDefault()}>
          <ReactFlow
            nodes={nodes} edges={edges} nodeTypes={nodeTypes}
            onNodesChange={(c) => { onNodesChange(c); if (c.some((x) => x.type !== "select" && x.type !== "dimensions")) markDirty(); }}
            onEdgesChange={(c) => { onEdgesChange(c); if (c.some((x) => x.type === "remove")) markDirty(); }}
            onConnect={onConnect}
            onSelectionChange={({ nodes: sel }) => setSelected(sel[0]?.id || null)}
            fitView colorMode={theme || "light"}
            proOptions={{ hideAttribution: true }}
            deleteKeyCode={["Delete", "Backspace"]}
          >
            <Background gap={18} size={1.4} />
            <Controls showInteractive={false} />
            <MiniMap pannable zoomable className="flow-minimap" />
          </ReactFlow>
        </div>

        {selNode && (
          <div className="flow-panel">
            <div className="flow-panel-head">
              <span>{selNode.data.agent.icon || "🤖"} Configure agent</span>
              <button className="btn sm danger" onClick={() => {
                setNodes((ns) => ns.filter((n) => n.id !== selected));
                setEdges((es) => es.filter((e) => e.source !== selected && e.target !== selected));
                setSelected(null);
                markDirty();
              }}>🗑 Remove</button>
            </div>
            <div className="flow-panel-body">
              <AgentFields value={selNode.data.agent} onChange={updateSelAgent} />
            </div>
          </div>
        )}

        {runOpen && (
          <div className="flow-panel run">
            <div className="flow-panel-head"><span>▶ Run this flow</span></div>
            <div className="flow-panel-body">
              <textarea rows={3} value={task} placeholder="Describe the task…"
                onChange={(e) => setTask(e.target.value)} style={{ width: "100%" }} />
              <div style={{ display: "flex", gap: 8, margin: "8px 0 14px" }}>
                <button className="btn primary" disabled={running} onClick={run}>
                  {running ? "Running…" : dirty ? "▶ Save & run" : "▶ Run"}
                </button>
                {running && runId && (
                  <button className="btn danger" onClick={() =>
                    api(`/runs/${runId}/stop`, { method: "POST", body: {} }).catch(() => {})}>■ Stop</button>
                )}
              </div>
              {runId && <Timeline items={items} runId={runId} />}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

export default function FlowEditor({ teamId }) {
  return (
    <ReactFlowProvider>
      <Editor teamId={teamId} />
    </ReactFlowProvider>
  );
}
