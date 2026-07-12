import React, { useEffect, useState } from "react";
import { api, toast } from "../lib/api.js";
import { useApp } from "../App.jsx";
import AgentFields from "../components/AgentFields.jsx";
import WizardPanel from "../components/WizardPanel.jsx";

/* ---------- deterministic card stats (mirrors sprites.py heuristics) ---------- */

function paramsB(model) {
  const m = /(\d+(?:\.\d+)?)b\b/i.exec(model || "");
  if (m) return parseFloat(m[1]);
  if (/(\d+)m\b/i.test(model || "")) return 0.5;
  if (/tinyllama|smollm/i.test(model || "")) return 1;
  return 7;
}
const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, Math.round(v)));

function cardStats(p) {
  const b = paramsB(p.model);
  const temp = p.params?.temperature ?? 0.7;
  const reasoning = /r1|qwq|think/i.test(p.model || "");
  const delegated = /r1|qwq|think|gemma/i.test(p.model || "");
  return [
    ["🧠", "Thinking depth", reasoning ? 9 : clamp(3 + b / 3, 2, 9), "green"],
    ["⚡", "Response speed", clamp(10 - b / 2, 2, 10), "amber"],
    ["🎯", "Accuracy", clamp(4 + b / 2.5, 3, 10), "accent"],
    ["✨", "Creativity", clamp(temp * 10, 1, 10), "violet"],
    ["🛡️", "Reliability", clamp(10 - Math.abs(temp - 0.3) * 6, 3, 10), "teal"],
    ["🔧", "Tool proficiency",
      clamp((delegated ? 4 : 8) + (p.tools?.length > 2 ? 1 : 0), 1, 10), "amber"],
  ];
}
const level = (p) => clamp(paramsB(p.model) * 4 + (p.skills?.length || 0) * 2, 5, 99);

/* ---------- Pokédex-style card ---------- */

