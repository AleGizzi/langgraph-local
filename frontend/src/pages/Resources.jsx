import React, { useEffect, useState } from "react";
import { api, toast } from "../lib/api.js";
import Tabs from "../components/Tabs.jsx";

const CAT_META = {
  news: ["📰", "AI News"],
  training: ["🎓", "Local LLM Trainings"],
  tools: ["🧰", "Tools & Models"],
};

function host(url) {
  try { return new URL(url).hostname.replace(/^www\./, ""); } catch { return url; }
}
function ago(ts) {
  const d = Math.floor(Date.now() / 1000 - ts);
  if (d < 3600) return `${Math.floor(d / 60)}m`;
  if (d < 86400) return `${Math.floor(d / 3600)}h`;
  return `${Math.floor(d / 86400)}d`;
}

export default function Resources() {
  const [items, setItems] = useState([]);
  const [cat, setCat] = useState("news");
  const [refreshing, setRefreshing] = useState(false);
  const [adding, setAdding] = useState(false);
  const [manual, setManual] = useState({ url: "", title: "" });
  const [editingPrompt, setEditingPrompt] = useState(false);
  const [prompt, setPrompt] = useState("");
  const [promptDefault, setPromptDefault] = useState("");
  const [models, setModels] = useState([]);   // ["ollama/qwen2.5:7b", …]
  const [model, setModel] = useState("");     // "" = auto-pick

  const load = () => api("/resources").then((d) => setItems(d.resources)).catch(() => {});
  useEffect(() => { load(); }, []);
  useEffect(() => {
    api("/models").then((d) => {
      const out = [];
      Object.entries(d || {}).forEach(([prov, names]) => {
        if (Array.isArray(names)) names.forEach((n) => out.push(`${prov}/${n}`));
      });
      setModels(out);
    }).catch(() => {});
  }, []);
  useEffect(() => {
    api(`/resources/prompt?category=${cat}`).then((d) => {
      setPrompt(d.prompt); setPromptDefault(d.default);
      setModel(d.model?.model ? `${d.model.provider}/${d.model.model}` : "");
    }).catch(() => {});
    setEditingPrompt(false);
  }, [cat]);

  // "ollama/qwen2.5:7b" -> {provider, model}; "" -> {provider:"", model:""}.
  // Only the FIRST slash splits: model names themselves can contain slashes.
  const splitModel = (v) => {
    const i = (v || "").indexOf("/");
    return i < 0 ? { provider: "", model: "" }
                 : { provider: v.slice(0, i), model: v.slice(i + 1) };
  };

  const savePrompt = async () => {
    await api("/resources/prompt", {
      method: "PUT", body: { category: cat, prompt, ...splitModel(model) },
    });
    toast("Search prompt saved — future refreshes will use it");
    setEditingPrompt(false);
  };

  const refresh = async () => {
    setRefreshing(true);
    try {
      const r = await api("/resources/refresh", {
        method: "POST", body: { category: cat, n: 6, ...splitModel(model) },
      });
      if (!r.ok) toast(r.error || "Refresh failed", true);
      else toast(`Found ${r.found}, added ${r.added} new link${r.added !== 1 ? "s" : ""} (via ${r.model})`);
      load();
    } catch (e) { toast(e.message, true); }
    setRefreshing(false);
  };

  const addManual = async () => {
    if (!manual.url.trim()) { toast("Paste a URL", true); return; }
    await api("/resources", { method: "POST", body: { ...manual, category: cat } });
    setManual({ url: "", title: "" }); setAdding(false); load();
  };

  const del = async (r) => {
    await api(`/resources/${r.id}`, { method: "DELETE" });
    load();
  };

  const shown = items.filter((r) => r.category === cat);

  return (
    <>
      <div className="page-head">
        <div>
          <h1 className="page-title">AI News & Resources</h1>
          <p className="page-sub">
            Curated links on AI news, running local LLMs, and open-source tools —
            refresh any category with a web-researching agent.
          </p>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <button className="btn" onClick={() => setEditingPrompt(!editingPrompt)}>
            ✏️ Search prompt & model
          </button>
          <button className="btn" onClick={() => setAdding(!adding)}>＋ Add link</button>
          <button className="btn primary" onClick={refresh} disabled={refreshing}>
            {refreshing ? "🔎 Researching…" : "🔄 Refresh with agent"}
          </button>
        </div>
      </div>

      <Tabs active={cat} onChange={setCat} tabs={Object.entries(CAT_META).map(([k, [ico, label]]) => ({
        key: k, label: `${ico} ${label}`,
        badge: items.filter((r) => r.category === k).length || undefined,
      }))} />

      {editingPrompt && (
        <div className="card" style={{ padding: 14, marginBottom: 12 }}>
          <div style={{ fontWeight: 600, fontSize: 13.5, marginBottom: 4 }}>
            What the agent looks for in <b>{CAT_META[cat][1]}</b>, and which model does it
          </div>
          <div className="help" style={{ marginBottom: 8 }}>
            Edit what the research agent searches for when you click "Refresh". Describe the
            kind of {CAT_META[cat][1].toLowerCase()} you want — the agent adds the search and
            JSON-format handling itself. This is how you tune your list over time.
          </div>
          <textarea rows={5} value={prompt} onChange={(e) => setPrompt(e.target.value)}
            style={{ width: "100%", padding: 9, border: "1px solid var(--border)",
                     borderRadius: 6, fontSize: 13, resize: "vertical" }} />

          <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 10,
                        flexWrap: "wrap" }}>
            <label style={{ fontWeight: 600, fontSize: 13 }}>Model</label>
            <select value={model} onChange={(e) => setModel(e.target.value)}
              style={{ padding: "6px 9px", border: "1px solid var(--border)",
                       borderRadius: 6, fontSize: 13, minWidth: 220 }}>
              <option value="">Auto (first qwen2.5, else any)</option>
              {models.map((m) => <option key={m} value={m}>{m}</option>)}
            </select>
          </div>
          <div className="help" style={{ marginTop: 4 }}>
            The model that does the searching. It must support <b>tool calling</b>
            {" "}— a model without it (or too small) will skip the web search and
            invent plausible-looking links instead. If a category keeps returning
            made-up URLs, try a bigger model here before rewriting the prompt.
          </div>

          <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
            <button className="btn primary sm" onClick={savePrompt}>Save prompt</button>
            <button className="btn sm" onClick={() => setPrompt(promptDefault)}>Reset to default</button>
            <button className="btn sm ghost" onClick={() => setEditingPrompt(false)}>Cancel</button>
          </div>
        </div>
      )}

      {adding && (
        <div className="card" style={{ padding: 12, marginBottom: 12, display: "flex", gap: 8, flexWrap: "wrap" }}>
          <input type="text" value={manual.url} placeholder="https://…"
            onChange={(e) => setManual({ ...manual, url: e.target.value })}
            style={{ flex: 2, minWidth: 200, padding: "7px 9px", border: "1px solid var(--border)", borderRadius: 6 }} />
          <input type="text" value={manual.title} placeholder="Title (optional)"
            onChange={(e) => setManual({ ...manual, title: e.target.value })}
            style={{ flex: 1, minWidth: 140, padding: "7px 9px", border: "1px solid var(--border)", borderRadius: 6 }} />
          <button className="btn primary" onClick={addManual}>Add to {CAT_META[cat][1]}</button>
        </div>
      )}

      {refreshing && (
        <div className="help" style={{ padding: 12, marginBottom: 10 }}>
          🔎 An agent is searching the web for fresh {CAT_META[cat][1].toLowerCase()} — this
          takes ~1-2 minutes on a local model.
        </div>
      )}

      {!shown.length && !refreshing && (
        <div className="empty" style={{ padding: 40 }}>
          <div className="big">{CAT_META[cat][0]}</div>
          No links here yet. Click <strong>Refresh with agent</strong> to have a
          research agent find some, or add one by hand.
        </div>
      )}

      <div className="res-list">
        {shown.map((r) => (
          <div key={r.id} className="res-card">
            <a className="res-link" href={r.url} target="_blank" rel="noreferrer">
              <div className="res-title">{r.title}</div>
              {r.summary && <div className="res-summary">{r.summary}</div>}
              <div className="res-meta">
                🔗 {host(r.url)} · {r.source === "agent" ? "🤖 found by agent" : "✍️ added by you"} · {ago(r.added_at)} ago
              </div>
            </a>
            <button className="icon-btn res-del" title="Remove" onClick={() => del(r)}>🗑️</button>
          </div>
        ))}
      </div>
    </>
  );
}
