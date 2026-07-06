import React, { useEffect, useState } from "react";
import { api, toast } from "../lib/api.js";
import { useApp } from "../App.jsx";

/* ---------------- skills ---------------- */

function SkillEditor({ skill, onClose, onSaved }) {
  const isNew = !skill?.id;
  const [data, setData] = useState(skill || {
    name: "", icon: "✨", description: "", instructions: "",
  });
  const save = async () => {
    try {
      const saved = isNew
        ? await api("/skills", { method: "POST", body: data })
        : await api(`/skills/${data.id}`, { method: "PUT", body: data });
      toast(isNew ? "Skill created" : "Skill saved");
      onSaved(saved);
    } catch (e) { toast(e.message, true); }
  };
  return (
    <div className="modal-back" onClick={(e) => e.target.classList.contains("modal-back") && onClose()}>
      <div className="modal">
        <div className="modal-head">
          <h2>{isNew ? "New skill" : `Edit ${data.name}`}</h2>
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
              <label>Skill name</label>
              <input type="text" value={data.name} placeholder="e.g. Structured Report"
                onChange={(e) => setData({ ...data, name: e.target.value })} />
            </div>
          </div>
          <div className="field">
            <label>Short description (shown in pickers)</label>
            <input type="text" value={data.description}
              placeholder="What does this skill make an agent do?"
              onChange={(e) => setData({ ...data, description: e.target.value })} />
          </div>
          <div className="field">
            <label>Instructions — appended to the agent's system prompt</label>
            <textarea rows={8} value={data.instructions}
              placeholder={"Write directives the agent must follow, e.g.\n" +
                "Format your output as a professional report: start with an executive summary…"}
              onChange={(e) => setData({ ...data, instructions: e.target.value })} />
          </div>
        </div>
        <div className="modal-foot">
          <button className="btn" onClick={onClose}>Cancel</button>
          <button className="btn primary" onClick={save}>{isNew ? "Create skill" : "Save changes"}</button>
        </div>
      </div>
    </div>
  );
}

/* ---------------- custom tool code editor ---------------- */

function ToolFileEditor({ file, template, onClose, onSaved }) {
  const isNew = !file;
  const [name, setName] = useState(file || "my_tool.py");
  const [code, setCode] = useState(template);
  const [result, setResult] = useState(null);

  useEffect(() => {
    if (file) api(`/tools/files/${file}`).then((d) => setCode(d.code)).catch(() => {});
  }, [file]);

  const save = async () => {
    if (!/^[A-Za-z0-9_\-]+\.py$/.test(name)) { toast("File name must be like my_tool.py", true); return; }
    try {
      const r = await api(`/tools/files/${name}`, { method: "PUT", body: { code } });
      setResult(r);
      if (r.error) toast("Saved, but the file has a problem — see below", true);
      else { toast(`Saved — loaded tools: ${r.loaded.join(", ")}`); onSaved(); }
    } catch (e) { toast(e.message, true); }
  };

  return (
    <div className="modal-back" onClick={(e) => e.target.classList.contains("modal-back") && onClose()}>
      <div className="modal" style={{ maxWidth: 860 }}>
        <div className="modal-head">
          <h2>{isNew ? "New custom tool" : `Edit ${file}`}</h2>
          <button className="btn ghost" onClick={onClose}>✕</button>
        </div>
        <div className="modal-body">
          <div className="field">
            <label>File name (in custom_tools/)</label>
            <input type="text" value={name} disabled={!isNew}
              onChange={(e) => setName(e.target.value)} />
          </div>
          <div className="field">
            <label>Python code — each @tool function becomes an agent tool</label>
            <textarea rows={16} value={code} spellCheck={false}
              style={{ fontFamily: "var(--mono)", fontSize: 12.5 }}
              onChange={(e) => setCode(e.target.value)} />
          </div>
          {result?.error && (
            <div className="tool-line" style={{ color: "var(--red)", borderColor: "#fda29b", background: "var(--red-soft)" }}>
              ⚠ {result.error}
            </div>
          )}
        </div>
        <div className="modal-foot">
          <button className="btn" onClick={onClose}>Close</button>
          <button className="btn primary" onClick={save}>Save & reload</button>
        </div>
      </div>
    </div>
  );
}

