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

function RunLog({ runId, onClose }) {
  const [data, setData] = useState(null);
  useEffect(() => { api(`/schedules/runs/${runId}`).then(setData).catch(() => {}); }, [runId]);
  return (
    <div className="modal-back" onClick={(e) => e.target.classList.contains("modal-back") && onClose()}>
      <div className="modal" style={{ maxWidth: 760 }}>
        <div className="modal-head">
          <h2>Run log {data?.ok === false && <span className="chip" style={{ color: "var(--red)" }}>failed</span>}</h2>
          <button className="btn ghost" onClick={onClose}>✕</button>
        </div>
        <div className="modal-body">
          {!data ? <div className="help">Loading…</div> : (
            <>
              <div className="field"><label>Result</label>
                <div className="sched-log-result">{data.result || "(no result)"}</div></div>
              <div className="sched-log-links">
                {data.note_path && (
                  <a className="btn sm primary" href={`#/knowledge/${encodeURIComponent(data.note_path)}`}
                    onClick={onClose}>📄 Read the saved note →</a>
                )}
                {data.run_id && (
                  <a className="btn sm" href={`#/run/${data.run_id}`} onClick={onClose}>
                    🗂️ Open full team run #{data.run_id} →</a>
                )}
              </div>
              <div className="field"><label>Execution log (for debugging)</label>
                <textarea rows={10} readOnly value={data.log || "(no log captured)"}
                  style={{ fontFamily: "var(--mono)", fontSize: 12 }} /></div>
            </>
          )}
        </div>
        <div className="modal-foot"><button className="btn" onClick={onClose}>Close</button></div>
      </div>
    </div>
  );
}

