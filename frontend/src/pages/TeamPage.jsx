import React, { useEffect, useRef, useState } from "react";
import { api, toast } from "../lib/api.js";
import Timeline, { useRunStream } from "../components/Timeline.jsx";
import TeamEditor from "../components/TeamEditor.jsx";

function FlowPreview({ team }) {
  const s = team.settings || {};
  if (team.topology === "graph" && team.graph) {
    const byId = Object.fromEntries(team.graph.nodes.map((n) => [n.id, n]));
    return (
      <div className="card flow">
        <span className="flow-graph-note">⛓ Custom pipeline · {team.graph.nodes.length} nodes
          {s.parallel ? " · parallel branches enabled" : " · serial execution"}</span>
        {team.graph.edges.map((e, i) => (
          <span key={i} className="flow-node" style={{ fontWeight: 500, fontSize: 12 }}>
            {e.source === "start" ? "▶" : byId[e.source]?.agent || e.source}
            <span className="flow-arrow"> → </span>
            {e.target === "end" ? "⏹" : byId[e.target]?.agent || e.target}
          </span>
        ))}
      </div>
    );
  }
  if (team.topology === "supervisor") {
    return (
      <div className="card flow">
        <span className="flow-node">{team.agents[0].name}
          <span className="m">supervisor · {team.agents[0].model}</span></span>
        <span className="flow-arrow">→</span>
        {team.agents.slice(1).map((a, i) => (
          <React.Fragment key={a.name}>
            {i > 0 && <span className="flow-arrow">·</span>}
            <span className="flow-node">{a.name}<span className="m">{a.model}</span></span>
          </React.Fragment>
        ))}
        <div className="flow-note">
          The supervisor delegates dynamically (max {s.max_steps || 8} steps), then synthesizes the final answer.
        </div>
      </div>
    );
  }
  return (
    <div className="card flow">
      {team.agents.map((a, i) => (
        <React.Fragment key={a.name}>
          {i > 0 && <span className="flow-arrow">→</span>}
          <span className="flow-node">{a.name}<span className="m">{a.model}</span></span>
        </React.Fragment>
      ))}
      {s.quality_loop && (
        <div className="flow-note">
          ↺ Quality loop: {team.agents.at(-1).name} can send work back for up to {s.max_revisions ?? 2} revisions.
        </div>
      )}
    </div>
  );
}

export default function TeamPage({ teamId }) {
  const [team, setTeam] = useState(null);
  const [editing, setEditing] = useState(false);
  const [task, setTask] = useState("");
  const [mode, setMode] = useState("balanced");
  const [runId, setRunId] = useState(null);
  const [running, setRunning] = useState(false);
  const stopDisabled = useRef(false);

  const load = () => api(`/teams/${teamId}`).then(setTeam).catch(() => (location.hash = "#/teams"));
  useEffect(() => { load(); }, [teamId]);

  const { items } = useRunStream(runId, () => setRunning(false));

  const start = async () => {
    if (!task.trim()) { toast("Describe a task first", true); return; }
    try {
      const { run_id } = await api(`/teams/${teamId}/runs`, { method: "POST", body: { task: task.trim(), mode } });
      stopDisabled.current = false;
      setRunId(run_id);
      setRunning(true);
    } catch (e) { toast("Failed to start: " + e.message, true); }
  };

  const stop = async () => {
    if (stopDisabled.current || !runId) return;
    stopDisabled.current = true;
    await api(`/runs/${runId}/stop`, { method: "POST", body: {} }).catch(() => {});
  };

  if (!team) return null;
  return (
    <>
      <div className="team-head">
        <div className="team-icon">{team.icon}</div>
        <div className="grow">
          <h1 className="page-title">{team.name}</h1>
          <p className="page-sub">{team.description || team.topology + " topology"}</p>
        </div>
        <button className="btn" onClick={() => (location.hash = `#/flow/${teamId}`)}>🎨 Canvas</button>
        <button className="btn" onClick={() => (location.hash = `#/pixel/${teamId}`)}>👾 Pixel</button>
        <button className="btn" onClick={() => setEditing(true)}>✏️ Edit</button>
        <button className="btn" onClick={() => (location.hash = "#/runs")}>🗂️ History</button>
      </div>

      <FlowPreview team={team} />

      <div className="card task-box">
        <textarea
          value={task}
          onChange={(e) => setTask(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) start(); }}
          placeholder="Describe the task for this team… e.g. “Write a market overview of open-source LLM tooling in 2026”"
        />
        <div className="task-actions">
          <span className="task-hint">Ctrl+Enter to run · runs entirely on your machine</span>
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <label className="mode-picker" title="Shifts every agent's model along its family size ladder for this run">
              <select value={mode} onChange={(e) => setMode(e.target.value)} disabled={running}>
                <option value="max-savings">⚡ Max savings (smaller, faster)</option>
                <option value="balanced">⚖️ Balanced (as configured)</option>
                <option value="quality">💎 Quality (larger, slower)</option>
              </select>
            </label>
            {running && <button className="btn danger" onClick={stop}>■ Stop</button>}
            <button className="btn primary" disabled={running} onClick={start}>▶ Run team</button>
          </div>
        </div>
      </div>

      {runId && <Timeline items={items} runId={runId} autoScroll />}

      {editing && (
        <TeamEditor
          team={team}
          onClose={() => setEditing(false)}
          onSaved={() => { setEditing(false); load(); }}
        />
      )}
    </>
  );
}
