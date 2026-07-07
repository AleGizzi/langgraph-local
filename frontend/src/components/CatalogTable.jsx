import React, { useEffect, useRef, useState } from "react";
import { api, toast } from "../lib/api.js";

function ago(ts) {
  if (!ts) return "never";
  const h = (Date.now() / 1000 - ts) / 3600;
  if (h < 1) return `${Math.max(1, Math.round(h * 60))} min ago`;
  if (h < 48) return `${Math.round(h)} h ago`;
  return `${Math.round(h / 24)} days ago`;
}

export default function CatalogTable({ compact = false, withDreamTeam = false, dreamOnly = false }) {
  const [data, setData] = useState(null);
  const [q, setQ] = useState("");
  const [cat, setCat] = useState("all");
  const [showAll, setShowAll] = useState(false);
  const [target, setTarget] = useState("ollama");
  const [installs, setInstalls] = useState({});
  const pollRef = useRef(null);

  const load = () => api("/catalog").then(setData).catch(() => {});
  useEffect(() => { load(); }, []);

  // Poll install status while anything is active.
  const anyActive = Object.values(installs).some((s) => !s.done);
  useEffect(() => {
    const tick = async () => {
      try {
        const st = await api("/install/status");
        setInstalls(st);
        const justDone = Object.values(st).filter((s) => s.done && s.status === "installed");
        if (justDone.length && !Object.values(installs).some((s) => s.done && s.status === "installed")) {
          load(); // refresh installed flags
        }
      } catch { /* server restarting */ }
    };
    tick();
    if (anyActive) {
      pollRef.current = setInterval(tick, 2500);
      return () => clearInterval(pollRef.current);
    }
    return undefined;
  }, [anyActive]);

  // Poll catalog while a refresh is running.
  useEffect(() => {
    if (!data?.refreshing) return undefined;
    const t = setInterval(load, 4000);
    return () => clearInterval(t);
  }, [data?.refreshing]);

  if (!data) return <p className="page-sub">Loading catalog…</p>;

  const refresh = async () => {
    await api("/catalog/refresh", { method: "POST", body: {} });
    toast("Updating catalog from ollama.com…");
    setTimeout(load, 1500);
  };

  const install = async (m) => {
    try {
      const r = await api("/install", { method: "POST", body: { provider: target, model: m.name } });
      if (r.ok === false) toast(r.error || "Could not start", true);
      else {
        toast(`Installing ${m.name} to ${target === "ollama" ? "Ollama" : "LM Studio"}…`);
        setInstalls((s) => ({ ...s, [`${target}::${m.name}`]: { done: false, progress: 0, status: "starting" } }));
      }
    } catch (e) { toast(e.message, true); }
  };

  const needle = q.trim().toLowerCase();
  let rows = data.models.filter((m) =>
    (cat === "all" || (m.categories || []).includes(cat)) &&
    (!needle ||
      m.name.toLowerCase().includes(needle) ||
      (m.description || "").toLowerCase().includes(needle) ||
      (m.capabilities || []).some((c) => c.toLowerCase().includes(needle))));
  if (cat !== "all") {
    rows = [...rows].sort((a, b) =>
      (a.ranks?.[cat] || 9999) - (b.ranks?.[cat] || 9999) ||
      (b.params_b || 0) - (a.params_b || 0));
  }
  const medal = (m) => {
    if (cat === "all") return null;
    const r = m.ranks?.[cat];
    return r === 1 ? "🥇" : r === 2 ? "🥈" : r === 3 ? "🥉" : null;
  };
  const limit = compact ? 12 : 40;
  const shown = showAll || needle ? rows : rows.slice(0, limit);

  const dreamCard = (t) => {
    const st = installs[`ollama::${t.model}`] || installs[`lmstudio::${t.model}`];
    const active = st && !st.done;
    return (
      <div key={t.category} className="dream-card">
        <div className="dream-role">{t.icon} {t.label}</div>
        <div className="dream-model mono">{t.model}</div>
        <div className="dream-meta">
          {t.size_gb} GB · {t.est_tok_s ? `~${t.est_tok_s} tok/s` : t.image ? t.runner : ""} ·{" "}
          <span className={"verdict " + t.verdict}>{t.verdict}</span>
        </div>
        <div className="param-hint">{t.reason}</div>
        <div style={{ marginTop: 8 }}>
          {t.image ? (
            <a className="btn sm" href="#/settings">🎨 Set up image gen</a>
          ) : t.installed ? <span className="badge-installed">installed</span>
            : active ? (
              <div className="install-progress" title={st.status}>
                <div className="install-progress-fill" style={{ width: `${st.progress || 2}%` }} />
                <span>{st.progress ? `${Math.round(st.progress)}%` : "…"}</span>
              </div>
            ) : (
              <button className="btn sm" onClick={() => install({ name: t.model })}>⬇ Install</button>
            )}
        </div>
      </div>
    );
  };

  if (dreamOnly) {
    return (
      <div className="dream-grid">
        {(data.dream_team || []).map(dreamCard)}
      </div>
    );
  }

  return (
    <div>
      {withDreamTeam && (data.dream_team || []).length > 0 && (
        <div className="dream-grid">
          {(data.dream_team || []).map(dreamCard)}
        </div>
      )}
      <div className="cat-chips">
        <span className={"tool-tag" + (cat === "all" ? " on" : "")}
          onClick={() => setCat("all")}>All</span>
        {Object.entries(data.categories || {}).map(([key, c]) => (
          <span key={key} className={"tool-tag" + (cat === key ? " on" : "")}
            onClick={() => setCat(cat === key ? "all" : key)}>
            {c.icon} {c.label}
          </span>
        ))}
        {cat !== "all" && <span className="help">ranked by family popularity among models that run here — 🥇🥈🥉 mark the top tiers</span>}
      </div>
      <div className="catalog-bar">
        <input type="text" className="catalog-search" placeholder={`Search ${data.summary.total} models…`}
          value={q} onChange={(e) => setQ(e.target.value)} />
        <div className="switch-row" style={{ gap: 6 }}>
          <span className="help">Install to:</span>
          <select value={target} onChange={(e) => setTarget(e.target.value)} style={{ padding: "4px 8px", borderRadius: 7 }}>
            <option value="ollama">Ollama</option>
            <option value="lmstudio">LM Studio (lms)</option>
          </select>
        </div>
        <span className="spacer" style={{ flex: 1 }} />
        <span className="help">
          {data.summary.runnable}/{data.summary.total} runnable here · updated {ago(data.fetched_at)}
          {data.refreshing ? " · refreshing…" : ""}
          {data.error ? ` · last refresh failed: ${data.error}` : ""}
        </span>
        <button className="btn sm" disabled={data.refreshing} onClick={refresh}>
          {data.refreshing ? "⏳ Updating…" : "🔄 Update list"}
        </button>
      </div>
      <div style={{ overflowX: "auto" }}>
        <table className="assess">
          <thead>
            <tr><th>Model</th><th>Size</th><th>Est. speed</th><th>Verdict</th>
              {!compact && <th>Pulls</th>}<th></th></tr>
          </thead>
          <tbody>
            {shown.map((m) => {
              const st = installs[`ollama::${m.name}`] || installs[`lmstudio::${m.name}`];
              const active = st && !st.done;
              return (
                <tr key={m.name}>
                  <td>
                    {medal(m) && <span style={{ marginRight: 5 }}>{medal(m)}</span>}
                    <span className="mono" style={{ fontFamily: "var(--mono)", fontSize: 12.5 }}>{m.name}</span>
                    {(m.categories || []).filter((c) => c !== "general" || m.categories.length === 1).map((c) => (
                      <span key={c} className="chip" style={{ marginLeft: 6 }}
                        title={data.categories?.[c]?.label}>
                        {data.categories?.[c]?.icon} {c}
                      </span>
                    ))}
                    {!compact && m.description && <div className="param-hint" style={{ maxWidth: 460 }}>{m.description}</div>}
                  </td>
                  <td>{m.size_gb ? `${m.size_gb} GB${m.exact ? "" : " ~"}` : "?"}</td>
                  <td>{m.est_tok_s ? `~${m.est_tok_s} tok/s` : "—"}</td>
                  <td><span className={"verdict " + (m.verdict === "unknown" ? "tight" : m.verdict)} title={m.verdict_label}>
                    {m.verdict === "no" ? "won't run" : m.verdict}</span></td>
                  {!compact && <td>{m.pulls_label}</td>}
                  <td style={{ minWidth: 130 }}>
                    {m.installed ? <span className="badge-installed">installed</span>
                      : active ? (
                        <div className="install-progress" title={st.status}>
                          <div className="install-progress-fill" style={{ width: `${st.progress || 2}%` }} />
                          <span>{st.progress ? `${Math.round(st.progress)}%` : "…"}</span>
                        </div>
                      ) : st && st.status === "error" ? (
                        <span className="verdict no" title={st.error}>failed</span>
                      ) : (
                        <button className="btn sm" disabled={m.verdict === "no"}
                          title={m.verdict === "no" ? "Not enough RAM on this machine" : `Download with ${target}`}
                          onClick={() => install(m)}>⬇ Install</button>
                      )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {!showAll && !needle && rows.length > limit && (
        <button className="btn sm" style={{ marginTop: 10 }} onClick={() => setShowAll(true)}>
          Show all {rows.length} models
        </button>
      )}
    </div>
  );
}