function ScheduleEditor({ schedule, onClose, onSaved }) {
  const editing = !!schedule?.id;
  const [name, setName] = useState(schedule?.name || "");
  const [prompt, setPrompt] = useState(schedule?.prompt || "");
  const [interval, setInterval] = useState(schedule?.interval_seconds || 86400);
  const [track, setTrack] = useState(schedule?.track_number || false);
  const [notify, setNotify] = useState(schedule?.notify || false);
  const [allowDestructive, setAllowDestructive] = useState(schedule?.allow_destructive || false);
  const [folder, setFolder] = useState(schedule?.knowledge_folder || "");
  const [mode, setMode] = useState(schedule?.team_id ? "team" : "agent");
  const [teamId, setTeamId] = useState(schedule?.team_id || "");
  const [personas, setPersonas] = useState([]);
  const [teams, setTeams] = useState([]);
  const [agent, setAgent] = useState(schedule?.agent?.model ? schedule.agent : {
    name: "Scheduled agent", provider: "ollama", model: "",
    system_prompt: "You are a precise research assistant.", params: {},
    tools: ["web_search", "read_webpage"], skills: [],
  });
  useEffect(() => {
    api("/personas").then(setPersonas).catch(() => {});
    api("/teams").then(setTeams).catch(() => {});
  }, []);

  const applyPersona = (p) => setAgent({
    name: p.name, provider: p.model ? p.provider : agent.provider,
    model: p.model || agent.model, system_prompt: p.system_prompt,
    params: { ...(p.params || {}) }, tools: [...(p.tools || [])], skills: [...(p.skills || [])],
  });

  const [drafting, setDrafting] = useState(false);
  const draftWithAI = async () => {
    const desc = prompt.trim() || name.trim();
    if (!desc) { toast("Describe what you want the task to do first", true); return; }
    setDrafting(true);
    try {
      const d = await api("/schedules/draft", { method: "POST", body: { request: desc } });
      setName(d.name); setPrompt(d.prompt); setInterval(d.interval_seconds);
      setTrack(d.track_number); setNotify(d.notify);
      setFolder(d.knowledge_folder || "");
      setMode("agent");
      setAgent((a) => ({ ...a, tools: d.tools?.length ? d.tools : a.tools }));
      toast("Drafted — review the fields, pick a model, and create");
    } catch (e) { toast(e.message, true); }
    setDrafting(false);
  };

  const save = async () => {
    if (!prompt.trim()) { toast("Describe the task (prompt)", true); return; }
    if (mode === "agent" && !agent.model) { toast("Pick a model", true); return; }
    if (mode === "team" && !teamId) { toast("Pick a team", true); return; }
    const body = {
      name: name || prompt.slice(0, 40), prompt,
      interval_seconds: interval, track_number: track, notify,
      allow_destructive: allowDestructive,
      knowledge_folder: folder.trim() || null,
      team_id: mode === "team" ? +teamId : null,
      agent: mode === "agent" ? agent : {},
    };
    try {
      if (editing) await api(`/schedules/${schedule.id}`, { method: "PUT", body });
      else await api("/schedules", { method: "POST", body });
      toast(editing ? "Schedule updated" : "Schedule created — it will run on its interval");
      onSaved();
    } catch (e) { toast(e.message, true); }
  };

  return (
    <div className="modal-back" onClick={(e) => e.target.classList.contains("modal-back") && onClose()}>
      <div className="modal" style={{ maxWidth: 720 }}>
        <div className="modal-head"><h2>{editing ? "Edit schedule" : "New scheduled task"}</h2>
          <button className="btn ghost" onClick={onClose}>✕</button></div>
        <div className="modal-body">
          <div className="seg" style={{ marginBottom: 12 }}>
            <button className={mode === "agent" ? "active" : ""} onClick={() => setMode("agent")}>👤 Single agent</button>
            <button className={mode === "team" ? "active" : ""} onClick={() => setMode("team")}>🎛️ Team</button>
          </div>
          <div className="field"><label>Name</label>
            <input type="text" value={name} placeholder="e.g. USD/ARS daily check"
              onChange={(e) => setName(e.target.value)} /></div>
          <div className="field">
            <label style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <span>Task prompt — what to do each time</span>
              <button className="btn sm" onClick={draftWithAI} disabled={drafting}
                title="Describe your task in the prompt, then let a model fill in the schedule">
                {drafting ? "Drafting…" : "🪄 Draft with AI"}
              </button>
            </label>
            <textarea rows={3} value={prompt}
              placeholder="e.g. Search the web for the current USD to ARS blue dollar exchange rate and report today's value as a single number. (Or type a rough idea and click 'Draft with AI'.)"
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
          <label style={{ display: "flex", gap: 8, alignItems: "center", cursor: "pointer", margin: "4px 0 6px" }}>
            <input type="checkbox" checked={track} onChange={(e) => setTrack(e.target.checked)} />
            📈 Track a number — extract the first number from each result and chart its evolution
          </label>
          <label style={{ display: "flex", gap: 8, alignItems: "center", cursor: "pointer", margin: "0 0 6px" }}>
            <input type="checkbox" checked={notify} onChange={(e) => setNotify(e.target.checked)} />
            🔔 Notify me when it finishes — a desktop popup + the in-app bell
          </label>
          <label style={{ display: "flex", gap: 8, alignItems: "flex-start", cursor: "pointer", margin: "0 0 10px" }}>
            <input type="checkbox" checked={allowDestructive} style={{ marginTop: 3 }}
              onChange={(e) => setAllowDestructive(e.target.checked)} />
            <span>🛑 Allow destructive actions — let this unattended run execute code
              (<code>run_python</code>) and edit real project files. Off by default: the
              blast-radius gate blocks those while no one is watching.</span>
          </label>

          {mode === "team" ? (
            <>
              <div className="field"><label>Team to run</label>
                <select value={teamId} onChange={(e) => setTeamId(e.target.value)}>
                  <option value="">— pick a team —</option>
                  {teams.map((t) => <option key={t.id} value={t.id}>{t.icon} {t.name}</option>)}
                </select></div>
              <div className="help">
                The team runs like a normal run — its full timeline is browsable on
                the Runs page, and linked from this schedule's history for debugging.
                Team runs take longer, so pick a wider interval.
              </div>
            </>
          ) : (
            <>
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
                the internet. Runs happen only while the app is on — keep it running (or
                use the systemd service / desktop app) for 24/7.
              </div>
            </>
          )}
        </div>
        <div className="modal-foot">
          <button className="btn" onClick={onClose}>Cancel</button>
          <button className="btn primary" onClick={save}>{editing ? "Save changes" : "Create schedule"}</button>
        </div>
      </div>
    </div>
  );
}

