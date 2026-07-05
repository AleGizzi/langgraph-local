import React, { useEffect, useState } from "react";
import { api } from "../lib/api.js";

function InstallInfo({ info }) {
  const rows = [
    ["Status", info.running
      ? <span className="verdict great">running</span>
      : info.installed
        ? <span className="verdict tight">installed, not running</span>
        : <span className="verdict no">not installed</span>],
    ["API endpoint", <code>{info.url}</code>],
    ["Port", <code>{info.port}</code>],
    info.version && ["Version", info.version],
    info.binary && ["Binary / CLI", <code>{info.binary}</code>],
    info.app && ["Application", <code>{info.app}</code>],
    info.home && ["Home folder", <code>{info.home}</code>],
    info.models_dir && ["Models folder", <code>{info.models_dir}</code>],
    info.models_size_gb != null && ["Models on disk", `${info.models_size_gb} GB`],
    info.service && ["Runs as", info.service],
  ].filter(Boolean);
  return (
    <table className="kv"><tbody>
      {rows.map(([k, v], i) => <tr key={i}><td>{k}</td><td>{v}</td></tr>)}
    </tbody></table>
  );
}

function Guide({ guide }) {
  return (
    <div className="steps">
      {guide.steps.map((s, i) => (
        <div key={i} className="step-item">
          <div className="step-num">{i + 1}</div>
          <div style={{ minWidth: 0, flex: 1 }}>
            {s.text}
            {s.cmd && <span className="cmd">{s.cmd}</span>}
          </div>
        </div>
      ))}
    </div>
  );
}

export default function Setup() {
  const [sys, setSys] = useState(null);
  useEffect(() => { api("/system").then(setSys).catch(() => {}); }, []);
  if (!sys) return <p className="page-sub">Inspecting your system…</p>;
  const { installations, guides } = sys;
  const sections = [
    ["ollama", installations.ollama, guides.ollama,
      "Recommended for this app: simple CLI, runs as a background service, best API support."],
    ["lmstudio", installations.lmstudio, guides.lmstudio,
      "Nice GUI for browsing and chatting with models; exposes an OpenAI-compatible server."],
  ];
  return (
    <>
      <div className="page-head">
        <div>
          <h1 className="page-title">Setup</h1>
          <p className="page-sub">
            Install the local model providers and see how they are configured on this machine
          </p>
        </div>
        <a className="btn" href="#/settings">⚙️ Model recommendations</a>
      </div>
      {sections.map(([key, info, guide, blurb]) => (
        <div key={key} className="card section-card">
          <h2>
            <span className={"dot " + (info.running ? "up" : "down")} />
            {info.name}
          </h2>
          <div className="sub">{blurb} · <a href={guide.site} target="_blank" rel="noopener noreferrer">{guide.site}</a></div>
          <h3 style={{ fontSize: 13, margin: "10px 0 6px" }}>On this machine</h3>
          <InstallInfo info={info} />
          <h3 style={{ fontSize: 13, margin: "16px 0 0" }}>
            {info.installed ? "Install steps (for reference)" : "How to install"}
          </h3>
          <Guide guide={guide} />
        </div>
      ))}
      <div className="card section-card">
        <h2>🔌 Connecting this app</h2>
        <div className="sub">
          Both providers are auto-detected. To point at a different host/port, set the
          environment variables before launching:
        </div>
        <table className="kv"><tbody>
          <tr><td>Ollama</td><td><code>OLLAMA_URL=http://localhost:11434 ./run.sh</code></td></tr>
          <tr><td>LM Studio</td><td><code>LMSTUDIO_URL=http://localhost:1234/v1 ./run.sh</code></td></tr>
        </tbody></table>
      </div>
    </>
  );
}
