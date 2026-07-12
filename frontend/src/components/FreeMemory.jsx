import React, { useEffect, useState } from "react";
import { api, toast } from "../lib/api.js";

/* Settings → Free memory: a live snapshot of what is eating RAM, one-click
 * actions for the parts this app controls, and OS-level steps for the rest. */

const bar = (used, total) => Math.min(100, Math.round((used / (total || 1)) * 100));

const OS_STEPS = [
  {
    title: "Close the big desktop apps",
    body: "Browsers and editors are usually the biggest non-model consumers — the table above names the real culprits on your machine. A browser with many tabs can easily hold several GB.",
    cmd: null,
  },
  {
    title: "Check what else is running",
    body: "See the top memory users at any time:",
    cmd: "ps -eo pid,comm,rss --sort=-rss | head -15",
  },
  {
    title: "Drop the kernel page cache (safe, instant)",
    body: "Cached file data is reclaimed automatically under pressure, so this is rarely needed — but it makes 'available' jump immediately:",
    cmd: "sudo sync && sudo sysctl -w vm.drop_caches=3",
  },
  {
    title: "Give Ollama a shorter keep-alive",
    body: "By default Ollama keeps a model in RAM for 5 minutes after use. Shorten it so memory returns sooner (Pop!_OS/Ubuntu use systemd):",
    cmd: "sudo systemctl edit ollama\n# add:\n[Service]\nEnvironment=\"OLLAMA_KEEP_ALIVE=30s\"\n\nsudo systemctl restart ollama",
  },
  {
    title: "Let one model use more of the machine",
    body: "Ollama can also be told to keep only one model resident at a time (avoids two big models coexisting):",
    cmd: "sudo systemctl edit ollama\n# add:\n[Service]\nEnvironment=\"OLLAMA_MAX_LOADED_MODELS=1\"\n\nsudo systemctl restart ollama",
  },
  {
    title: "Add zram / swap as a safety net (Pop!_OS)",
    body: "Swap won't make a model fast, but it prevents the OOM killer from killing a run that briefly overshoots. Pop!_OS ships with a swapfile; zram compresses RAM instead of hitting disk:",
    cmd: "sudo apt install zram-config   # then reboot\nfree -h                        # verify",
  },
  {
    title: "Log out of the desktop session (last resort)",
    body: "The GNOME session itself (plus extensions) can hold 1–2 GB. Running the app and Ollama from a TTY (Ctrl+Alt+F3) frees that for the model.",
    cmd: null,
  },
];

