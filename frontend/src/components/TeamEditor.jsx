import React, { useEffect, useState } from "react";
import { api, toast } from "../lib/api.js";
import { useApp } from "../App.jsx";
import AgentFields from "./AgentFields.jsx";
import GraphEditor from "./GraphEditor.jsx";
import WizardPanel from "./WizardPanel.jsx";

let keyCounter = 0;
const withKey = (a) => ({ ...a, _key: a._key ?? `k${++keyCounter}` });

function defaultGraphFor(agents) {
  // Sensible starting point: a straight line through all agents.
  const nodes = agents.filter((a) => a.name).map((a, i) => ({ id: `n${i + 1}`, agent: a.name }));
  const edges = [];
  if (nodes.length) {
    edges.push({ source: "start", target: nodes[0].id });
    for (let i = 0; i < nodes.length - 1; i++) {
      edges.push({ source: nodes[i].id, target: nodes[i + 1].id });
    }
    edges.push({ source: nodes.at(-1).id, target: "end" });
  }
  const positions = { start: { x: 10, y: 150 }, end: { x: 200 + nodes.length * 210, y: 150 } };
  nodes.forEach((n, i) => { positions[n.id] = { x: 190 + i * 210, y: 140 }; });
  return { nodes, edges, positions };
}

export default function TeamEditor({ team, wizard, onClose, onSaved }) {
  const isNew = !team;
  const { models } = useApp();
  const [personas, setPersonas] = useState([]);
  const [sys, setSys] = useState(null);
  const [data, setData] = useState(() => {
    const base = team ? JSON.parse(JSON.stringify(team)) : {
      name: "", icon: "🤖", description: "", topology: "pipeline",
      settings: { quality_loop: false, max_revisions: 2, max_steps: 8, parallel: false },
      agents: [],
      graph: null,
    };
    base.agents = (base.agents.length ? base.agents : [{
      name: "Agent 1", role: "", provider: "ollama", model: "", system_prompt: "",
      params: {}, tools: [],
    }]).map(withKey);
    return base;
  });

  useEffect(() => { api("/personas").then(setPersonas).catch(() => {}); }, []);
  useEffect(() => { api("/system").then(setSys).catch(() => {}); }, []);

  // Default model once models arrive (for agents created before load).
  useEffect(() => {
    const pick = (list) =>
      list.find((m) => /^(qwen|llama|mistral|gemma)/i.test(m) && !/r1|coder|think/i.test(m)) || list[0] || "";
    const fallback = pick(models.ollama || []) || pick(models.lmstudio || []);
    if (!fallback) return;
    setData((d) => ({
      ...d,
      agents: d.agents.map((a) => (a.model ? a : { ...a, model: fallback, provider: (models.ollama || []).length ? "ollama" : "lmstudio" })),
    }));
  }, [models]);

  const upd = (patch) => setData((d) => ({ ...d, ...patch }));
  const updAgent = (i, next) => setData((d) => {
    const agents = [...d.agents];
    const old = agents[i];
    agents[i] = { ...next, _key: old._key };
    let graph = d.graph;
    if (graph && old.name !== next.name) {
      graph = { ...graph, nodes: graph.nodes.map((n) => n.agent === old.name ? { ...n, agent: next.name } : n) };
    }
    return { ...d, agents, graph };
  });

  const addAgent = (fromPersona) => setData((d) => {
    const base = fromPersona ? {
      name: uniqueName(fromPersona.name, d.agents), role: fromPersona.role,
      provider: fromPersona.provider, model: fromPersona.model || "",
      system_prompt: fromPersona.system_prompt,
      params: { ...(fromPersona.params || {}) }, tools: [...(fromPersona.tools || [])],
      skills: [...(fromPersona.skills || [])],
    } : {
      name: uniqueName(`Agent ${d.agents.length + 1}`, d.agents), role: "",
      provider: "ollama", model: "", system_prompt: "", params: {}, tools: [], skills: [],
    };
    return { ...d, agents: [...d.agents, withKey(base)] };
  });

  const uniqueName = (name, agents) => {
    let n = name, i = 2;
    const names = new Set(agents.map((a) => a.name.toLowerCase()));
    while (names.has(n.toLowerCase())) n = `${name} ${i++}`;
    return n;
  };

  const applyPersona = (i, persona) => {
    const a = data.agents[i];
    updAgent(i, {
      ...a,
      name: a.name.startsWith("Agent ") ? uniqueName(persona.name, data.agents.filter((_, j) => j !== i)) : a.name,
      role: persona.role,
      provider: persona.model ? persona.provider : a.provider,
      model: persona.model || a.model,
      system_prompt: persona.system_prompt,
      params: { ...(persona.params || {}) },
      tools: [...(persona.tools || [])],
      skills: [...(persona.skills || [])],
    });
    toast(`Applied persona: ${persona.name}`);
  };

  const saveAsPersona = async (a) => {
    try {
      await api("/personas", { method: "POST", body: {
        name: a.name, icon: "🧑", role: a.role, description: `Saved from team editor`,
        system_prompt: a.system_prompt, provider: a.provider, model: a.model,
        params: a.params, tools: a.tools, skills: a.skills,
      }});
      toast(`Saved "${a.name}" as a persona`);
    } catch (e) { toast(e.message, true); }
  };

  const move = (i, dir) => setData((d) => {
    const agents = [...d.agents];
    [agents[i], agents[i + dir]] = [agents[i + dir], agents[i]];
    return { ...d, agents };
  });
  const remove = (i) => setData((d) => {
    const victim = d.agents[i];
    let graph = d.graph;
    if (graph) {
      const dead = new Set(graph.nodes.filter((n) => n.agent === victim.name).map((n) => n.id));
      graph = {
        ...graph,
        nodes: graph.nodes.filter((n) => !dead.has(n.id)),
        edges: graph.edges.filter((e) => !dead.has(e.source) && !dead.has(e.target)),
      };
    }
    return { ...d, agents: d.agents.filter((_, j) => j !== i), graph };
  });

  const setTopology = (topology) => setData((d) => ({
    ...d, topology,
    graph: topology === "graph" ? (d.graph || defaultGraphFor(d.agents)) : d.graph,
  }));

  // Load an AI-wizard team draft into the editor for review.
  const applyDraft = (draft) => {
    setData((d) => ({
      ...d,
      name: draft.name || d.name,
      icon: draft.icon || d.icon,
      description: draft.description ?? d.description,
      topology: draft.topology || "pipeline",
      settings: { ...d.settings, ...(draft.settings || {}) },
      agents: (draft.agents || []).map(withKey),
      graph: draft.topology === "graph" ? (draft.graph || null) : null,
    }));
  };

  const save = async () => {
    const body = { ...data, agents: data.agents.map(({ _key, ...a }) => a) };
    if (body.topology !== "graph") delete body.graph;
    try {
      const saved = isNew
        ? await api("/teams", { method: "POST", body })
        : await api(`/teams/${data.id}`, { method: "PUT", body });
      toast(isNew ? "Team created" : "Team saved");
      onSaved(saved);
    } catch (e) { toast(e.message, true); }
  };

  const s = data.settings;
  const roleLabel = (i) => {
    if (data.topology === "supervisor") return i === 0 ? "SUPERVISOR" : `WORKER ${i}`;
    if (data.topology === "graph") return "AGENT";
    if (data.topology === "pipeline" && s.quality_loop && i === data.agents.length - 1)
      return `STEP ${i + 1} · REVIEWER`;
    return `STEP ${i + 1}`;
  };

  return (
    <div className="modal-back" onClick={(e) => e.target.classList.contains("modal-back") && onClose()}>
      <div className="modal" style={{ maxWidth: data.topology === "graph" ? 980 : 760 }}>
        <div className="modal-head">
          <h2>{isNew ? (wizard ? "New team — AI wizard" : "New team") : `Edit ${data.name}`}</h2>
          <button className="btn ghost" onClick={onClose}>✕</button>
        </div>
        <div className="modal-body">
          {wizard && (
            <WizardPanel kind="team"
              buildPayload={() => ({
                current: { ...data, agents: data.agents.map(({ _key, ...a }) => a) },
              })}
              onDraft={applyDraft} />
          )}
          <div className="row">
            <div className="field narrow">
              <label>Icon</label>
              <input type="text" maxLength={4} value={data.icon}
                onChange={(e) => upd({ icon: e.target.value })} />
            </div>
            <div className="field">
              <label>Team name</label>
              <input type="text" value={data.name} placeholder="e.g. Research & Report"
                onChange={(e) => upd({ name: e.target.value })} />
            </div>
          </div>
          <div className="field">
            <label>Description</label>
            <input type="text" value={data.description} placeholder="What does this team do?"
              onChange={(e) => upd({ description: e.target.value })} />
          </div>
          <div className="field">
            <label>Topology</label>
            <select value={data.topology} onChange={(e) => setTopology(e.target.value)}>
              <option value="pipeline">Pipeline — agents run in order</option>
              <option value="supervisor">Supervisor — first agent delegates dynamically</option>
              <option value="router">Router — classify once, dispatch to one specialist</option>
              <option value="graph">Custom pipeline — visual graph with branches</option>
              <option value="single">Single agent</option>
            </select>
          </div>

          {data.topology === "pipeline" && (
            <>
              <div className="switch-row">
                <input type="checkbox" checked={!!s.quality_loop}
                  onChange={(e) => upd({ settings: { ...s, quality_loop: e.target.checked } })} />
                Quality loop — last agent reviews and can send work back
              </div>
              {s.quality_loop && (
                <div className="row">
                  <div className="field narrow">
                    <label>Max revisions</label>
                    <input type="number" min={0} max={5} value={s.max_revisions ?? 2}
                      onChange={(e) => upd({ settings: { ...s, max_revisions: +e.target.value } })} />
                  </div>
                </div>
              )}
            </>
          )}
          {data.topology === "supervisor" && (
            <div className="row">
              <div className="field narrow">
                <label>Max steps</label>
                <input type="number" min={1} max={20} value={s.max_steps ?? 8}
                  onChange={(e) => upd({ settings: { ...s, max_steps: +e.target.value } })} />
              </div>
              <div className="field">
                <div className="help" style={{ marginTop: 22 }}>
                  The first agent acts as supervisor; the rest are workers it delegates to.
                </div>
              </div>
            </div>
          )}
          <div className="switch-row">
            <input type="checkbox" checked={!!s.parallel}
              onChange={(e) => upd({ settings: { ...s, parallel: e.target.checked } })} />
            Run agents in parallel when the pipeline branches
            {sys && <span className="chip topo">up to ×{sys.assessment.parallel.capacity} on this PC</span>}
          </div>
          {s.parallel && sys && (
            <div className="help">{sys.assessment.parallel.reason}</div>
          )}

          <div className="field">
            <label>Agents</label>
            {personas.length > 0 && (
              <div className="persona-strip">
                <span className="help" style={{ marginRight: 2, marginTop: 4 }}>Add from persona:</span>
                {personas.map((p) => (
                  <span key={p.id} className="persona-chip" title={p.description}
                    onClick={() => addAgent(p)}>{p.icon} {p.name}</span>
                ))}
              </div>
            )}
            <div className="agents-editor">
              {data.agents.map((a, i) => (
                <div key={a._key} className="agent-box">
                  <div className="agent-box-head">
                    <span className="n">{roleLabel(i)}</span>
                    <span className="spacer" />
                    <select
                      value=""
                      style={{ fontSize: 12, padding: "3px 6px", borderRadius: 7 }}
                      onChange={(e) => {
                        const p = personas.find((x) => x.id === +e.target.value);
                        if (p) applyPersona(i, p);
                      }}>
                      <option value="" disabled>Apply persona…</option>
                      {personas.map((p) => <option key={p.id} value={p.id}>{p.icon} {p.name}</option>)}
                    </select>
                    <button type="button" className="icon-btn" title="Save as persona"
                      onClick={() => saveAsPersona(a)}>💾</button>
                    {i > 0 && <button type="button" className="icon-btn" title="Move up" onClick={() => move(i, -1)}>↑</button>}
                    {i < data.agents.length - 1 && <button type="button" className="icon-btn" title="Move down" onClick={() => move(i, 1)}>↓</button>}
                    {data.agents.length > 1 && <button type="button" className="icon-btn" title="Remove" onClick={() => remove(i)}>🗑️</button>}
                  </div>
                  <AgentFields value={a} onChange={(next) => updAgent(i, next)} />
                </div>
              ))}
              <button type="button" className="btn" onClick={() => addAgent(null)}>＋ Add blank agent</button>
            </div>
          </div>

          {data.topology === "graph" && data.graph && (
            <div className="field">
              <label>Pipeline canvas</label>
              <GraphEditor
                agents={data.agents}
                graph={data.graph}
                onChange={(graph) => upd({ graph })}
              />
            </div>
          )}
        </div>
        <div className="modal-foot">
          <button className="btn" onClick={onClose}>Cancel</button>
          <button className="btn primary" onClick={save}>{isNew ? "Create team" : "Save changes"}</button>
        </div>
      </div>
    </div>
  );
}
