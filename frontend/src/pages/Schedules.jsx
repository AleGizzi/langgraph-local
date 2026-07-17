import React, { useEffect, useState } from "react";
import { api, toast } from "../lib/api.js";
import AgentFields from "../components/AgentFields.jsx";

const INTERVALS = [
  ["Every 15 min", 900], ["Hourly", 3600], ["Every 6 h", 21600],
  ["Every 12 h", 43200], ["Daily", 86400], ["Weekly", 604800],
];

function fmtWhen(ts) {
  if (!ts) return "—";
  const d = new Date(ts * 1000);
  const now = Date.now() / 1000;
  const diff = ts - now;
  const rel = Math.abs(diff) < 3600 ? `${Math.round(Math.abs(diff) / 60)}m`
    : Math.abs(diff) < 86400 ? `${Math.round(Math.abs(diff) / 3600)}h`
    : `${Math.round(Math.abs(diff) / 86400)}d`;
  return `${d.toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })} (${diff > 0 ? "in " : ""}${rel}${diff > 0 ? "" : " ago"})`;
}

/* Tiny inline SVG line chart of tracked values over time. */
function Sparkline({ runs }) {
  const pts = runs.filter((r) => r.value != null);
  if (pts.length < 2) return null;
  const W = 320, H = 60, pad = 4;
  const vals = pts.map((p) => p.value);
  const min = Math.min(...vals), max = Math.max(...vals);
  const span = max - min || 1;
  const xy = pts.map((p, i) => [
    pad + (i / (pts.length - 1)) * (W - 2 * pad),
    H - pad - ((p.value - min) / span) * (H - 2 * pad),
  ]);
  const d = xy.map(([x, y], i) => `${i ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
  const last = pts[pts.length - 1].value;
  const first = pts[0].value;
  const up = last >= first;
  return (
    <div className="sched-chart">
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" height={H} preserveAspectRatio="none">
        <path d={d} fill="none" stroke={up ? "var(--green)" : "var(--red)"} strokeWidth="1.6" />
        {xy.map(([x, y], i) => <circle key={i} cx={x} cy={y} r="1.8" fill={up ? "var(--green)" : "var(--red)"} />)}
      </svg>
      <div className="sched-chart-legend">
        {pts.length} points · min {min} · max {max} · latest <b>{last}</b>
        <span style={{ color: up ? "var(--green)" : "var(--red)" }}> {up ? "▲" : "▼"} {(last - first).toFixed(2)}</span>
      </div>
    </div>
  );
}

function ScheduleEditor({ onClose, onSaved }) {
  const [name, setName] = useState("");
  const [prompt, setPrompt] = useState("");
  const [interval, setInterval] = useState(86400);
  const [track, setTrack] = useState(false);
  const [folder, setFolder] = useState("");
  const [personas, setPersonas] = useState([]);
  const [agent, setAgent] = useState({
    name: "Scheduled agent", provider: "ollama", model: "",
    system_prompt: "You are a precise research assistant.", params: {},
    tools: ["web_search", "read_webpage"], skills: [],
  });
  useEffect(() => { api("/personas").then(setPersonas).catch(() => {}); }, []);

  const applyPersona = (p) => setAgent({
    name: p.name, provider: p.model ? p.provider : agent.provider,
    model: p.model || agent.model, system_prompt: p.system_prompt,
    params: { ...(p.params || {}) }, tools: [...(p.tools || [])], skills: [...(p.skills || [])],
  });

  const save = async () => {
    if (!prompt.trim()) { toast("Describe the task (prompt)", true); return; }
    if (!agent.model) { toast("Pick a model", true); return; }
    try {
      await api("/schedules", { method: "POST", body: {
        name: name || prompt.slice(0, 40), prompt, agent,
        interval_seconds: interval, track_number: track,
        knowledge_folder: folder.trim() || null,
      }});
      toast("Schedule created — it will run on its interval");
      onSaved();
    } catch (e) { toast(e.message, true); }
  };

  return (
    <div className="modal-back" onClick={(e) => e.target.classList.contains("modal-back") && onClose()}>
      <div className="modal" style={{ maxWidth: 720 }}>
        <div className="modal-head"><h2>New scheduled task</h2>
          <button className="btn ghost" onClick={onClose}>✕</button></div>
        <div className="modal-body">
          <div className="field"><label>Name</label>
            <input type="text" value={name} placeholder="e.g. USD/ARS daily check"
              onChange={(e) => setName(e.target.value)} /></div>
          <div className="field"><label>Task prompt — what the agent should do each time</label>
            <textarea rows={3} value={prompt}
              placeholder="e.g. Search the web for the current USD to ARS blue dollar exchange rate and report today's value as a single number."
              onChange={(e) => setPrompt(e.target.value)} /></div>
          <div className="row">
            <div className="field"><label>Runs</label>
              <select value={interval} onChange={(e) => setInterval(+e.target.value)}>
                {INTERVALS.map(([l, v]) => <option key={v} value={v}>{l}</option>)}
              </select></div>
            <div className="field"><label>Save results to knowledge folder (optional)</label>
              <input type="text" value={folder} placeholder="e.g. usd-ars-tracking"
                onChange={(e) => setFolder(e.target.value)} /></div>
          </div>
          <label style={{ display: "inline-flex", gap: 8, alignItems: "center", cursor: "pointer", margin: "4px 0 10px" }}>
            <input type="checkbox" checked={track} onChange={(e) => setTrack(e.target.checked)} />
            📈 Track a number — extract the first number from each result and chart its evolution
          </label>
          <div className="field">
            <label>Quick-load a persona</label>
            <div className="persona-strip">
              {personas.map((p) => (
                <span key={p.id} className="persona-chip" title={p.description}
                  onClick={() => applyPersona(p)}>{p.icon} {p.name}</span>
              ))}
            </div>
          </div>
          <AgentFields value={agent} onChange={setAgent} namePlaceholder="Agent name" />
          <div className="help" style={{ marginTop: 8 }}>
            Give the agent web tools (web_search, read_webpage) for tasks that need
            the internet. Scheduled runs happen only while the app is running —
            keep it on (or install the systemd service / desktop app) for 24/7.
          </div>
        </div>
        <div className="modal-foot">
          <button className="btn" onClick={onClose}>Cancel</button>
          <button className="btn primary" onClick={save}>Create schedule</button>
        </div>
      </div>
    </div>
  );
}

export default function Schedules() {
  const [schedules, setSchedules] = useState(null);
  const [editing, setEditing] = useState(false);
  const [expanded, setExpanded] = useState({});

  const load = () => api("/schedules").then((d) => setSchedules(d.schedules)).catch(() => setSchedules([]));
  useEffect(() => { load(); const t = window.setInterval(load, 15000); return () => window.clearInterval(t); }, []);

  const toggle = async (s) => {
    await api(`/schedules/${s.id}`, { method: "PUT", body: { enabled: !s.enabled } });
    load();
  };
  const runNow = async (s) => {
    await api(`/schedules/${s.id}/run`, { method: "POST" });
    toast(`Running "${s.name}" now…`);
    setTimeout(load, 2000);
  };
  const del = async (s) => {
    if (!confirm(`Delete schedule "${s.name}" and its history?`)) return;
    await api(`/schedules/${s.id}`, { method: "DELETE" });
    load();
  };

  return (
    <>
      <div className="page-head">
        <div>
          <h1 className="page-title">Schedules</h1>
          <p className="page-sub">
            Run an agent unattended on an interval — daily web checks, tracked
            metrics, recurring research. Runs while the app is on.
          </p>
        </div>
        <button className="btn primary" onClick={() => setEditing(true)}>＋ New schedule</button>
      </div>

      {schedules && !schedules.length && (
        <div className="empty" style={{ padding: 40 }}>
          <div className="big">⏰</div>
          No scheduled tasks yet. Create one — e.g. "check the USD/ARS rate daily and track it".
        </div>
      )}

      {(schedules || []).map((s) => {
        const okRuns = s.runs.filter((r) => r.ok);
        return (
          <div key={s.id} className="card sched-card">
            <div className="sched-head">
              <button className={"sched-switch" + (s.enabled ? " on" : "")}
                title={s.enabled ? "Enabled — click to pause" : "Paused — click to enable"}
                onClick={() => toggle(s)}>
                <span className="sched-switch-knob" /></button>
              <div className="sched-main">
                <div className="sched-name">{s.name}</div>
                <div className="sched-sub">
                  {INTERVALS.find(([, v]) => v === s.interval_seconds)?.[0]
                    || `every ${Math.round(s.interval_seconds / 3600)}h`}
                  {" · next "}{s.enabled ? fmtWhen(s.next_run) : "paused"}
                  {s.knowledge_folder && <> · 📁 {s.knowledge_folder}</>}
                  {" · "}{s.runs.length} run{s.runs.length !== 1 ? "s" : ""}
                </div>
              </div>
              <button className="btn sm" onClick={() => runNow(s)}>▶ Run now</button>
              <button className="icon-btn" title="Delete" onClick={() => del(s)}>🗑️</button>
            </div>
            <div className="sched-prompt">{s.prompt}</div>
            {s.track_number && <Sparkline runs={s.runs} />}
            {s.last_result && (
              <div className="sched-last">
                <b>Latest result</b> ({fmtWhen(s.last_run)}): {s.last_result.slice(0, 400)}
                {s.last_result.length > 400 && "…"}
              </div>
            )}
            {s.runs.length > 1 && (
              <button className="btn sm ghost" style={{ padding: "3px 8px", marginTop: 6 }}
                onClick={() => setExpanded((e) => ({ ...e, [s.id]: !e[s.id] }))}>
                {expanded[s.id] ? "▾" : "▸"} history ({s.runs.length})
              </button>
            )}
            {expanded[s.id] && (
              <div className="sched-history">
                {[...s.runs].reverse().map((r) => (
                  <div key={r.id} className="sched-run">
                    <span>{r.ok ? "✅" : "⚠️"}</span>
                    <span className="sched-run-time">{fmtWhen(r.ran_at)}</span>
                    {r.value != null && <span className="chip">{r.value}</span>}
                    <span className="sched-run-result">{(r.result || "").slice(0, 120)}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        );
      })}

      {editing && <ScheduleEditor onClose={() => setEditing(false)}
        onSaved={() => { setEditing(false); load(); }} />}
    </>
  );
}