function PersonaCard({ persona, onClose, onEdit, onChanged }) {
  const { skills } = useApp();
  const [p, setP] = useState(persona);
  const [generating, setGenerating] = useState(false);

  const genSprite = async () => {
    setGenerating(true);
    toast("Generating sprite — a few minutes on this GPU…");
    try {
      const updated = await api(`/personas/${p.id}/sprite`, {
        method: "POST", body: p._flavor ? { flavor: p._flavor } : {} });
      setP(updated);
      onChanged?.(updated);
      toast("Sprite ready!");
    } catch (e) { toast(e.message, true); }
    setGenerating(false);
  };

  const meta = p.sprite_meta || {};
  const specs = [
    ["Model ID", `${p.provider}/${p.model || "—"}`],
    ["Parameters", `${paramsB(p.model)}B`],
    ["Context window", `${(p.params?.num_ctx ?? 8192).toLocaleString()} tokens`],
    ["Temperature", p.params?.temperature ?? 0.7],
    ["Species", meta.species || "not yet discovered"],
    ["Role", p.role || "—"],
    ["Description", p.description || "—"],
  ];

  return (
    <div className="modal-back" onClick={(e) => e.target.classList.contains("modal-back") && onClose()}>
      <div className="dex-card">
        <div className="dex-head">
          <span className="dex-icon">{p.icon}</span>
          <h2>{p.name}</h2>
          <span className="dex-level">Lv. {level(p)}</span>
          <span className="spacer" />
          <span className="dex-active">{p.builtin ? "BUILTIN" : "CUSTOM"}</span>
          <button className="btn ghost" style={{ color: "#cfe3ea" }} onClick={onClose}>✕</button>
        </div>
        <div className="dex-body">
          <div className="dex-specs">
            {specs.map(([k, v]) => (
              <div key={k} className="dex-spec-row">
                <span className="k">{k}</span><span className="v">{String(v)}</span>
              </div>
            ))}
          </div>
          <div className="dex-sprite">
            {p.sprite
              ? <img src={`/api/imagegen/images/${p.sprite}`} alt={meta.species || p.name} />
              : <div className="dex-sprite-empty">{p.icon}</div>}
            {meta.species && (
              <div className="dex-species">
                {meta.species}
                <span className="dex-stage">{"◆".repeat(meta.stage || 1)}{"◇".repeat(3 - (meta.stage || 1))}</span>
              </div>
            )}
            <button className="btn sm" disabled={generating} onClick={genSprite}
              style={{ marginTop: 8 }}>
              {generating ? "🧬 Evolving… (~6 min)" : p.sprite ? "🎨 Regenerate sprite" : "✨ Generate sprite"}
            </button>
          </div>
          <div className="dex-stats">
            {cardStats(p).map(([ico, label, val, color]) => (
              <div key={label} className="dex-stat">
                <div className="dex-stat-head">
                  <span>{ico} {label.toUpperCase()}</span><b>{val}/10</b>
                </div>
                <div className="dex-bar">
                  {Array.from({ length: 10 }, (_, i) => (
                    <span key={i} className={"seg " + (i < val ? "on " + color : "")} />
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>
        <div className="dex-lower">
          <div className="dex-panel">
            <h4>TOOLS AVAILABLE</h4>
            <div className="dex-chips">
              {(p.tools || []).length
                ? p.tools.map((t) => <span key={t} className="dex-chip">🛠 {t}</span>)
                : <span className="dex-dim">none — relies on pure reasoning</span>}
            </div>
          </div>
          <div className="dex-panel">
            <h4>SPECIAL ABILITIES</h4>
            {(p.skills || []).length ? p.skills.map((s) => {
              const sk = skills.find((x) => x.name === s);
              return (
                <div key={s} className="dex-ability">
                  <b>{sk?.icon || "✨"} {s}</b>
                  {sk?.description && <span>{sk.description}</span>}
                </div>
              );
            }) : <span className="dex-dim">none yet</span>}
          </div>
          <div className="dex-panel">
            <h4>AGENT STATUS</h4>
            <div className="dex-spec-row"><span className="k">Family</span><span className="v">{meta.family || "?"}</span></div>
            <div className="dex-spec-row"><span className="k">Evolution</span><span className="v">stage {meta.stage || "?"} / 3</span></div>
            <div className="dex-spec-row"><span className="k">Origin</span><span className="v">{p.builtin ? "seeded" : "user-made"}</span></div>
            <div className="dex-spec-row"><span className="k">Hyperparams</span><span className="v">{Object.keys(p.params || {}).length} set</span></div>
          </div>
        </div>
        <div className="dex-foot">
          <span className="dex-personality">
            💬 <b>PERSONALITY</b> {(p.system_prompt || "").split(".")[0].slice(0, 140) || "A mysterious agent."}
          </span>
          <button className="btn sm" onClick={() => onEdit(p)}>✏️ Edit settings</button>
        </div>
      </div>
    </div>
  );
}

/* ---------- editor (unchanged fields + optional wizard) ---------- */

function PersonaEditor({ persona, wizard, onClose, onSaved }) {
  const isNew = !persona?.id;
  const [data, setData] = useState(persona || {
    name: "", icon: "🧑", role: "", description: "", system_prompt: "",
    provider: "ollama", model: "", params: {}, tools: [], skills: [],
  });
  const [flavor, setFlavor] = useState("");

  const save = async () => {
    try {
      const saved = isNew
        ? await api("/personas", { method: "POST", body: data })
        : await api(`/personas/${data.id}`, { method: "PUT", body: data });
      toast(isNew ? "Persona created" : "Persona saved");
      onSaved(saved, flavor);
    } catch (e) { toast(e.message, true); }
  };

  return (
    <div className="modal-back" onClick={(e) => e.target.classList.contains("modal-back") && onClose()}>
      <div className="modal">
        <div className="modal-head">
          <h2>{isNew ? (wizard ? "New persona — AI wizard" : "New persona") : `Edit ${data.name}`}</h2>
          <button className="btn ghost" onClick={onClose}>✕</button>
        </div>
        <div className="modal-body">
          {wizard && (
            <WizardPanel kind="persona"
              buildPayload={() => ({ current: data })}
              onDraft={(d) => {
                const { flavor: fl, ...rest } = d;
                setData((prev) => ({ ...prev, ...rest }));
                if (fl) setFlavor(fl);
              }} />
          )}
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
          {wizard && flavor && (
            <div className="help">Sprite flavor from the wizard: “{flavor}” — used when you generate its sprite.</div>
          )}
        </div>
        <div className="modal-foot">
          <button className="btn" onClick={onClose}>Cancel</button>
          <button className="btn primary" onClick={save}>{isNew ? "Create persona" : "Save changes"}</button>
        </div>
      </div>
    </div>
  );
}

/* ---------- page ---------- */

export default function Personas() {
  const [personas, setPersonas] = useState(null);
  const [editing, setEditing] = useState(undefined);
  const [wizMode, setWizMode] = useState(false);
  const [viewing, setViewing] = useState(null);

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
            Your roster of reusable agents — click one to open its card, generate
            its creature sprite, or edit its settings
          </p>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <button className="btn" onClick={() => { setWizMode(true); setEditing(null); }}>🪄 Describe an agent</button>
          <button className="btn primary" onClick={() => { setWizMode(false); setEditing(null); }}>＋ New Persona</button>
        </div>
      </div>
      <div className="grid">
        {personas.map((p) => (
          <div key={p.id} className="card team-card persona-card" onClick={() => setViewing(p)}>
            <div className="top">
              {p.sprite
                ? <img className="persona-thumb" src={`/api/imagegen/images/${p.sprite}`} alt="" />
                : <div className="team-icon">{p.icon}</div>}
              <div>
                <h3>{p.name} <span className="chip" style={{ marginLeft: 4 }}>Lv. {level(p)}</span></h3>
                <div className="role">{p.sprite_meta?.species || p.role}</div>
              </div>
            </div>
            <div className="desc">{p.description}</div>
            <div className="foot">
              {p.model && <span className="chip">{p.model}</span>}
              {(p.tools || []).length > 0 && <span className="chip loop">{p.tools.length} tools</span>}
              {p.builtin && <span className="chip">builtin</span>}
            </div>
            <div className="card-actions">
              <button className="icon-btn" title="Edit" onClick={(e) => { e.stopPropagation(); setWizMode(false); setEditing(p); }}>✏️</button>
              <button className="icon-btn" title="Delete" onClick={(e) => del(p, e)}>🗑️</button>
            </div>
          </div>
        ))}
        <div className="new-card" onClick={() => { setWizMode(false); setEditing(null); }}>
          <div className="plus">＋</div>Create a persona
        </div>
        <div className="new-card" onClick={() => { setWizMode(true); setEditing(null); }}>
          <div className="plus">🪄</div>Describe it — AI builds the agent
        </div>
      </div>

      {viewing && (
        <PersonaCard persona={viewing}
          onClose={() => setViewing(null)}
          onEdit={(p) => { setViewing(null); setWizMode(false); setEditing(p); }}
          onChanged={() => load()} />
      )}
      {editing !== undefined && (
        <PersonaEditor persona={editing} wizard={wizMode}
          onClose={() => setEditing(undefined)}
          onSaved={(saved, flavor) => {
            setEditing(undefined);
            load();
            // Wizard flow: open the card so the sprite can be generated next,
            // carrying the wizard's visual flavor into the generation.
            if (wizMode && saved?.id) setViewing({ ...saved, _flavor: flavor });
          }} />
      )}
    </>
  );
}
