import React, { useEffect, useRef, useState } from "react";
import { api, toast } from "../lib/api.js";
import Tabs, { useTab } from "../components/Tabs.jsx";

function InstallWizard({ provider, info, docker, onInstalled }) {
  const [st, setSt] = useState(null);
  const timer = useRef(null);
  const key = `setup::${provider}`;
  const active = st && !st.done;

  useEffect(() => {
    const tick = async () => {
      try {
        const all = await api("/install/status");
        const cur = all[key];
        setSt(cur || null);
        if (cur?.done) {
          clearInterval(timer.current);
          if (cur.status?.startsWith("installed")) onInstalled?.();
        }
      } catch { /* server busy */ }
    };
    tick();
    return () => clearInterval(timer.current);
  }, []);

  const start = async () => {
    try {
      const r = await api("/setup/install", { method: "POST", body: { provider } });
      if (r.ok === false) { toast(r.error, true); return; }
      setSt({ done: false, progress: 0, status: "starting" });
      timer.current = setInterval(async () => {
        try {
          const all = await api("/install/status");
          const cur = all[key];
          if (cur) setSt(cur);
          if (cur?.done) {
            clearInterval(timer.current);
            if (cur.status?.startsWith("installed")) {
              toast(`${info.name} installed and running`);
              onInstalled?.();
            }
          }
        } catch { /* retry next tick */ }
      }, 1500);
    } catch (e) { toast(e.message, true); }
  };

  if (docker) {
    return (
      <div className="wizard-box" style={{ marginTop: 12 }}>
        <div className="wizard-head">🐳 Running in Docker</div>
        <div className="help">
          {provider === "ollama"
            ? "Ollama is provided by the bundled service in docker-compose — nothing to install. Pull models from the Settings page."
            : "LM Studio is a desktop app and does not run inside Docker. Use the bundled Ollama service instead."}
        </div>
      </div>
    );
  }
  if (info.running) return null;

  return (
    <div className="wizard-box" style={{ marginTop: 12 }}>
      <div className="wizard-head">
        🚀 First time here?
        <span className="help">
          {provider === "ollama"
            ? "One click installs Ollama for your user (no admin password) and starts it."
            : "One click downloads the LM Studio app; you launch it once to finish."}
        </span>
      </div>
      {active ? (
        <div>
          <div className="install-progress" style={{ maxWidth: 420 }} title={st.status}>
            <div className="install-progress-fill" style={{ width: `${st.progress || 2}%` }} />
            <span>{st.progress ? `${Math.round(st.progress)}%` : "…"}</span>
          </div>
          <div className="param-hint" style={{ marginTop: 6 }}>{st.status}</div>
        </div>
      ) : st?.done && !st.status?.startsWith("installed") ? (
        <div className="param-hint" style={{ color: st.error ? "var(--red)" : "var(--green)" }}>
          {st.error || st.status}
        </div>
      ) : info.installed ? (
        <div className="param-hint">
          {info.name} is installed but not running —{" "}
          {provider === "ollama"
            ? "start it with `systemctl start ollama` or `ollama serve`."
            : "launch the app and start its server from the Developer tab."}
        </div>
      ) : (
        <div>
          <button className="btn primary" onClick={start}>
            {provider === "ollama" ? "⬇ Install Ollama automatically" : "⬇ Download LM Studio"}
          </button>
        </div>
      )}
    </div>
  );
}

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
  const [tab, setTab] = useTab("setup", "ollama");
  const load = () => api("/system").then(setSys).catch(() => {});
  useEffect(() => { load(); }, []);
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
      <Tabs
        tabs={sections.map(([key, info]) => ({
          key, label: <><span className={"dot " + (info.running ? "up" : "down")} /> {info.name}</> }))}
        active={tab} onChange={setTab} />
      {sections.filter(([key]) => key === tab).map(([key, info, guide, blurb]) => (
        <div key={key} className="card section-card">
          <div className="sub">{blurb} · <a href={guide.site} target="_blank" rel="noopener noreferrer">{guide.site}</a></div>
          <h3 style={{ fontSize: 13, margin: "10px 0 6px" }}>On this machine</h3>
          <InstallInfo info={info} />
          <InstallWizard provider={key} info={info} docker={sys.docker} onInstalled={load} />
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
