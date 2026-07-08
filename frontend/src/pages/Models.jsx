import React from "react";
import { useApp } from "../App.jsx";
import CatalogTable from "../components/CatalogTable.jsx";
import ImageGen from "../components/ImageGen.jsx";

export default function Models() {
  const { models, health } = useApp();
  if (!health) return null;
  const groups = [
    ["ollama", "Ollama", health.providers.ollama],
    ["lmstudio", "LM Studio", health.providers.lmstudio],
  ];
  return (
    <>
      <div className="page-head">
        <div>
          <h1 className="page-title">Models</h1>
          <p className="page-sub">Chat models discovered from your local providers</p>
        </div>
        <a className="btn" href="#/settings">⚙️ Which models fit my PC?</a>
      </div>
      {groups.map(([key, label, st]) => (
        <div key={key} className="model-group card" style={{ padding: 16 }}>
          <h3>
            <span className={"dot " + (st.up ? "up" : "down")} />
            {label}
            <span style={{ fontWeight: 400, color: "var(--text-3)", fontSize: 12 }}>
              {st.url}{st.up ? "" : " — offline"}
            </span>
          </h3>
          <div className="model-list">
            {(models[key] || []).map((m) => <span key={m} className="model-pill">{m}</span>)}
            {!(models[key] || []).length && (
              <span style={{ color: "var(--text-3)" }}>
                {st.up ? "No chat models loaded." : "Provider not reachable — see the Setup page."}
              </span>
            )}
          </div>
        </div>
      ))}
      <div className="card section-card" style={{ marginTop: 16 }}>
        <h2>⬇ Get more models</h2>
        <div className="sub">
          Everything in the Ollama library, assessed against this machine —
          see Settings for the hardware details behind the verdicts.
        </div>
        <CatalogTable compact />
      </div>
      <ImageGen />
    </>
  );
}
