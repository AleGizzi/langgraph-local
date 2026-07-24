import React, { useEffect, useState } from "react";
import { api, toast } from "../lib/api.js";

/* "What is this model best used for?" — the model equivalent of a persona's
 * Pokédex card. All scores come from the server (modelinfo.py, deterministic). */

const BAR_COLORS = {
  brainstorming: "violet", problem_solving: "green", execution: "accent",
  tool_use: "amber", coding: "accent", writing: "violet",
  speed: "amber", long_context: "teal",
};

export default function ModelCard({ name, provider = "ollama", onClose }) {
  const [c, setCard] = useState(null);

  useEffect(() => {
    api(`/models/card?name=${encodeURIComponent(name)}&provider=${provider}`)
      .then(setCard)
      .catch((e) => { toast(e.message, true); onClose(); });
  }, [name, provider]);

  if (!c) return null;

  // Where you'd fetch this model by hand. Ollama's library page carries the
  // exact `ollama pull` command + all tags; LM Studio models live on HF.
  const slug = c.name.split(":")[0];
  const manualUrl = c.provider === "lmstudio"
    ? `https://huggingface.co/models?search=${encodeURIComponent(slug)}`
    : `https://ollama.com/library/${slug}`;
  const manualLabel = c.provider === "lmstudio"
    ? "Find on Hugging Face" : "View on ollama.com";

  const spec = [
    ["Model ID", `${c.provider}/${c.name}`],
    ["Parameters", `${c.params_b}B`],
    c.size_gb && ["Size on disk", `${c.size_gb} GB`],
    c.quant && ["Quantization", c.quant],
    ["Speed here", c.est_tok_s ? `~${c.est_tok_s} tok/s` : "—"],
    ["Native tool use", c.native_tools ? "yes" : "no (delegated in team runs)"],
    ["Reasoning model", c.thinking ? "yes — thinks before answering" : "no"],
    c.verdict && ["Runs on this PC", c.verdict === "no" ? "won't run" : c.verdict],
  ].filter(Boolean);

  return (
    <div className="modal-back" onClick={(e) => e.target.classList.contains("modal-back") && onClose()}>
      <div className="dex-card">
        <div className="dex-head">
          <span className="dex-icon">🧠</span>
          <h2 style={{ fontFamily: "var(--mono)", fontSize: 19 }}>{c.name}</h2>
          <span className="dex-level">Lv. {c.level}</span>
          <span className="spacer" style={{ flex: 1 }} />
          {c.capabilities.map((cap) => (
            <span key={cap} className="dex-chip">{cap}</span>
          ))}
          <span className={"dex-active"} style={
            c.installed ? undefined : { background: "#3a2a10", color: "#f5b83d", borderColor: "#8a6520" }}>
            {c.installed ? "INSTALLED" : "NOT INSTALLED"}
          </span>
          <button className="btn ghost" style={{ color: "#cfe3ea" }} onClick={onClose}>✕</button>
        </div>

        <div className="dex-body" style={{ gridTemplateColumns: "1fr 1.15fr" }}>
          <div className="dex-specs">
            {spec.map(([k, v]) => (
              <div key={k} className="dex-spec-row">
                <span className="k">{k}</span><span className="v">{String(v)}</span>
              </div>
            ))}
            {c.description && (
              <div className="param-hint" style={{ color: "#9fc3cf", marginTop: 10 }}>
                {c.description}
              </div>
            )}
            <div style={{ marginTop: 10, display: "flex", flexWrap: "wrap",
                          alignItems: "center", gap: 8 }}>
              <a className="btn sm" href={manualUrl} target="_blank" rel="noreferrer"
                title="Download / inspect this model by hand">
                ⬇ {manualLabel}
              </a>
              {c.provider !== "lmstudio" && (
                <code className="param-hint" style={{ fontFamily: "var(--mono)" }}>
                  ollama pull {c.name}
                </code>
              )}
            </div>
          </div>

          <div className="dex-stats">
            {c.aptitudes.map((a) => (
              <div key={a.key} className="dex-stat" title={a.meaning}>
                <div className="dex-stat-head">
                  <span>{a.icon} {a.label.toUpperCase()}</span><b>{a.score}/10</b>
                </div>
                <div className="dex-bar">
                  {Array.from({ length: 10 }, (_, i) => (
                    <span key={i}
                      className={"seg " + (i < a.score ? "on " + (BAR_COLORS[a.key] || "accent") : "")} />
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="dex-lower" style={{ gridTemplateColumns: "1.2fr 1fr" }}>
          <div className="dex-panel">
            <h4>✅ BEST USED FOR</h4>
            {c.best_for.map((b) => (
              <div key={b.title} className="dex-ability">
                <b>{b.title}</b>
                <span>{b.why}</span>
              </div>
            ))}
          </div>
          <div className="dex-panel">
            <h4>⚠️ AVOID / WATCH OUT</h4>
            {c.avoid.length
              ? c.avoid.map((a, i) => (
                <div key={i} className="dex-ability">
                  <span style={{ color: "#ffc7b8" }}>{a}</span>
                </div>
              ))
              : <span className="dex-dim">No particular caveats.</span>}
            {c.notes.length > 0 && (
              <>
                <h4 style={{ marginTop: 10 }}>💡 SETTINGS TIPS</h4>
                {c.notes.map((n, i) => <div key={i} className="dex-dim">{n}</div>)}
              </>
            )}
          </div>
        </div>

        <div className="dex-foot">
          <span className="dex-personality">
            💬 <b>SUGGESTED START</b> temperature {c.suggested_params.temperature} ·
            max tokens {c.suggested_params.num_predict} · context {c.suggested_params.num_ctx}
          </span>
          <button className="btn sm primary" onClick={() => (location.hash = "#/chat")}>
            💬 Try it in Chat
          </button>
        </div>
      </div>
    </div>
  );
}
