import React, { useState } from "react";
import { useApp } from "../App.jsx";

export function ModelSelect({ provider, model, onChange }) {
  const { models } = useApp();
  const groups = [["ollama", "Ollama"], ["lmstudio", "LM Studio"]];
  return (
    <select
      value={`${provider}::${model}`}
      onChange={(e) => {
        const [prov, ...rest] = e.target.value.split("::");
        onChange(prov, rest.join("::"));
      }}
    >
      {!model && <option value="::">Select a model…</option>}
      {model && !(models[provider] || []).includes(model) && (
        <option value={`${provider}::${model}`}>{model} (not loaded)</option>
      )}
      {groups.map(([prov, label]) =>
        (models[prov] || []).length ? (
          <optgroup key={prov} label={label}>
            {models[prov].map((m) => (
              <option key={m} value={`${prov}::${m}`}>{m}</option>
            ))}
          </optgroup>
        ) : null
      )}
    </select>
  );
}

export function ParamsEditor({ params, onChange }) {
  const { paramSpecs } = useApp();
  const [open, setOpen] = useState(false);
  const set = (key, raw) => {
    const next = { ...params };
    if (raw === "" || raw === null) delete next[key];
    else next[key] = +raw;
    onChange(next);
  };
  const activeCount = Object.keys(params || {}).length;
  return (
    <div className="field" style={{ marginTop: 8 }}>
      <div className="collapse-head" onClick={() => setOpen(!open)}>
        <span>{open ? "▾" : "▸"}</span>
        Model hyperparameters
        {activeCount > 0 && <span className="chip">{activeCount} set</span>}
      </div>
      {open && (
        <div className="params-grid" style={{ marginTop: 6 }}>
          {paramSpecs.map((p) => (
            <div key={p.key} className="param-field">
              <label>
                {p.label}
                <span className="val">{params?.[p.key] ?? (p.default ?? "auto")}</span>
              </label>
              <input
                type="number" min={p.min} max={p.max} step={p.step}
                value={params?.[p.key] ?? ""}
                placeholder={p.default != null ? String(p.default) : "auto"}
                onChange={(e) => set(p.key, e.target.value)}
              />
              <div className="param-hint">{p.hint}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export function ToolsPicker({ selected, onChange }) {
  const { tools } = useApp();
  const toggle = (key) => {
    const cur = selected || [];
    onChange(cur.includes(key) ? cur.filter((t) => t !== key) : [...cur, key]);
  };
  return (
    <div className="tools-row">
      {Object.entries(tools).map(([key, desc]) => (
        <span
          key={key}
          className={"tool-tag" + ((selected || []).includes(key) ? " on" : "")}
          title={desc}
          onClick={() => toggle(key)}
        >{key}</span>
      ))}
    </div>
  );
}

/* Shared field block for an agent-like object (team agent or persona). */
export default function AgentFields({ value, onChange, namePlaceholder = "Agent name" }) {
  const upd = (patch) => onChange({ ...value, ...patch });
  return (
    <>
      <div className="row">
        <div className="field">
          <label>Name</label>
          <input type="text" value={value.name || ""} placeholder={namePlaceholder}
            onChange={(e) => upd({ name: e.target.value })} />
        </div>
        <div className="field">
          <label>Role</label>
          <input type="text" value={value.role || ""} placeholder="e.g. Researcher"
            onChange={(e) => upd({ role: e.target.value })} />
        </div>
      </div>
      <div className="row" style={{ marginTop: 8 }}>
        <div className="field">
          <label>Model</label>
          <ModelSelect provider={value.provider || "ollama"} model={value.model || ""}
            onChange={(provider, model) => upd({ provider, model })} />
        </div>
      </div>
      <div className="field" style={{ marginTop: 8 }}>
        <label>System prompt — who is this agent and how should it work?</label>
        <textarea rows={4} value={value.system_prompt || ""}
          placeholder="You are a meticulous research analyst. Break the task down…"
          onChange={(e) => upd({ system_prompt: e.target.value })} />
      </div>
      <ParamsEditor params={value.params || {}} onChange={(params) => upd({ params })} />
      <div className="field" style={{ marginTop: 8 }}>
        <label>Tools</label>
        <ToolsPicker selected={value.tools} onChange={(tools) => upd({ tools })} />
      </div>
    </>
  );
}
