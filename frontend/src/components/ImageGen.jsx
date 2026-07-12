import React, { useEffect, useRef, useState } from "react";
import { api, toast } from "../lib/api.js";

export default function ImageGen() {
  const [status, setStatus] = useState(null);
  const [images, setImages] = useState([]);
  const [imageMeta, setImageMeta] = useState({});
  const [prompt, setPrompt] = useState("");
  const [negative, setNegative] = useState("");
  const [aspect, setAspect] = useState("1152*896");
  const [speed, setSpeed] = useState("Extreme Speed");
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState(null);
  const pollRef = useRef(null);

  // --- LoRAs (Fooocus/SDXL style LoRAs from Civitai) ---
  const [lorasOpen, setLorasOpen] = useState(false);
  const [loraQuery, setLoraQuery] = useState("");
  const [loraResults, setLoraResults] = useState([]);
  const [loraSearching, setLoraSearching] = useState(false);
  const [loraError, setLoraError] = useState(null);
  const [localLoras, setLocalLoras] = useState([]);
  const [loraDownloads, setLoraDownloads] = useState({});
  const [selectedLoras, setSelectedLoras] = useState({}); // file_name -> weight
  const loraPollRef = useRef(null);

  // Load initial status and gallery
  useEffect(() => {
    const loadStatus = async () => {
      try {
        const st = await api("/imagegen/status");
        setStatus(st);
        setError(st.error || null);
      } catch (e) {
        toast(e.message, true);
        setError(e.message);
      }
    };

    const loadGallery = async () => {
      try {
        const g = await api("/imagegen/gallery");
        setImages(g.images || []);
        setImageMeta(g.meta || {});
      } catch (e) {
        console.error("Failed to load gallery:", e);
      }
    };

    loadStatus();
    loadGallery();
  }, []);

  // Poll install status while installing
  useEffect(() => {
    const isInstalling = status?.installing;

    if (isInstalling) {
      const tick = async () => {
        try {
          const st = await api("/imagegen/status");
          setStatus(st);
          if (st.error) setError(st.error);
        } catch (e) {
          console.error("Poll error:", e);
        }
      };

      tick();
      pollRef.current = setInterval(tick, 2500);
      return () => clearInterval(pollRef.current);
    }
    return undefined;
  }, [status?.installing]);

  const handleInstall = async () => {
    try {
      setError(null);
      const r = await api("/imagegen/install", { method: "POST" });
      if (r.error) {
        toast(r.error, true);
        setError(r.error);
      } else {
        toast("Installing Fooocus… this may take a few minutes.");
        setStatus((s) => ({ ...s, installing: true, install: { status: "starting", progress: 0 } }));
      }
    } catch (e) {
      toast(e.message, true);
      setError(e.message);
    }
  };

  const handleStart = async () => {
    try {
      setError(null);
      const r = await api("/imagegen/start", { method: "POST" });
      if (r.error) {
        toast(r.error, true);
        setError(r.error);
      } else {
        toast("Starting image server… wait ~30-60 seconds.");
        setStatus((s) => ({ ...s, running: true }));
      }
    } catch (e) {
      toast(e.message, true);
      setError(e.message);
    }
  };

  const handleGenerate = async () => {
    if (!prompt.trim()) {
      toast("Please enter a prompt", true);
      return;
    }

    try {
      setError(null);
      setGenerating(true);
      const loraPayload = Object.entries(selectedLoras).map(([file_name, weight]) => ({
        file_name, weight: Number(weight) || 0.8,
      }));
      const r = await api("/imagegen/generate", {
        method: "POST",
        body: { prompt, negative, aspect, performance: speed,
                ...(loraPayload.length ? { loras: loraPayload } : {}) },
      });

      if (r.error) {
        toast(r.error, true);
        setError(r.error);
      } else {
        const newImages = r.images || [];
        setImages((old) => [...newImages, ...old]);
        toast("Images generated successfully!");
        setPrompt("");
        setNegative("");
      }
    } catch (e) {
      toast(e.message, true);
      setError(e.message);
    } finally {
      setGenerating(false);
    }
  };

  const handleStop = async () => {
    try {
      await api("/imagegen/stop", { method: "POST" });
      setStatus((s) => ({ ...s, running: false }));
      toast("Server stopped.");
    } catch (e) {
      toast(e.message, true);
    }
  };

  // --- LoRAs ---

  const loadLoras = async () => {
    try {
      const r = await api("/loras");
      setLocalLoras(r.local || []);
      setLoraDownloads(r.downloads || {});
    } catch (e) {
      console.error("Failed to load loras:", e);
    }
  };

  useEffect(() => {
    if (status?.running) loadLoras();
  }, [status?.running]);

  // Poll while any download is in flight.
  useEffect(() => {
    const anyActive = Object.values(loraDownloads).some((d) => !d.done);
    if (anyActive) {
      loraPollRef.current = setInterval(loadLoras, 2000);
      return () => clearInterval(loraPollRef.current);
    }
    return undefined;
  }, [loraDownloads]);

  const handleLoraSearch = async () => {
    if (!loraQuery.trim()) return;
    try {
      setLoraSearching(true);
      setLoraError(null);
      const r = await api(`/loras/search?q=${encodeURIComponent(loraQuery)}&base=SDXL`);
      if (r.error) {
        setLoraError(r.error);
        setLoraResults([]);
      } else {
        setLoraResults(r.results || []);
      }
    } catch (e) {
      setLoraError(e.message);
      toast(e.message, true);
    } finally {
      setLoraSearching(false);
    }
  };

  const handleLoraDownload = async (result) => {
    try {
      const r = await api("/loras/download", {
        method: "POST",
        body: { download_url: result.download_url, file_name: result.file_name },
      });
      if (r.error) {
        toast(r.error, true);
      } else {
        toast(`Downloading ${result.file_name}…`);
        setLoraDownloads((d) => ({
          ...d,
          [result.file_name]: { file_name: result.file_name, status: "starting", progress: 0, done: false },
        }));
      }
    } catch (e) {
      toast(e.message, true);
    }
  };

  const toggleLoraSelected = (file_name) => {
    setSelectedLoras((sel) => {
      const next = { ...sel };
      if (file_name in next) delete next[file_name];
      else next[file_name] = 0.8;
      return next;
    });
  };

  const setLoraWeight = (file_name, weight) => {
    setSelectedLoras((sel) => (file_name in sel ? { ...sel, [file_name]: weight } : sel));
  };

  if (!status) return <div className="card section-card"><p className="page-sub">Loading…</p></div>;

  const { installed, running, installing, error: statusError, install } = status;
  const displayError = error || statusError;
  const selectedLoraCount = Object.keys(selectedLoras).length;

  return (
    <div className="card section-card">
      <h2>🎨 Image generation (Fooocus)</h2>
      <div className="sub">Local image generation on your GPU</div>

      {displayError && (
        <div className="param-hint" style={{ color: "var(--red)", marginBottom: 12 }}>
          Error: {displayError}
        </div>
      )}

      {!installed && !installing && (
        <div>
          <button className="btn primary" onClick={handleInstall} style={{ marginBottom: 8 }}>
            ⬇ Install Fooocus
          </button>
          <div className="help" style={{ marginTop: 8 }}>
            ⚠️ Large download (~3-5 GB). On a 4 GB GPU, generation will be slow (low-VRAM mode).
          </div>
        </div>
      )}

      {installing && (
        <div>
          <div className="install-progress" title={install?.status || "installing"}>
            <div className="install-progress-fill" style={{ width: `${install?.progress || 2}%` }} />
            <span>{install?.progress ? `${Math.round(install.progress)}%` : "…"}</span>
          </div>
          <div className="page-sub" style={{ marginTop: 8 }}>
            {install?.status || "Installing…"}
          </div>
        </div>
      )}

      {installed && !running && !installing && (
        <div>
          <button className="btn primary" onClick={handleStart} style={{ marginBottom: 8 }}>
            ▶ Start image server
          </button>
          <div className="help" style={{ marginTop: 8 }}>
            Takes ~30-60 seconds to load the model. Be patient.
          </div>
        </div>
      )}

      {running && (
        <div>
          <div style={{ marginBottom: 16 }}>
            <label style={{ display: "block", marginBottom: 4, fontWeight: 500 }}>Prompt</label>
            <textarea
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              disabled={generating}
              placeholder="Describe the image you want to generate…"
              style={{
                width: "100%",
                minHeight: 80,
                padding: 8,
                border: "1px solid var(--border)",
                borderRadius: 6,
                fontFamily: "inherit",
                fontSize: 13,
                resize: "vertical",
                opacity: generating ? 0.6 : 1,
              }}
            />
          </div>

          <div style={{ marginBottom: 16 }}>
            <label style={{ display: "block", marginBottom: 4, fontWeight: 500 }}>Negative prompt (optional)</label>
            <input
              type="text"
              value={negative}
              onChange={(e) => setNegative(e.target.value)}
              disabled={generating}
              placeholder="What to avoid in the image…"
              style={{
                width: "100%",
                padding: 8,
                border: "1px solid var(--border)",
                borderRadius: 6,
                fontSize: 13,
                opacity: generating ? 0.6 : 1,
              }}
            />
          </div>

          <div style={{ marginBottom: 16, display: "flex", gap: 12, alignItems: "flex-end" }}>
            <div style={{ flex: 1 }}>
              <label style={{ display: "block", marginBottom: 4, fontWeight: 500 }}>Aspect ratio</label>
              <select
                value={aspect}
                onChange={(e) => setAspect(e.target.value)}
                disabled={generating}
                style={{
                  width: "100%",
                  padding: "8px 6px",
                  border: "1px solid var(--border)",
                  borderRadius: 6,
                  fontSize: 13,
                  opacity: generating ? 0.6 : 1,
                }}
              >
                <option value="1152*896">Landscape (1152x896)</option>
                <option value="896*1152">Portrait (896x1152)</option>
                <option value="1024*1024">Square (1024x1024)</option>
              </select>
            </div>
            <div style={{ flex: 1 }}>
              <label style={{ display: "block", marginBottom: 4, fontWeight: 500 }}>Speed / quality</label>
              <select
                value={speed}
                onChange={(e) => setSpeed(e.target.value)}
                disabled={generating}
                style={{
                  width: "100%",
                  padding: "8px 6px",
                  border: "1px solid var(--border)",
                  borderRadius: 6,
                  fontSize: 13,
                  opacity: generating ? 0.6 : 1,
                }}
              >
                <option value="Extreme Speed">Extreme Speed (~8 steps, fastest)</option>
                <option value="Lightning">Lightning (~4 steps)</option>
                <option value="Speed">Speed (30 steps, slow)</option>
                <option value="Quality">Quality (60 steps, slowest)</option>
              </select>
            </div>
            <div style={{ display: "flex", gap: 6 }}>
              <button
                className="btn primary"
                onClick={handleGenerate}
                disabled={generating}
                style={{ opacity: generating ? 0.7 : 1, minWidth: 120 }}
              >
                {generating ? "Generating…" : "✨ Generate"}
              </button>
              <button
                className="btn sm"
                onClick={handleStop}
                style={{ minWidth: 60 }}
              >
                Stop
              </button>
            </div>
          </div>

          <div className="page-sub" style={{ marginBottom: 12 }}>
            {generating
              ? "Generating… on a low-VRAM GPU this takes minutes even in fast mode — leave it running."
              : "Tip: on a 4 GB GPU use Extreme Speed / Lightning; the 30-60 step modes can take ~40 min per image."}
          </div>

          <div style={{ borderTop: "1px solid var(--border)", paddingTop: 10 }}>
            <button
              className="btn sm ghost"
              onClick={() => setLorasOpen((o) => !o)}
              style={{ padding: "4px 8px" }}
            >
              {lorasOpen ? "▾" : "▸"} 🎨 Style LoRAs
              {selectedLoraCount > 0 ? ` (${selectedLoraCount} selected)` : ""}
            </button>

            {lorasOpen && (
              <div style={{ marginTop: 10 }}>
                <div style={{ display: "flex", gap: 6, marginBottom: 6 }}>
                  <input
                    type="text"
                    value={loraQuery}
                    onChange={(e) => setLoraQuery(e.target.value)}
                    onKeyDown={(e) => e.key === "Enter" && handleLoraSearch()}
                    placeholder='Search Civitai, e.g. "GBA pokemon sprite"…'
                    style={{
                      flex: 1, padding: "6px 8px", border: "1px solid var(--border)",
                      borderRadius: 6, fontSize: 13,
                    }}
                  />
                  <button className="btn sm" onClick={handleLoraSearch} disabled={loraSearching}>
                    {loraSearching ? "Searching…" : "Search"}
                  </button>
                </div>
                <div className="param-hint" style={{ marginBottom: 8 }}>
                  Only SDXL/Pony LoRAs work on this JuggernautXL (SDXL) base — SD 1.5 LoRAs
                  download and load without error but visibly do nothing. Some Civitai files
                  require an account; set <code>CIVITAI_API_KEY</code> on the server to unlock those.
                </div>

                {loraError && (
                  <div className="param-hint" style={{ color: "var(--red)", marginBottom: 8 }}>
                    Error: {loraError}
                  </div>
                )}

                {loraResults.length > 0 && (
                  <div style={{
                    display: "flex", flexDirection: "column", gap: 6, marginBottom: 14,
                    maxHeight: 260, overflowY: "auto",
                  }}>
                    {loraResults.map((r) => {
                      const dl = loraDownloads[r.file_name];
                      const downloading = dl && !dl.done;
                      const already = localLoras.some((l) => l.file_name === r.file_name);
                      return (
                        <div
                          key={`${r.id}-${r.file_name}`}
                          style={{
                            display: "flex", alignItems: "center", gap: 8, padding: "6px 8px",
                            border: "1px solid var(--border)", borderRadius: 7,
                          }}
                        >
                          <div style={{ flex: 1, minWidth: 0 }}>
                            <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
                              <span style={{ fontWeight: 600, fontSize: 12.5 }}>{r.name}</span>
                              <span
                                className="chip"
                                style={r.compatible
                                  ? { background: "var(--green-soft)", color: "var(--green)", borderColor: "transparent" }
                                  : { background: "var(--red-soft)", color: "var(--red)", borderColor: "transparent" }}
                              >
                                {r.compatible ? r.base_model : `incompatible (${r.base_model})`}
                              </span>
                              <span className="param-hint" style={{ margin: 0 }}>
                                ⬇ {typeof r.downloads === "number" ? r.downloads.toLocaleString() : r.downloads}
                              </span>
                            </div>
                            {r.description && (
                              <div className="param-hint" style={{ marginTop: 2 }}>{r.description}</div>
                            )}
                          </div>
                          {already ? (
                            <span className="param-hint" style={{ margin: 0, color: "var(--green)" }}>✓ installed</span>
                          ) : downloading ? (
                            <div className="install-progress" style={{ minWidth: 90 }} title={dl.status}>
                              <div className="install-progress-fill" style={{ width: `${dl.progress || 2}%` }} />
                              <span>{dl.progress ? `${Math.round(dl.progress)}%` : "…"}</span>
                            </div>
                          ) : (
                            <button className="btn sm" onClick={() => handleLoraDownload(r)}>⬇</button>
                          )}
                        </div>
                      );
                    })}
                  </div>
                )}

                <div style={{ fontWeight: 600, fontSize: 12.5, marginBottom: 6 }}>Installed LoRAs</div>
                {localLoras.length === 0 ? (
                  <div className="param-hint">None yet — search above and download one.</div>
                ) : (
                  <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
                    {localLoras.map((l) => (
                      <div key={l.file_name} style={{ display: "flex", alignItems: "center", gap: 8 }}>
                        <input
                          type="checkbox"
                          checked={l.file_name in selectedLoras}
                          onChange={() => toggleLoraSelected(l.file_name)}
                        />
                        <span style={{ fontSize: 12.5, flex: 1 }}>{l.file_name}</span>
                        <span className="param-hint" style={{ margin: 0 }}>{l.size_mb} MB</span>
                        <input
                          type="number"
                          min={0.1}
                          max={2}
                          step={0.1}
                          value={selectedLoras[l.file_name] ?? 0.8}
                          disabled={!(l.file_name in selectedLoras)}
                          onChange={(e) => setLoraWeight(l.file_name, e.target.value)}
                          style={{
                            width: 56, padding: "3px 5px", border: "1px solid var(--border)",
                            borderRadius: 5, fontSize: 12,
                          }}
                        />
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      )}

      {images.length > 0 && (
        <div style={{ marginTop: 20 }}>
          <h3 style={{ marginBottom: 12 }}>Gallery</h3>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))",
              gap: 12,
            }}
          >
            {images.map((img, idx) => (
              <figure key={idx} style={{ margin: 0 }}>
                <img
                  src={`/api/imagegen/images/${img}`}
                  alt={imageMeta[img]?.prompt || `Generated ${idx}`}
                  title={imageMeta[img]?.prompt
                    ? `${imageMeta[img].prompt}\n— ${imageMeta[img].performance || ""}`
                      + (imageMeta[img].loras?.length
                        ? ` · LoRA: ${imageMeta[img].loras.map((l) => l.file_name).join(", ")}` : "")
                    : "prompt unknown (generated before tracking)"}
                  onClick={() => window.open(`/api/imagegen/images/${img}`, "_blank")}
                  style={{
                    width: "100%",
                    height: 200,
                    objectFit: "cover",
                    borderRadius: 8,
                    cursor: "pointer",
                    transition: "transform 0.2s",
                  }}
                  onMouseEnter={(e) => (e.target.style.transform = "scale(1.05)")}
                  onMouseLeave={(e) => (e.target.style.transform = "scale(1)")}
                />
                {imageMeta[img]?.prompt && (
                  <figcaption className="param-hint" style={{
                    whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                    {imageMeta[img].prompt}
                  </figcaption>
                )}
              </figure>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
