import React, { createContext, useContext, useEffect, useState } from "react";
import { api } from "./lib/api.js";
import Agents from "./pages/Agents.jsx";
import TeamPage from "./pages/TeamPage.jsx";
import Runs from "./pages/Runs.jsx";
import RunDetail from "./pages/RunDetail.jsx";
import Models from "./pages/Models.jsx";
import Setup from "./pages/Setup.jsx";
import Settings from "./pages/Settings.jsx";
import Toolbox from "./pages/Toolbox.jsx";
import FlowEditor from "./pages/FlowEditor.jsx";
import Chat from "./pages/Chat.jsx";
import Knowledge from "./pages/Knowledge.jsx";
import Schedules from "./pages/Schedules.jsx";
import Resources from "./pages/Resources.jsx";
import Guide from "./pages/Guide.jsx";
import PixelStudio from "./pages/PixelStudio.jsx";
import HelpAssistant from "./components/HelpAssistant.jsx";
import NotificationBell from "./components/NotificationBell.jsx";
import PixelSprite from "./components/PixelSprite.jsx";

export const AppCtx = createContext(null);
export const useApp = () => useContext(AppCtx);

function useHashRoute() {
  const [hash, setHash] = useState(location.hash || "#/agents");
  useEffect(() => {
    const fn = () => setHash(location.hash || "#/agents");
    window.addEventListener("hashchange", fn);
    return () => window.removeEventListener("hashchange", fn);
  }, []);
  const [, page = "agents", id] = hash.split("/");
  return { page, id: id ? decodeURIComponent(id) : null };
}

const NAV = [
  ["agents", "🎭", "Agents"],
  ["chat", "💬", "Chat"],
  ["runs", "🗂️", "Runs"],
  ["schedules", "⏰", "Schedules"],
  ["resources", "📰", "AI News"],
  ["knowledge", "📚", "Knowledge"],
  ["toolbox", "🧰", "Skills & Tools"],
  ["models", "🧠", "Models"],
  ["setup", "📦", "Setup"],
  ["settings", "⚙️", "Settings"],
  ["guide", "📖", "Guide"],
];

