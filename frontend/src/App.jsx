import React, { createContext, useContext, useEffect, useState } from "react";
import { api } from "./lib/api.js";
import Teams from "./pages/Teams.jsx";
import TeamPage from "./pages/TeamPage.jsx";
import Runs from "./pages/Runs.jsx";
import RunDetail from "./pages/RunDetail.jsx";
import Models from "./pages/Models.jsx";
import Personas from "./pages/Personas.jsx";
import Setup from "./pages/Setup.jsx";
import Settings from "./pages/Settings.jsx";
import Toolbox from "./pages/Toolbox.jsx";
import FlowEditor from "./pages/FlowEditor.jsx";
import Chat from "./pages/Chat.jsx";
import Knowledge from "./pages/Knowledge.jsx";
import PixelStudio from "./pages/PixelStudio.jsx";
import HelpAssistant from "./components/HelpAssistant.jsx";

export const AppCtx = createContext(null);
export const useApp = () => useContext(AppCtx);

function useHashRoute() {
  const [hash, setHash] = useState(location.hash || "#/teams");
  useEffect(() => {
    const fn = () => setHash(location.hash || "#/teams");
    window.addEventListener("hashchange", fn);
    return () => window.removeEventListener("hashchange", fn);
  }, []);
  const [, page = "teams", id] = hash.split("/");
  return { page, id: id ? decodeURIComponent(id) : null };
}

const NAV = [
  ["teams", "🎛️", "Studio"],
  ["chat", "💬", "Chat"],
  ["runs", "🗂️", "Runs"],
  ["knowledge", "📚", "Knowledge"],
  ["personas", "🎭", "Personas"],
  ["toolbox", "🧰", "Skills & Tools"],
  ["models", "🧠", "Models"],
  ["setup", "📦", "Setup"],
  ["settings", "⚙️", "Settings"],
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
  const firstStarted = React.useRef(null);

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

  const active = ["team", "flow", "pixel"].includes(route.page) ? "teams" : route.page === "run" ? "runs" : route.page;

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
  if (route.page === "teams") view = <Teams />;
  else if (route.page === "team" && route.id) view = <TeamPage teamId={+route.id} key={route.id} />;
  else if (route.page === "runs") view = <Runs />;
  else if (route.page === "run" && route.id) view = <RunDetail runId={+route.id} key={route.id} />;
  else if (route.page === "models") view = <Models />;
  else if (route.page === "personas") view = <Personas />;
  else if (route.page === "setup") view = <Setup />;
  else if (route.page === "settings") view = <Settings />;
  else if (route.page === "toolbox") view = <Toolbox />;
  else if (route.page === "chat") view = <Chat personaId={route.id ? +route.id : null} key={route.id || "chat"} />;
  else if (route.page === "knowledge") view = <Knowledge />;
  else view = <Teams />;

  return (
    <AppCtx.Provider value={{ models, tools, skills, paramSpecs, health, reloadCatalogs, theme }}>
      <div id="app">
        <aside className="sidebar">
          <div className="logo">
            <div className="logo-mark">🧩</div>
            <div>
              <div className="logo-name">Agents Studio</div>
              <div className="logo-sub">LangGraph · local</div>
            </div>
          </div>
          <nav className="nav">
            {NAV.map(([key, ico, label]) => (
              <a key={key} href={`#/${key}`} className={active === key ? "active" : ""}>
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
              className="btn ghost theme-toggle"
              title={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
              onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
            >
              {theme === "dark" ? "☀️" : "🌙"}
              <span className="txt">{theme === "dark" ? "Light mode" : "Dark mode"}</span>
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