/* ---------------- page ---------------- */

export default function Toolbox() {
  const { reloadCatalogs } = useApp();
  const [skills, setSkills] = useState([]);
  const [catalog, setCatalog] = useState(null);
  const [editSkill, setEditSkill] = useState(undefined);
  const [editFile, setEditFile] = useState(undefined); // undefined closed, null new, "x.py" edit

  const load = () => {
    api("/skills").then(setSkills).catch(() => {});
    api("/tools").then(setCatalog).catch(() => {});
  };
  useEffect(() => { load(); }, []);
  const reload = () => { load(); reloadCatalogs?.(); };

  const delSkill = async (s, e) => {
    e.stopPropagation();
    if (!confirm(`Delete skill "${s.name}"?`)) return;
    await api(`/skills/${s.id}`, { method: "DELETE" });
    toast("Skill deleted");
    reload();
  };
  const delFile = async (fn) => {
    if (!confirm(`Delete ${fn} and its tools?`)) return;
    await api(`/tools/files/${fn}`, { method: "DELETE" });
    toast("Tool file deleted");
    reload();
  };

  return (
    <>
      <div className="page-head">
        <div>
          <h1 className="page-title">Skills & Tools</h1>
          <p className="page-sub">
            Skills shape how an agent behaves (prompt directives); tools give it things
            it can do (Python functions it can call)
          </p>
        </div>
      </div>

      {/* ---- skills ---- */}
      <div className="card section-card">
        <h2>✨ Skills</h2>
        <div className="sub">
          A skill is a reusable block of instructions appended to an agent's system
          prompt. Attach skills to agents in the team editor or on a persona.
        </div>
        <div className="grid" style={{ marginTop: 10 }}>
          {skills.map((s) => (
            <div key={s.id} className="card team-card persona-card" onClick={() => setEditSkill(s)}>
              <div className="top">
                <div className="team-icon">{s.icon}</div>
                <div>
                  <h3>{s.name} {s.builtin && <span className="chip" style={{ marginLeft: 4 }}>builtin</span>}</h3>
                </div>
              </div>
              <div className="desc">{s.description}</div>
              <div className="prompt-preview">{s.instructions}</div>
              <div className="card-actions">
                <button className="icon-btn" title="Edit" onClick={(e) => { e.stopPropagation(); setEditSkill(s); }}>✏️</button>
                <button className="icon-btn" title="Delete" onClick={(e) => delSkill(s, e)}>🗑️</button>
              </div>
            </div>
          ))}
          <div className="new-card" onClick={() => setEditSkill(null)}>
            <div className="plus">＋</div>Create a skill
          </div>
        </div>
        <h3 style={{ fontSize: 13, margin: "18px 0 4px" }}>How to create a good skill</h3>
        <div className="steps">
          <div className="step-item"><div className="step-num">1</div>
            <div>Click <strong>Create a skill</strong> and give it a clear name and a one-line description (agents pickers show these).</div></div>
          <div className="step-item"><div className="step-num">2</div>
            <div>Write the instructions as <em>directives</em>, not descriptions: “Format output as…”, “Always end with…”, “Never present a guess as fact”. They are injected verbatim into the agent's system prompt under a <code>## Skill</code> heading.</div></div>
          <div className="step-item"><div className="step-num">3</div>
            <div>Keep each skill focused on one behavior. Combine multiple small skills on an agent instead of writing one giant skill — they compose.</div></div>
          <div className="step-item"><div className="step-num">4</div>
            <div>Attach it: team editor → agent → <strong>Skills</strong>, or add it to a persona so every agent created from that persona has it.</div></div>
        </div>
      </div>

      {/* ---- tools ---- */}
      <div className="card section-card">
        <h2>🛠️ Tools</h2>
        <div className="sub">
          Tools are Python functions agents can call while working (function calling).
          Builtin tools ship with the app; custom tools are .py files in
          <code> custom_tools/</code> — created here or with any editor.
        </div>

        <h3 style={{ fontSize: 13, margin: "14px 0 6px" }}>Builtin</h3>
        <table className="assess">
          <thead><tr><th>Tool</th><th>Description</th></tr></thead>
          <tbody>
            {(catalog?.builtin || []).map((t) => (
              <tr key={t.name}>
                <td className="mono">{t.name}</td>
                <td>{t.description}</td>
              </tr>
            ))}
          </tbody>
        </table>

        <h3 style={{ fontSize: 13, margin: "18px 0 6px" }}>
          Custom
          <button className="btn sm" style={{ marginLeft: 10 }} onClick={() => setEditFile(null)}>＋ New tool file</button>
        </h3>
        {!(catalog?.files || []).length && (
          <p className="page-sub">No custom tools yet — create one to see it appear in every agent's tool picker.</p>
        )}
        {(catalog?.files || []).map((f) => (
          <div key={f.file} className="agent-box" style={{ marginBottom: 8 }}>
            <div className="agent-box-head" style={{ marginBottom: 0 }}>
              <span className="mono" style={{ fontFamily: "var(--mono)", fontSize: 13 }}>{f.file}</span>
              {f.error
                ? <span className="verdict no" title={f.error}>load error</span>
                : <span className="verdict great">{f.tools.length} tool{f.tools.length !== 1 ? "s" : ""} loaded</span>}
              {!f.error && f.tools.map((t) => <span key={t} className="chip">{t}</span>)}
              <span className="spacer" />
              <button className="icon-btn" title="Edit" onClick={() => setEditFile(f.file)}>✏️</button>
              <button className="icon-btn" title="Delete" onClick={() => delFile(f.file)}>🗑️</button>
            </div>
            {f.error && <div className="param-hint" style={{ color: "var(--red)", marginTop: 6 }}>{f.error}</div>}
          </div>
        ))}

        <h3 style={{ fontSize: 13, margin: "18px 0 4px" }}>How to create a custom tool</h3>
        <div className="steps">
          <div className="step-item"><div className="step-num">1</div>
            <div>Click <strong>New tool file</strong> (or drop a .py file into <code>custom_tools/</code>). One file can define several tools.</div></div>
          <div className="step-item"><div className="step-num">2</div>
            <div>Decorate a plain Python function with <code>@tool</code> from <code>langchain_core.tools</code>. Type-annotate the arguments and return a string.
              <span className="cmd">{catalog?.template || ""}</span></div></div>
          <div className="step-item"><div className="step-num">3</div>
            <div>The <em>docstring is the contract</em>: the model reads it to decide when to call the tool — say what it does, when to use it, and what each argument means.</div></div>
          <div className="step-item"><div className="step-num">4</div>
            <div><strong>Save & reload</strong> validates the file instantly; load errors show here without breaking anything. Then enable the tool on any agent under → <strong>Tools</strong>.</div></div>
          <div className="step-item"><div className="step-num">5</div>
            <div>Tip: tool calling needs a model that supports it well — qwen2.5 models do; tinyllama does not.</div></div>
        </div>
      </div>

      {editSkill !== undefined && (
        <SkillEditor skill={editSkill} onClose={() => setEditSkill(undefined)}
          onSaved={() => { setEditSkill(undefined); reload(); }} />
      )}
      {editFile !== undefined && (
        <ToolFileEditor file={editFile} template={catalog?.template || ""}
          onClose={() => setEditFile(undefined)}
          onSaved={() => reload()} />
      )}
    </>
  );
}