function initialTheme() {
  const saved = localStorage.getItem("theme");
  if (saved === "dark" || saved === "light") return saved;
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export default function App() {
  const route = useHashRoute();
  const [theme, setTheme] = useState(initialTheme);
  const [models, setModels] = useState({ ollama: [], lmstudio: [] });
  const [tools, setTools] = useState({ builtin: [], custom: [] });
  const [skills, setSkills] = useState([]);
  const [paramSpecs, setParamSpecs] = useState([]);
  const [health, setHealth] = useState(null);
  const [staleBundle, setStaleBundle] = useState(false);
  const [collapsed, setCollapsed] = useState(() => localStorage.getItem("sidebar") === "collapsed");
  const firstStarted = React.useRef(null);
  useEffect(() => {
    localStorage.setItem("sidebar", collapsed ? "collapsed" : "expanded");
  }, [collapsed]);

  const reloadCatalogs = () => {
    api("/tools").then(setTools).catch(() => {});
    api("/skills").then(setSkills).catch(() => {});
  };

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("theme", theme);
  }, [theme]);

  useEffect(() => {
    const loadModels = () => api("/models").then(setModels).catch(() => {});
    loadModels();
    api("/params").then(setParamSpecs).catch(() => {});
    reloadCatalogs();
    // Refresh models on the same cadence as health (and on focus) so models
    // pulled from the in-app catalog after mount show up in dropdowns without
    // a hard reload.
    const poll = () => {
      api("/health").then((h) => {
        setHealth(h);
        // Server restarted since this tab loaded → the JS bundle is likely
        // outdated; offer a reload instead of silently running stale code.
        if (h.server_started) {
          if (firstStarted.current === null) firstStarted.current = h.server_started;
          else if (h.server_started !== firstStarted.current) setStaleBundle(true);
        }
      }).catch(() => {});
      loadModels();
    };
    poll();
    const t = setInterval(poll, 15000);
    window.addEventListener("focus", loadModels);
    return () => {
      clearInterval(t);
      window.removeEventListener("focus", loadModels);
    };
  }, []);

  const active = ["team", "flow", "pixel", "teams", "personas"].includes(route.page)
    ? "agents" : route.page === "run" ? "runs" : route.page;

  // Full-viewport pages without the normal page wrapper.
  if (route.page === "flow" && route.id) {
    return (
      <AppCtx.Provider value={{ models, tools, skills, paramSpecs, health, reloadCatalogs, theme }}>
        <FlowEditor teamId={+route.id} key={route.id} />
        <HelpAssistant />
      </AppCtx.Provider>
    );
  }
  if (route.page === "pixel" && route.id) {
    return (
      <AppCtx.Provider value={{ models, tools, skills, paramSpecs, health, reloadCatalogs, theme }}>
        <PixelStudio teamId={+route.id} key={route.id} />
        <HelpAssistant />
      </AppCtx.Provider>
    );
  }

  let view = null;
  if (route.page === "agents") view = <Agents subtab={route.id} />;
  // legacy deep links → the Agents page's tabs
  else if (route.page === "teams") view = <Agents subtab="teams" />;
  else if (route.page === "personas") view = <Agents subtab="personas" />;
  else if (route.page === "team" && route.id) view = <TeamPage teamId={+route.id} key={route.id} />;
  else if (route.page === "runs") view = <Runs />;
  else if (route.page === "run" && route.id) view = <RunDetail runId={+route.id} key={route.id} />;
  else if (route.page === "models") view = <Models />;
  else if (route.page === "setup") view = <Setup />;
  else if (route.page === "settings") view = <Settings />;
  else if (route.page === "toolbox") view = <Toolbox />;
  else if (route.page === "chat") view = <Chat personaId={route.id ? +route.id : null} key={route.id || "chat"} />;
  else if (route.page === "knowledge") view = <Knowledge />;
  else if (route.page === "schedules") view = <Schedules />;
  else if (route.page === "resources") view = <Resources />;
  else if (route.page === "guide") view = <Guide />;
  else view = <Agents />;

  return (
    <AppCtx.Provider value={{ models, tools, skills, paramSpecs, health, reloadCatalogs, theme }}>
      <div id="app" className={collapsed ? "sidebar-collapsed" : ""}>
        <aside className="sidebar">
          <div className="logo">
            <div className="logo-mark"><PixelSprite name="invader" size={20} color="#fff" /></div>
            <div className="logo-text">
              <div className="logo-name">Agents Studio</div>
              <div className="logo-sub">LangGraph · local</div>
            </div>
            <NotificationBell />
            <button className="sidebar-toggle" title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
              aria-label="Toggle sidebar" onClick={() => setCollapsed(!collapsed)}>
              {collapsed ? "»" : "«"}
            </button>
          </div>
          <nav className="nav">
            {NAV.map(([key, ico, label]) => (
              <a key={key} href={`#/${key}`} className={active === key ? "active" : ""}
                data-label={label}>
                <span className="ico">{ico}</span>
                <span className="txt">{label}</span>
              </a>
            ))}
          </nav>
          <div className="sidebar-foot">
            {health && Object.entries(health.providers).map(([name, p]) => (
              <div className="prov" key={name}>
                <span className={"dot " + (p.up ? "up" : "down")} />
                <span className="lbl">
                  {name === "ollama" ? "Ollama" : "LM Studio"} · {p.up ? `${p.models} models` : "offline"}
                </span>
              </div>
            ))}
            <button
              className={"theme-switch" + (theme === "dark" ? " on" : "")}
              role="switch" aria-checked={theme === "dark"}
              title={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
              onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
            >
              <span className="theme-switch-label">☀️</span>
              <span className="theme-switch-track"><span className="theme-switch-knob" /></span>
              <span className="theme-switch-label">🌙</span>
            </button>
          </div>
        </aside>
        <main className="main">
          {staleBundle && (
            <a className="first-run-banner" onClick={() => location.reload()}
              style={{ cursor: "pointer" }}>
              🔄 The app was updated behind this tab — click to reload the new version.
            </a>
          )}
          {health && !health.providers.ollama.up && !health.providers.lmstudio.up && route.page !== "setup" && (
            <a className="first-run-banner" href="#/setup">
              🚀 No local model provider is running — open <strong>Setup</strong> to
              install Ollama with one click.
            </a>
          )}
          {health && health.providers.ollama.up && health.providers.ollama.models === 0 &&
            !health.providers.lmstudio.up && route.page !== "settings" && (
            <a className="first-run-banner" href="#/settings">
              📦 Ollama is running but has no models yet — pick one from the
              <strong> dream team</strong> in Settings.
            </a>
          )}
          <div className={route.page === "chat" ? "page-full" : "page"}>{view}</div>
        </main>
        <HelpAssistant />
      </div>
    </AppCtx.Provider>
  );
}