export default function Schedules() {
  const [schedules, setSchedules] = useState(null);
  const [editing, setEditing] = useState(undefined); // undefined=closed, null=new, obj=edit
  const [expanded, setExpanded] = useState({});
  const [logRun, setLogRun] = useState(null);
  const [teams, setTeams] = useState([]);
  useEffect(() => { api("/teams").then(setTeams).catch(() => {}); }, []);

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
        <button className="btn primary" onClick={() => setEditing(null)}>＋ New schedule</button>
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
                <div className="sched-name">
                  {s.name}
                  <span className="chip" style={{ marginLeft: 6 }}>
                    {s.team_id ? `🎛️ ${teams.find((t) => t.id === s.team_id)?.name || "team"}` : "👤 agent"}
                  </span>
                </div>
                <div className="sched-sub">
                  {INTERVALS.find(([, v]) => v === s.interval_seconds)?.[0]
                    || `every ${Math.round(s.interval_seconds / 3600)}h`}
                  {" · next "}{s.enabled ? fmtWhen(s.next_run) : "paused"}
                  {s.knowledge_folder && <> · 📁 {s.knowledge_folder}</>}
                  {" · "}{s.runs.length} run{s.runs.length !== 1 ? "s" : ""}
                </div>
              </div>
              <button className="btn sm" onClick={() => runNow(s)}>▶ Run now</button>
              <button className="icon-btn" title="Edit" onClick={() => setEditing(s)}>✏️</button>
              <button className="icon-btn" title="Delete" onClick={() => del(s)}>🗑️</button>
            </div>
            <div className="sched-prompt">{s.prompt}</div>
            {s.track_number && <Sparkline runs={s.runs} />}
            {s.last_result && (() => {
              const latest = s.runs.length ? s.runs[s.runs.length - 1] : null;
              const note = latest?.note_path;
              return (
                <div className="sched-last">
                  <div className="sched-last-body">
                    {s.last_result.slice(0, 600)}{s.last_result.length > 600 && "…"}
                  </div>
                  <div className="sched-last-meta">
                    <span className="sched-when">🕓 {fmtWhen(s.last_run)}</span>
                    {note && (
                      <a className="sched-note-link" href={`#/knowledge/${encodeURIComponent(note)}`}>
                        📄 Read the saved note →
                      </a>
                    )}
                  </div>
                </div>
              );
            })()}
            {s.runs.length > 0 && (
              <button className="btn sm ghost" style={{ padding: "3px 8px", marginTop: 6 }}
                onClick={() => setExpanded((e) => ({ ...e, [s.id]: !e[s.id] }))}>
                {expanded[s.id] ? "▾" : "▸"} run history &amp; logs ({s.runs.length})
              </button>
            )}
            {expanded[s.id] && (
              <div className="sched-history">
                {[...s.runs].reverse().map((r) => (
                  <div key={r.id} className="sched-run">
                    <div className="sched-run-body">
                      {(r.result || "").slice(0, 280)}{(r.result || "").length > 280 && "…"}
                    </div>
                    <div className="sched-run-meta">
                      <span>{r.ok ? "✅" : "⚠️"}</span>
                      <span className="sched-run-time">{fmtWhen(r.ran_at)}</span>
                      {r.value != null && <span className="chip">{r.value}</span>}
                      {r.note_path && (
                        <a className="sched-run-note" title="Read the saved note"
                          href={`#/knowledge/${encodeURIComponent(r.note_path)}`}>📄 note</a>
                      )}
                      <button className="btn sm ghost" style={{ padding: "1px 7px", marginLeft: "auto", flexShrink: 0 }}
                        onClick={() => setLogRun(r.id)}>📋 log</button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        );
      })}

      {editing !== undefined && <ScheduleEditor schedule={editing}
        onClose={() => setEditing(undefined)}
        onSaved={() => { setEditing(undefined); load(); }} />}
      {logRun && <RunLog runId={logRun} onClose={() => setLogRun(null)} />}
    </>
  );
}
