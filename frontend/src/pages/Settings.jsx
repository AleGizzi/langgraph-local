import React, { useEffect, useState } from "react";
import { api } from "../lib/api.js";
import CatalogTable from "../components/CatalogTable.jsx";

function AssessTable({ rows, showInstalled }) {
  return (
    <table className="assess">
      <thead>
        <tr>
          <th>Model</th><th>Size</th><th>Est. speed</th><th>Verdict</th>
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
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export default function Settings() {
  const [sys, setSys] = useState(null);
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

      <div className="card section-card">
        <h2>✅ Your installed models</h2>
        <div className="sub">Assessment of every chat model currently available in Ollama.</div>
        {a.installed.length
          ? <AssessTable rows={a.installed} />
          : <p className="page-sub">No models installed yet — see the catalog below and the Setup page.</p>}
      </div>

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
    </>
  );
}
