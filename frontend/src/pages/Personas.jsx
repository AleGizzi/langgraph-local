import React, { useEffect, useState } from "react";
import { api, toast } from "../lib/api.js";
import AgentFields from "../components/AgentFields.jsx";

function PersonaEditor({ persona, onClose, onSaved }) {
  const isNew = !persona?.id;
  const [data, setData] = useState(persona || {
    name: "", icon: "🧑", role: "", description: "", system_prompt: "",
    provider: "ollama", model: "", params: {}, tools: [],
  });

  const save = async () => {
    try {
      const saved = isNew
        ? await api("/personas", { method: "POST", body: data })
        : await api(`/personas/${data.id}`, { method: "PUT", body: data });
      toast(isNew ? "Persona created" : "Persona saved");
      onSaved(saved);
    } catch (e) { toast(e.message, true); }
  };

  return (
    <div className="modal-back" onClick={(e) => e.target.classList.contains("modal-back") && onClose()}>
      <div className="modal">
        <div className="modal-head">
          <h2>{isNew ? "New persona" : `Edit ${data.name}`}</h2>
          <button className="btn ghost" onClick={onClose}>✕</button>
        </div>
        <div className="modal-body">
          <div className="row">
            <div className="field narrow">
              <label>Icon</label>
              <input type="text" maxLength={4} value={data.icon}
                onChange={(e) => setData({ ...data, icon: e.target.value })} />
            </div>
            <div className="field">
              <label>Short description</label>
              <input type="text" value={data.description}
                placeholder="What is this persona good at?"
                onChange={(e) => setData({ ...data, description: e.target.value })} />
            </div>
          </div>
          <AgentFields value={data} onChange={setData} namePlaceholder="e.g. Researcher" />
        </div>
        <div className="modal-foot">
          <button className="btn" onClick={onClose}>Cancel</button>
          <button className="btn primary" onClick={save}>{isNew ? "Create persona" : "Save changes"}</button>
        </div>
      </div>
    </div>
  );
}

export default function Personas() {
  const [personas, setPersonas] = useState(null);
  const [editing, setEditing] = useState(undefined);

  const load = () => api("/personas").then(setPersonas).catch(() => setPersonas([]));
  useEffect(() => { load(); }, []);

  const del = async (p, e) => {
    e.stopPropagation();
    if (!confirm(`Delete persona "${p.name}"?`)) return;
    await api(`/personas/${p.id}`, { method: "DELETE" });
    toast("Persona deleted");
    load();
  };

  if (!personas) return null;
  return (
    <>
      <div className="page-head">
        <div>
          <h1 className="page-title">Personas</h1>
          <p className="page-sub">
            Reusable agent definitions — prompt, model and tuning — you can drop into any team
          </p>
        </div>
        <button className="btn primary" onClick={() => setEditing(null)}>＋ New Persona</button>
      </div>
      <div className="grid">
        {personas.map((p) => (
          <div key={p.id} className="card team-card persona-card" onClick={() => setEditing(p)}>
            <div className="top">
              <div className="team-icon">{p.icon}</div>
              <div>
                <h3>{p.name} {p.builtin && <span className="chip" style={{ marginLeft: 4 }}>builtin</span>}</h3>
                <div className="role">{p.role}</div>
              </div>
            </div>
            <div className="desc">{p.description}</div>
            <div className="prompt-preview">{p.system_prompt}</div>
            <div className="foot">
              {p.model && <span className="chip">{p.model}</span>}
              {Object.keys(p.params || {}).length > 0 &&
                <span className="chip topo">{Object.keys(p.params).length} params</span>}
              {(p.tools || []).length > 0 && <span className="chip loop">{p.tools.length} tools</span>}
            </div>
            <div className="card-actions">
              <button className="icon-btn" title="Edit" onClick={(e) => { e.stopPropagation(); setEditing(p); }}>✏️</button>
              <button className="icon-btn" title="Delete" onClick={(e) => del(p, e)}>🗑️</button>
            </div>
          </div>
        ))}
        <div className="new-card" onClick={() => setEditing(null)}>
          <div className="plus">＋</div>Create a persona
        </div>
      </div>
      {editing !== undefined && (
        <PersonaEditor
          persona={editing}
          onClose={() => setEditing(undefined)}
          onSaved={() => { setEditing(undefined); load(); }}
        />
      )}
    </>
  );
}
