import React, { useState } from "react";
import { useApp } from "../App.jsx";
import CatalogTable from "../components/CatalogTable.jsx";
import ImageGen from "../components/ImageGen.jsx";
import VideoMaker from "../components/VideoMaker.jsx";
import ModelCard from "../components/ModelCard.jsx";
import Tabs, { useTab } from "../components/Tabs.jsx";

export default function Models() {
  const { models, health } = useApp();
  const [card, setCard] = useState(null);
  const [tab, setTab] = useTab("models", "text");
  if (!health) return null;
  const groups = [
    ["ollama", "Ollama", health.providers.ollama],
    ["lmstudio", "LM Studio", health.providers.lmstudio],
  ];
  const nText = (models.ollama || []).length + (models.lmstudio || []).length;
  return (
    <>
      <div className="page-head">
        <div>
          <h1 className="page-title">Models</h1>
          <p className="page-sub">
            Your local models — click any one to see what it's best used for
          </p>
        </div>
        <a className="btn" href="#/settings">⚙️ Which models fit my PC?</a>
      </div>

      <Tabs active={tab} onChange={setTab} tabs={[
        { key: "text", label: "🧠 Text models", badge: nText },
        { key: "image", label: "🎨 Image generation" },
        { key: "video", label: "🎬 Video" },
      ]} />

      {tab === "text" && <>
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
            {(models[key] || []).map((m) => (
              <span key={m} className="model-pill clickable"
                title="See what this model is best used for"
                onClick={() => setCard({ name: m, provider: key })}>{m} →</span>
            ))}
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
      </>}

      {tab === "image" && <ImageGen />}
      {tab === "video" && <VideoMaker startOpen />}

      {card && (
        <ModelCard name={card.name} provider={card.provider}
          onClose={() => setCard(null)} />
      )}
    </>
  );
}
