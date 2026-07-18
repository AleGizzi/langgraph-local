import React, { useEffect, useState } from "react";
import { api, toast } from "../lib/api.js";
import CatalogTable from "../components/CatalogTable.jsx";
import ImageModels from "../components/ImageModels.jsx";
import FreeMemory from "../components/FreeMemory.jsx";
import ModelCard from "../components/ModelCard.jsx";
import Tabs, { useTab } from "../components/Tabs.jsx";

function AssessTable({ rows, showInstalled, onPick }) {
  return (
    <table className="assess">
      <thead>
        <tr>
          <th>Model</th><th>Size</th><th>Est. speed</th><th>Verdict</th><th></th>
        </tr>
      </thead>
      <tbody>
        {rows.map((m) => (
          <tr key={m.name}>
            <td className="mono">
              {m.name}
              {m.tag && m.tag !== "general" && <span className="chip" style={{ marginLeft: 7 }}>{m.tag}</span>}
              {showInstalled && m.installed && <span className="badge-installed">installed</span>}
            </td>
            <td>{m.size_gb} GB</td>
            <td>{m.est_tok_s ? `~${m.est_tok_s} tok/s` : "—"}</td>
            <td><span className={"verdict " + m.verdict} title={m.verdict_label}>{m.verdict === "no" ? "won't run" : m.verdict}</span></td>
            <td>
              <button className="btn sm" onClick={() => onPick(m.name)}>
                What's it for?
              </button>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function DesktopAppCard() {
  const [st, setSt] = React.useState(null);
  const [busy, setBusy] = React.useState(false);
  React.useEffect(() => { api("/desktop-app").then(setSt).catch(() => {}); }, []);
  const install = async () => {
    setBusy(true);
    try {
      await api("/desktop-app/install", { method: "POST" });
      toast("Installed — look for 'Agent Studio' in your app launcher");
      setSt({ installed: true });
    } catch (e) { toast(e.message, true); }
    setBusy(false);
  };
  return (
    <div className="card section-card">
      <h2>🖥️ Install as a desktop app</h2>
      <div className="sub">
        Add <strong>Agent Studio</strong> to your Pop!_OS / GNOME app launcher and
        dock. Launching it starts the local server (if needed) and opens a
        dedicated app window — no browser tab. No admin password required.
      </div>
      <div style={{ marginTop: 10, display: "flex", gap: 10, alignItems: "center" }}>
        {st?.installed
          ? <span className="chip" style={{ color: "var(--green)" }}>✅ Installed — find it in your launcher</span>
          : <span className="help">Not installed yet.</span>}
        <button className="btn primary" onClick={install} disabled={busy}>
          {busy ? "Installing…" : st?.installed ? "Reinstall / update" : "＋ Install as app"}
        </button>
      </div>
    </div>
  );
}

export default function Settings() {
  const [sys, setSys] = useState(null);
  const [card, setCard] = useState(null);
  const [tab, setTab] = useTab("settings", "hardware");
  useEffect(() => { api("/system").then(setSys).catch(() => {}); }, []);
  if (!sys) return <p className="page-sub">Assessing your hardware…</p>;
  const hw = sys.hardware;
  const a = sys.assessment;
  return (
    <>
      <div className="page-head">
        <div>
          <h1 className="page-title">Settings & Hardware</h1>
          <p className="page-sub">What this PC can run, and how to get the most out of it</p>
        </div>
      </div>

      <Tabs active={tab} onChange={setTab} tabs={[
        { key: "hardware", label: "🖥️ Hardware" },
        { key: "installed", label: "✅ Installed", badge: a.installed.length },
        { key: "recommend", label: "🏆 Recommendations" },
        { key: "image", label: "🎨 Image models" },
      ]} />

      {tab === "hardware" && <>
      <div className="card section-card">
        <h2>🖥️ This machine</h2>
        <div className="spec-grid" style={{ marginTop: 10 }}>
          <div className="spec-tile"><div className="k">CPU</div>
            <div className="v">{hw.cores} threads</div><div className="d">{hw.cpu}</div></div>
          <div className="spec-tile"><div className="k">RAM</div>
            <div className="v">{hw.ram_total_gb} GB</div>
            <div className="d">{hw.ram_available_gb} GB available now</div></div>
          <div className="spec-tile"><div className="k">GPU</div>
            <div className="v">{hw.gpu ? (hw.gpu.vram_total_gb ? `${hw.gpu.vram_total_gb} GB VRAM` : "detected") : "none"}</div>
            <div className="d">{hw.gpu ? hw.gpu.name : "CPU-only inference"}</div></div>
          <div className="spec-tile"><div className="k">Disk free</div>
            <div className="v">{hw.disk_free_gb} GB</div><div className="d">{hw.os}</div></div>
        </div>
        <ul className="note-list">
          {a.notes.map((n, i) => <li key={i}>{n}</li>)}
        </ul>
      </div>

      <div className="card section-card">
        <h2>⚡ Parallel agents</h2>
        <div className="sub">
          Teams with the “Run agents in parallel” toggle use up to this many concurrent
          model calls; everything else runs one call at a time.
        </div>
        <div className="spec-grid">
          <div className="spec-tile">
            <div className="k">Recommended max</div>
            <div className="v">×{a.parallel.capacity}</div>
            <div className="d">{a.parallel.reason}</div>
          </div>
        </div>
      </div>

      <FreeMemory />
      <DesktopAppCard />
      </>}

      {tab === "installed" && (
      <div className="card section-card">
        <h2>✅ Your installed models</h2>
        <div className="sub">Assessment of every chat model currently available in Ollama.</div>
        {a.installed.length
          ? <AssessTable rows={a.installed} onPick={setCard} />
          : <p className="page-sub">No models installed yet — see the Recommendations tab and the Setup page.</p>}
      </div>
      )}

      {tab === "recommend" && <>
      <div className="card section-card">
        <h2>🏆 Suggested dream team for this PC</h2>
        <div className="sub">
          The top-tier model for each job, picked from the live catalog: the most
          popular family in each category, at the largest size that runs comfortably
          on your hardware. Install the missing ones and assign them to your agents.
        </div>
        <CatalogTable dreamOnly />
      </div>

      <div className="card section-card">
        <h2>🧭 Every model that can run on this PC</h2>
        <div className="sub">
          The full Ollama library, checked against your hardware. The list updates
          itself from ollama.com (plain parsing, no AI) and can be refreshed any time.
          Install downloads the model straight into your chosen provider.
        </div>
        <CatalogTable />
      </div>
      </>}

      {tab === "image" && <ImageModels />}
      {card && <ModelCard name={card} onClose={() => setCard(null)} />}
    </>
  );
}