export default function FreeMemory() {
  const [mem, setMem] = useState(null);
  const [busy, setBusy] = useState(false);
  const [guideOpen, setGuideOpen] = useState(false);

  const load = () => api("/system/memory").then(setMem).catch(() => {});
  useEffect(() => {
    load();
    const t = setInterval(load, 5000);
    return () => clearInterval(t);
  }, []);

  const freeNow = async (opts) => {
    setBusy(true);
    try {
      const r = await api("/system/free-memory", { method: "POST", body: opts });
      setMem(r.after);
      const freed = r.freed_gb;
      toast(freed > 0.2
        ? `Freed ${freed} GB — ${r.actions.join(", ") || "nothing to do"}`
        : (r.actions.length ? r.actions.join(", ") : "Nothing to free right now"));
    } catch (e) { toast(e.message, true); }
    setBusy(false);
  };

  if (!mem) return null;
  const used = +(mem.total_gb - mem.available_gb).toFixed(1);

  return (
    <div className="card section-card">
      <h2>🧹 Free memory (run bigger models)</h2>
      <div className="sub">
        Live view of what's using RAM right now, what this app can release
        instantly, and how to reclaim the rest on Linux / Pop!_OS.
      </div>

      <div className="mem-bar" title={`${used} GB used of ${mem.total_gb} GB`}>
        <div className="mem-fill" style={{ width: `${bar(used, mem.total_gb)}%` }} />
        <div className="mem-fill freeable"
          style={{ width: `${bar(mem.freeable_gb, mem.total_gb)}%`,
                   left: `${bar(used - mem.freeable_gb, mem.total_gb)}%` }} />
      </div>
      <div className="spec-grid" style={{ marginTop: 12 }}>
        <div className="spec-tile">
          <div className="k">Available now</div>
          <div className="v">{mem.available_gb} GB</div>
          <div className="d">of {mem.total_gb} GB total</div>
        </div>
        <div className="spec-tile">
          <div className="k">App can free</div>
          <div className="v" style={{ color: "var(--green)" }}>{mem.freeable_gb} GB</div>
          <div className="d">loaded models + image server</div>
        </div>
        <div className="spec-tile">
          <div className="k">Biggest model that fits</div>
          <div className="v">~{mem.largest_model_fits_gb} GB</div>
          <div className="d">after freeing, keeping headroom for the OS</div>
        </div>
        <div className="spec-tile">
          <div className="k">Swap used</div>
          <div className="v">{mem.swap_used_gb} GB</div>
          <div className="d">{mem.swap_total_gb} GB total · {mem.cached_gb} GB cached</div>
        </div>
      </div>

      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", margin: "14px 0 6px" }}>
        <button className="btn primary" disabled={busy || mem.freeable_gb <= 0}
          onClick={() => freeNow({ unload_models: true, stop_image_server: true })}>
          {busy ? "Freeing…" : `🧹 Free ${mem.freeable_gb} GB now`}
        </button>
        <button className="btn" disabled={busy || !mem.ollama_loaded.length}
          onClick={() => freeNow({ unload_models: true, stop_image_server: false })}>
          Unload {mem.ollama_loaded.length} model{mem.ollama_loaded.length === 1 ? "" : "s"}
        </button>
        <button className="btn" disabled={busy || !mem.image_server.running}
          onClick={() => freeNow({ unload_models: false, stop_image_server: true })}>
          Stop image server{mem.image_server.running ? ` (${mem.image_server.rss_gb} GB)` : ""}
        </button>
      </div>
      <div className="help">
        Unloading is safe — models reload on next use (a few seconds). Stopping the
        image server also gives the GPU back to Ollama.
      </div>

      {(mem.ollama_loaded.length > 0 || mem.image_server.running) && (
        <table className="assess" style={{ marginTop: 12 }}>
          <thead><tr><th>Held by this app</th><th>Memory</th><th>Note</th></tr></thead>
          <tbody>
            {mem.ollama_loaded.map((m) => (
              <tr key={m.name}>
                <td className="mono">{m.name}</td>
                <td>{m.size_gb} GB</td>
                <td className="param-hint">loaded in Ollama · {m.processor || ""}</td>
              </tr>
            ))}
            {mem.image_server.running && (
              <tr>
                <td className="mono">Fooocus image server</td>
                <td>{mem.image_server.rss_gb} GB</td>
                <td className="param-hint">also holds the GPU — makes chat/runs much slower</td>
              </tr>
            )}
          </tbody>
        </table>
      )}

      <h3 style={{ fontSize: 13, margin: "18px 0 6px" }}>Top memory users on this machine</h3>
      <table className="assess">
        <thead><tr><th>Process</th><th>PID</th><th>Memory</th></tr></thead>
        <tbody>
          {mem.top_processes.map((p) => (
            <tr key={p.pid}>
              <td className="mono">{p.name}</td>
              <td className="param-hint">{p.pid}</td>
              <td>{p.rss_gb} GB</td>
            </tr>
          ))}
        </tbody>
      </table>

      <div className="collapse-head" style={{ marginTop: 14 }}
        onClick={() => setGuideOpen(!guideOpen)}>
        <span>{guideOpen ? "▾" : "▸"}</span> 🐧 Free more memory on Linux / Pop!_OS
        <span className="chip">{OS_STEPS.length} steps</span>
      </div>
      {guideOpen && (
        <div className="steps" style={{ marginTop: 8 }}>
          {OS_STEPS.map((s, i) => (
            <div key={i} className="step-item">
              <div className="step-num">{i + 1}</div>
              <div style={{ flex: 1, minWidth: 0 }}>
                <strong>{s.title}</strong>
                <div className="param-hint" style={{ marginTop: 2 }}>{s.body}</div>
                {s.cmd && <span className="cmd">{s.cmd}</span>}
              </div>
            </div>
          ))}
          <div className="help">
            Rule of thumb: a Q4 model needs about its file size in RAM plus ~2 GB
            for context. With {mem.largest_model_fits_gb} GB free you can run models
            up to roughly that size — see the catalog above for what fits.
          </div>
        </div>
      )}
    </div>
  );
}
