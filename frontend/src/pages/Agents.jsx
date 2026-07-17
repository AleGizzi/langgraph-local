import React, { useEffect, useState } from "react";
import { api } from "../lib/api.js";
import Tabs, { useTab } from "../components/Tabs.jsx";
import Teams from "./Teams.jsx";
import Personas from "./Personas.jsx";

function timeAgo(ts) {
  if (!ts) return "";
  const s = Math.floor(Date.now() / 1000 - ts);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

const RUN_STATUS = {
  done: ["✅", "var(--green)"], running: ["⏳", "var(--amber)"],
  error: ["⚠️", "var(--red)"], cancelled: ["⏹", "var(--text-3)"],
};

function Dashboard() {
  const [d, setD] = useState(null);
  useEffect(() => { api("/dashboard").then(setD).catch(() => {}); }, []);
  if (!d) return <div className="help" style={{ padding: 24 }}>Loading dashboard…</div>;

  const maxUse = Math.max(1, ...d.persona_usage.map((p) => p.chats + p.team_uses));
  const anyUsage = d.persona_usage.some((p) => p.chats + p.team_uses > 0);

  return (
    <div className="dash">
      <div className="dash-tiles">
        {[["Teams", d.totals.teams, "🎛️", "teams"],
          ["Personas", d.totals.personas, "🎭", "personas"],
          ["Runs", d.totals.runs, "🗂️", null],
          ["Chats", d.totals.chats, "💬", null]].map(([label, n, ico, go]) => (
          <div key={label} className={"dash-tile" + (go ? " clickable" : "")}
            onClick={go ? () => (location.hash = `#/agents/${go}`) : undefined}>
            <div className="dash-tile-ico">{ico}</div>
            <div className="dash-tile-n">{n}</div>
            <div className="dash-tile-l">{label}</div>
          </div>
        ))}
      </div>

      <div className="dash-cols">
        <div className="card dash-card">
          <h3>🏆 Persona usage</h3>
          <div className="sub">Which personas you actually put to work (chats loaded as them + team runs that include them).</div>
          {anyUsage ? d.persona_usage.filter((p) => p.chats + p.team_uses > 0).map((p) => {
            const total = p.chats + p.team_uses;
            return (
              <div key={p.id} className="dash-bar-row"
                onClick={() => (location.hash = `#/chat/${p.id}`)} title="Chat as this persona">
                <span className="dash-bar-label">{p.icon} {p.name}</span>
                <div className="dash-bar"><div className="dash-bar-fill"
                  style={{ width: `${(total / maxUse) * 100}%` }} /></div>
                <span className="dash-bar-n">{total}
                  <span className="dash-bar-detail"> ({p.chats}💬 {p.team_uses}🎛️)</span></span>
              </div>
            );
          }) : (
            <div className="help" style={{ padding: 12 }}>
              No persona usage yet. Load a persona in Chat or run a team, and it shows up here.
            </div>
          )}
        </div>

        <div className="card dash-card">
          <h3>🗂️ Recent team runs</h3>
          {d.recent_runs.length ? d.recent_runs.map((r) => {
            const [ico, col] = RUN_STATUS[r.status] || ["•", "var(--text-3)"];
            return (
              <div key={r.id} className="dash-row" onClick={() => (location.hash = `#/run/${r.id}`)}>
                <span style={{ color: col }}>{ico}</span>
                <div className="dash-row-main">
                  <div className="dash-row-title">{r.team_name}</div>
                  <div className="dash-row-sub">{r.task || "—"}</div>
                </div>
                <span className="dash-row-time">{timeAgo(r.created_at)}</span>
              </div>
            );
          }) : <div className="help" style={{ padding: 12 }}>No runs yet.</div>}
        </div>

        <div className="card dash-card">
          <h3>💬 Recent chats</h3>
          {d.recent_chats.length ? d.recent_chats.map((c) => (
            <div key={c.id} className="dash-row" onClick={() => (location.hash = "#/chat")}>
              <span>💬</span>
              <div className="dash-row-main">
                <div className="dash-row-title">{c.title}</div>
                <div className="dash-row-sub">
                  {c.agent && c.agent !== "Chat" ? `${c.agent} · ` : ""}{c.model} · {c.messages} msg
                </div>
              </div>
              <span className="dash-row-time">{timeAgo(c.updated_at)}</span>
            </div>
          )) : <div className="help" style={{ padding: 12 }}>No chats yet.</div>}
        </div>

        <div className="card dash-card">
          <h3>🎛️ Most-run teams</h3>
          {d.team_usage.some((t) => t.runs > 0) ? d.team_usage.filter((t) => t.runs > 0).map((t) => (
            <div key={t.id} className="dash-row" onClick={() => (location.hash = `#/team/${t.id}`)}>
              <span>{t.icon}</span>
              <div className="dash-row-main"><div className="dash-row-title">{t.name}</div></div>
              <span className="dash-bar-n">{t.runs} run{t.runs !== 1 ? "s" : ""}</span>
            </div>
          )) : <div className="help" style={{ padding: 12 }}>No team runs yet.</div>}
        </div>
      </div>
    </div>
  );
}

export default function Agents({ subtab }) {
  const [tab, setTab] = useTab("agents", "dashboard");
  // A deep link (#/agents/teams, #/teams, a persona link) overrides the
  // remembered tab exactly once, on mount / when it changes.
  useEffect(() => {
    if (subtab && ["dashboard", "teams", "personas"].includes(subtab)) setTab(subtab);
  }, [subtab]); // eslint-disable-line

  return (
    <>
      <div className="page-head" style={{ marginBottom: 12 }}>
        <div>
          <h1 className="page-title">Agents</h1>
          <p className="page-sub">Your teams, your personas, and how they're being used</p>
        </div>
      </div>
      <Tabs active={tab} onChange={setTab} tabs={[
        { key: "dashboard", label: "📊 Dashboard" },
        { key: "teams", label: "🎛️ Teams" },
        { key: "personas", label: "🎭 Personas" },
      ]} />
      {tab === "dashboard" && <Dashboard />}
      {tab === "teams" && <Teams embedded />}
      {tab === "personas" && <Personas embedded />}
    </>
  );
}
