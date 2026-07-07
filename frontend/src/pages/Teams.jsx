import React, { useEffect, useState } from "react";
import { api, toast } from "../lib/api.js";
import TeamEditor from "../components/TeamEditor.jsx";

export default function Teams() {
  const [teams, setTeams] = useState(null);
  const [editing, setEditing] = useState(undefined); // undefined=closed, null=new, obj=edit

  const load = () => api("/teams").then(setTeams).catch((e) => toast(e.message, true));
  useEffect(() => { load(); }, []);

  const dup = async (t, e) => {
    e.stopPropagation();
    const copy = { ...t, name: t.name + " (copy)" };
    delete copy.id;
    await api("/teams", { method: "POST", body: copy });
    toast("Team duplicated");
    load();
  };
  const del = async (t, e) => {
    e.stopPropagation();
    if (!confirm(`Delete team "${t.name}"?`)) return;
    await api(`/teams/${t.id}`, { method: "DELETE" });
    toast("Team deleted");
    load();
  };

  return (
    <>
      <div className="page-head">
        <div>
          <h1 className="page-title">Studio</h1>
          <p className="page-sub">Agent teams that run on your local models</p>
        </div>
        <button className="btn primary" onClick={() => setEditing(null)}>＋ New Team</button>
      </div>
      <div className="grid">
        {(teams || []).map((t) => (
          <div key={t.id} className="card team-card" onClick={() => (location.hash = `#/team/${t.id}`)}>
            <div className="top">
              <div className="team-icon">{t.icon}</div>
              <div><h3>{t.name}</h3></div>
            </div>
            <div className="desc">{t.description || "No description"}</div>
            <div className="foot">
              <span className="chip topo">{t.topology}</span>
              <span className="chip">{t.agents.length} agent{t.agents.length > 1 ? "s" : ""}</span>
              {t.settings.quality_loop && <span className="chip loop">quality loop</span>}
              {t.settings.parallel && <span className="chip topo">parallel</span>}
            </div>
            <div className="card-actions">
              <button className="icon-btn" title="Open in canvas" onClick={(e) => { e.stopPropagation(); location.hash = `#/flow/${t.id}`; }}>🎨</button>
              <button className="icon-btn" title="Pixel studio" onClick={(e) => { e.stopPropagation(); location.hash = `#/pixel/${t.id}`; }}>👾</button>
              <button className="icon-btn" title="Edit" onClick={(e) => { e.stopPropagation(); setEditing(t); }}>✏️</button>
              <button className="icon-btn" title="Duplicate" onClick={(e) => dup(t, e)}>📋</button>
              <button className="icon-btn" title="Delete" onClick={(e) => del(t, e)}>🗑️</button>
            </div>
          </div>
        ))}
        <div className="new-card" onClick={() => setEditing(null)}>
          <div className="plus">＋</div>Create a team
        </div>
      </div>
      {editing !== undefined && (
        <TeamEditor
          team={editing}
          onClose={() => setEditing(undefined)}
          onSaved={(saved) => { setEditing(undefined); location.hash = `#/team/${saved.id}`; }}
        />
      )}
    </>
  );
}
