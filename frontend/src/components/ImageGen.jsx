import React, { useEffect, useRef, useState } from "react";
import { api, toast, fmtTime } from "../lib/api.js";

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
  const [identifying, setIdentifying] = useState(null);

  // --- modify an existing image ---
  const [modifyOpen, setModifyOpen] = useState(false);
  const [modes, setModes] = useState([]);
  const [mode, setMode] = useState("vary_strong");
  const [source, setSource] = useState(null); // {data|name, label}
  const [cnWeight, setCnWeight] = useState(0.6);
  const [dragOver, setDragOver] = useState(false);
  const loraPollRef = useRef(null);

  // --- prompt assistant ---
  const [assistText, setAssistText] = useState("");
  const [assistRequest, setAssistRequest] = useState("");
  const [assisting, setAssisting] = useState(false);
  const [assistNotes, setAssistNotes] = useState("");
  const [assistModel, setAssistModel] = useState("");
  const [assistError, setAssistError] = useState(null);

  // --- queue ---
  const [queueCount, setQueueCount] = useState(1);
  const [queueJobs, setQueueJobs] = useState([]);
  const [enqueuing, setEnqueuing] = useState(false);
  const queuePollRef = useRef(null);
  const queueDoneRef = useRef(new Set());

  // --- gallery view ---
  const [galleryView, setGalleryView] = useState("grid");

  const loadGallery = async () => {
    try {
      const g = await api("/imagegen/gallery");
      setImages(g.images || []);
      setImageMeta(g.meta || {});
    } catch (e) {
      console.error("Failed to load gallery:", e);
    }
  };

  const loadQueue = async () => {
    try {
      const r = await api("/imagegen/queue");
      const jobs = r.jobs || [];
      const newlyDone = jobs.filter((j) => j.status === "done" && !queueDoneRef.current.has(j.id));
      if (newlyDone.length) {
        newlyDone.forEach((j) => queueDoneRef.current.add(j.id));
        loadGallery();
      }
      setQueueJobs(jobs);
    } catch (e) {
      console.error("Failed to load queue:", e);
    }
  };

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

    loadStatus();
    loadGallery();
    api("/imagegen/modes").then((d) => setModes(d.modes || [])).catch(() => {});
  }, []);

  // Poll the job queue every 3s while anything is queued/running.
  const queueActive = queueJobs.some((j) => j.status === "queued" || j.status === "running");
  useEffect(() => {
    loadQueue();
    if (queueActive) {
      queuePollRef.current = setInterval(loadQueue, 3000);
      return () => clearInterval(queuePollRef.current);
    }
    return undefined;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [queueActive]);

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

  // --- modify an existing image (img2img) ---

  const loraPayload = () => Object.entries(selectedLoras).map(([file_name, weight]) => ({
    file_name, weight: Number(weight) || 0.8,
  }));

  const pickFile = (file) => {
    if (!file) return;
    if (!file.type.startsWith("image/")) { toast("Not an image file", true); return; }
    const reader = new FileReader();
    reader.onload = () => setSource({ data: reader.result, label: file.name });
    reader.readAsDataURL(file);
  };

  const handleModify = async () => {
    if (!source) { toast("Choose an image to modify first", true); return; }
    const spec = modes.find((m) => m.key === mode);
    if (spec?.needs_prompt && !prompt.trim()) {
      toast("This mode uses your prompt — describe the change you want", true);
      return;
    }
    try {
      setError(null);
      setGenerating(true);
      const r = await api("/imagegen/queue", {
        method: "POST",
        body: {
          kind: "modify",
          params: {
            image: source.data ?? source.name,  // data URL, or a gallery filename
            mode, prompt, negative, performance: speed,
            weight: Number(cnWeight) || 0.6,
            ...(loraPayload().length ? { loras: loraPayload() } : {}),
          },
        },
      });
      if (r.error) { toast(r.error, true); setError(r.error); }
      else {
        toast("Queued — modified image will appear in the gallery when done");
        loadQueue();
      }
    } catch (e) {
      toast(e.message, true);
      setError(e.message);
    } finally {
      setGenerating(false);
    }
  };

  const handleGenerate = async () => {
    if (!prompt.trim()) {
      toast("Please enter a prompt", true);
      return;
    }

    try {
      setError(null);
      setEnqueuing(true);
      const n = Math.min(10, Math.max(1, Number(queueCount) || 1));
      const r = await api("/imagegen/queue", {
        method: "POST",
        body: {
          kind: "generate",
          count: n,
          params: { prompt, negative, aspect, performance: speed,
                    ...(loraPayload().length ? { loras: loraPayload() } : {}) },
        },
      });

      if (r.error) {
        toast(r.error, true);
        setError(r.error);
      } else {
        const ids = r.ids || [];
        toast(`Queued ${ids.length} job${ids.length === 1 ? "" : "s"}`);
        loadQueue();
      }
    } catch (e) {
      toast(e.message, true);
      setError(e.message);
    } finally {
      setEnqueuing(false);
    }
  };

  const handleCancelJob = async (id) => {
    try {
      const r = await api(`/imagegen/queue/${id}/cancel`, { method: "POST" });
      if (r.error) toast(r.error, true);
      else { toast("Job cancelled"); loadQueue(); }
    } catch (e) {
      toast(e.message, true);
    }
  };

  const handleClearQueue = async () => {
    try {
      await api("/imagegen/queue/clear", { method: "POST" });
      loadQueue();
    } catch (e) {
      toast(e.message, true);
    }
  };

  const handleAssist = async () => {
    if (!assistText.trim()) return;
    try {
      setAssisting(true);
      setAssistError(null);
      const refining = !!assistRequest;
      const body = refining
        ? { request: assistRequest, current_prompt: prompt, feedback: assistText }
        : { request: assistText };
      const r = await api("/imagegen/prompt-assist", { method: "POST", body });
      if (!r.ok) {
        toast(r.error || "Could not draft a prompt", true);
        setAssistError(r.error || "failed");
        return;
      }
      setPrompt(r.prompt || "");
      setNegative(r.negative || "");
      if (!refining) setAssistRequest(assistText);
      setAssistText("");
      setAssistNotes(r.notes || "");
      setAssistModel(r.model || "");
      const newLoras = Array.isArray(r.loras) ? r.loras : [];
      if (newLoras.length) {
        setSelectedLoras((sel) => {
          const next = { ...sel };
          newLoras.forEach((f) => {
            if (f && !(f in next)) next[f] = 0.8;
          });
          return next;
        });
      }
      toast("Prompt drafted");
    } catch (e) {
      toast(e.message, true);
      setAssistError(e.message);
    } finally {
      setAssisting(false);
    }
  };

  const handleReuse = (img) => {
    const meta = imageMeta[img] || {};
    setPrompt(meta.prompt || "");
    setNegative(meta.negative || "");
    if (Array.isArray(meta.loras) && meta.loras.length) {
      const next = {};
      meta.loras.forEach((l) => {
        const name = (l && l.file_name) || (typeof l === "string" ? l : null);
        if (name) next[name] = Number(l?.weight) || 0.8;
      });
      setSelectedLoras(next);
    }
    toast("Prompt loaded — tweak and generate");
  };

  const handleModifyThis = (img) => {
    setSource({ name: img, label: img });
    setModifyOpen(true);
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

  const handleLoraDelete = async (l) => {
    if (!confirm(`Remove ${l.file_name}? The file is deleted from disk.`)) return;
    try {
      await api(`/loras/${encodeURIComponent(l.file_name)}`, { method: "DELETE" });
      setSelectedLoras((sel) => {
        const next = { ...sel };
        delete next[l.file_name];
        return next;
      });
      toast(`Removed ${l.file_name}`);
      loadLoras();
    } catch (e) { toast(e.message, true); }
  };

  const handleLoraIdentify = async (l) => {
    setIdentifying(l.file_name);
    try {
      const r = await api("/loras/identify", {
        method: "POST", body: { file_name: l.file_name } });
      if (r.ok) { toast(`Identified: ${r.meta.name || l.file_name}`); loadLoras(); }
      else toast(r.error || "Could not identify", true);
    } catch (e) { toast(e.message, true); }
    setIdentifying(null);
  };

  const handleLoraDownload = async (result) => {
    try {
      const r = await api("/loras/download", {
        method: "POST",
        // Carry the description/source/triggers so they survive with the file.
        body: {
          download_url: result.download_url, file_name: result.file_name,
          name: result.name, version_name: result.version_name,
          description: result.description, source_url: result.source_url,
          base_model: result.base_model, trigger_words: result.trigger_words,
          creator: result.creator, downloads: result.downloads,
          id: result.id, version_id: result.version_id,
        },
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
          <div style={{ marginBottom: 8 }}>
            <label style={{ display: "block", marginBottom: 4, fontWeight: 500 }}>Prompt</label>
            <textarea
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
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
              }}
            />
          </div>

          <div style={{ marginBottom: 16 }}>
            <div style={{ display: "flex", gap: 6 }}>
              <input
                type="text"
                value={assistText}
                onChange={(e) => setAssistText(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && !assisting && handleAssist()}
                disabled={assisting}
                placeholder={assistRequest
                  ? "What would you like to change? (optional feedback)…"
                  : 'Plain description, e.g. "a tiny wizard frog, gameboy style"…'}
                style={{
                  flex: 1, padding: "6px 8px", border: "1px solid var(--border)",
                  borderRadius: 6, fontSize: 12.5, opacity: assisting ? 0.6 : 1,
                }}
              />
              <button className="btn sm" onClick={handleAssist} disabled={assisting || !assistText.trim()}>
                {assisting ? "Thinking…" : assistRequest ? "🔄 Refine" : "✨ Help me write this"}
              </button>
              {assistRequest && !assisting && (
                <button className="btn sm ghost" style={{ padding: "5px 8px" }}
                  onClick={() => { setAssistRequest(""); setAssistText(""); setAssistNotes(""); setAssistModel(""); }}>
                  start over
                </button>
              )}
            </div>
            {(assistNotes || assistModel) && (
              <div className="param-hint" style={{ marginTop: 4 }}>
                {assistNotes}{assistNotes && assistModel ? " — " : ""}{assistModel ? `via ${assistModel}` : ""}
              </div>
            )}
            {assistError && (
              <div className="param-hint" style={{ color: "var(--red)", marginTop: 4 }}>Error: {assistError}</div>
            )}
          </div>

          <div style={{ marginBottom: 16 }}>
            <label style={{ display: "block", marginBottom: 4, fontWeight: 500 }}>Negative prompt (optional)</label>
            <input
              type="text"
              value={negative}
              onChange={(e) => setNegative(e.target.value)}
              placeholder="What to avoid in the image…"
              style={{
                width: "100%",
                padding: 8,
                border: "1px solid var(--border)",
                borderRadius: 6,
                fontSize: 13,
              }}
            />
          </div>

          <div style={{ marginBottom: 16, display: "flex", gap: 12, alignItems: "flex-end", flexWrap: "wrap" }}>
            <div style={{ flex: 1, minWidth: 160 }}>
              <label style={{ display: "block", marginBottom: 4, fontWeight: 500 }}>Aspect ratio</label>
              <select
                value={aspect}
                onChange={(e) => setAspect(e.target.value)}
                style={{
                  width: "100%",
                  padding: "8px 6px",
                  border: "1px solid var(--border)",
                  borderRadius: 6,
                  fontSize: 13,
                }}
              >
                <option value="1152*896">Landscape (1152x896)</option>
                <option value="896*1152">Portrait (896x1152)</option>
                <option value="1024*1024">Square (1024x1024)</option>
              </select>
            </div>
            <div style={{ flex: 1, minWidth: 160 }}>
              <label style={{ display: "block", marginBottom: 4, fontWeight: 500 }}>Speed / quality</label>
              <select
                value={speed}
                onChange={(e) => setSpeed(e.target.value)}
                style={{
                  width: "100%",
                  padding: "8px 6px",
                  border: "1px solid var(--border)",
                  borderRadius: 6,
                  fontSize: 13,
                }}
              >
                <option value="Extreme Speed">Extreme Speed (~8 steps, fastest)</option>
                <option value="Lightning">Lightning (~4 steps)</option>
                <option value="Speed">Speed (30 steps, slow)</option>
                <option value="Quality">Quality (60 steps, slowest)</option>
              </select>
            </div>
            <div>
              <label style={{ display: "block", marginBottom: 4, fontWeight: 500 }} title="How many jobs to queue">×N</label>
              <input type="number" min={1} max={10} value={queueCount}
                onChange={(e) => setQueueCount(e.target.value)}
                style={{
                  width: 52, padding: "8px 6px", border: "1px solid var(--border)",
                  borderRadius: 6, fontSize: 13, textAlign: "center",
                }} />
            </div>
            <div style={{ display: "flex", gap: 6 }}>
              <button
                className="btn primary"
                onClick={handleGenerate}
                disabled={enqueuing}
                style={{ opacity: enqueuing ? 0.7 : 1, minWidth: 120 }}
              >
                {enqueuing ? "Queuing…" : "✨ Generate"}
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
            Jobs run one at a time on the GPU — queue as many as you like and keep tweaking
            the form while they process. On a 4 GB GPU use Extreme Speed / Lightning;
            the 30-60 step modes can take ~40 min per image.
          </div>

          <div style={{ borderTop: "1px solid var(--border)", paddingTop: 10, marginBottom: 10 }}>
            <button className="btn sm ghost" style={{ padding: "4px 8px" }}
              onClick={() => setModifyOpen((o) => !o)}>
              {modifyOpen ? "▾" : "▸"} 🖼️ Modify an existing image
              {source ? ` (${source.label})` : ""}
            </button>

            {modifyOpen && (
              <div style={{ marginTop: 10 }}>
                <div className={"img-drop" + (dragOver ? " over" : "")}
                  onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
                  onDragLeave={() => setDragOver(false)}
                  onDrop={(e) => {
                    e.preventDefault(); setDragOver(false);
                    pickFile(e.dataTransfer.files?.[0]);
                  }}>
                  {source ? (
                    <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                      <img src={source.data || `/api/imagegen/images/${source.name}`}
                        alt="" className="img-drop-thumb" />
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ fontSize: 12.5, fontWeight: 600 }}>{source.label}</div>
                        <button className="btn sm ghost" style={{ padding: "1px 7px" }}
                          onClick={() => setSource(null)}>✕ choose another</button>
                      </div>
                    </div>
                  ) : (
                    <>
                      <div style={{ fontSize: 12.5, marginBottom: 6 }}>
                        Drop an image here, or
                        <label className="btn sm" style={{ marginLeft: 6, display: "inline-flex" }}>
                          browse…
                          <input type="file" accept="image/*" hidden
                            onChange={(e) => pickFile(e.target.files?.[0])} />
                        </label>
                      </div>
                      {images.length > 0 && (
                        <div>
                          <div className="param-hint">…or pick one you already made:</div>
                          <div style={{ display: "flex", gap: 6, overflowX: "auto", paddingTop: 6 }}>
                            {images.slice(0, 12).map((img) => (
                              <img key={img} src={`/api/imagegen/images/${img}`} alt=""
                                className="img-pick"
                                title={imageMeta[img]?.prompt || img}
                                onClick={() => setSource({ name: img, label: img })} />
                            ))}
                          </div>
                        </div>
                      )}
                    </>
                  )}
                </div>

                <div style={{ display: "flex", gap: 10, alignItems: "flex-end", marginTop: 10, flexWrap: "wrap" }}>
                  <div style={{ flex: 1, minWidth: 220 }}>
                    <label style={{ display: "block", marginBottom: 4, fontWeight: 500, fontSize: 12.5 }}>
                      What to do with it
                    </label>
                    <select value={mode} onChange={(e) => setMode(e.target.value)}
                      disabled={generating}
                      style={{ width: "100%", padding: "8px 6px", border: "1px solid var(--border)",
                               borderRadius: 6, fontSize: 13 }}>
                      {modes.map((m) => (
                        <option key={m.key} value={m.key}>{m.label}</option>
                      ))}
                    </select>
                  </div>
                  {["style", "structure", "depth", "face"].includes(mode) && (
                    <div>
                      <label style={{ display: "block", marginBottom: 4, fontWeight: 500, fontSize: 12.5 }}>
                        Influence
                      </label>
                      <input type="number" min={0.1} max={2} step={0.1} value={cnWeight}
                        onChange={(e) => setCnWeight(e.target.value)}
                        style={{ width: 70, padding: "7px 6px", border: "1px solid var(--border)",
                                 borderRadius: 6, fontSize: 13 }} />
                    </div>
                  )}
                  <button className="btn primary" disabled={generating || !source}
                    onClick={handleModify}>
                    {generating ? "Queuing…" : "🖼️ Modify"}
                  </button>
                </div>
                <div className="param-hint" style={{ marginTop: 6 }}>
                  Uses the prompt box above for the change you want (except pure upscales).
                  Queued like generate jobs — vary/restyle re-diffuse the image and take a
                  few minutes on this GPU; “Upscale 2× (fast)” is the quick one.
                </div>
              </div>
            )}
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
                            <div className="param-hint" style={{ marginTop: 2, display: "flex", gap: 8, flexWrap: "wrap" }}>
                              {r.source_url && (
                                <a href={r.source_url} target="_blank" rel="noopener noreferrer">
                                  🔗 inspect on Civitai
                                </a>
                              )}
                              {r.creator && <span>by {r.creator}</span>}
                              {(r.trigger_words || []).length > 0 && (
                                <span>trigger: <code>{r.trigger_words.join(", ")}</code></span>
                              )}
                            </div>
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
                  <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                    {localLoras.map((l) => (
                      <div key={l.file_name} className="lora-row">
                        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                          <input
                            type="checkbox"
                            checked={l.file_name in selectedLoras}
                            onChange={() => toggleLoraSelected(l.file_name)}
                          />
                          <span style={{ fontSize: 12.5, flex: 1, minWidth: 0 }}>
                            <b>{l.name || l.file_name}</b>
                            {l.builtin && <span className="chip" style={{ marginLeft: 6 }}>built-in</span>}
                            {l.base_model && <span className="chip" style={{ marginLeft: 6 }}>{l.base_model}</span>}
                          </span>
                          <span className="param-hint" style={{ margin: 0 }}>{l.size_mb} MB</span>
                          <input
                            type="number" min={0.1} max={2} step={0.1}
                            title="LoRA weight"
                            value={selectedLoras[l.file_name] ?? 0.8}
                            disabled={!(l.file_name in selectedLoras)}
                            onChange={(e) => setLoraWeight(l.file_name, e.target.value)}
                            style={{
                              width: 56, padding: "3px 5px", border: "1px solid var(--border)",
                              borderRadius: 5, fontSize: 12,
                            }}
                          />
                          {!l.builtin && (
                            <button className="icon-btn" title={`Remove ${l.file_name}`}
                              onClick={() => handleLoraDelete(l)}>🗑️</button>
                          )}
                        </div>
                        <div className="param-hint" style={{ paddingLeft: 24 }}>
                          {l.description
                            ? l.description
                            : <em>No description — this file has no metadata yet.</em>}
                        </div>
                        <div className="param-hint" style={{ paddingLeft: 24, display: "flex", gap: 10, flexWrap: "wrap" }}>
                          <code>{l.file_name}</code>
                          {l.source_url && (
                            <a href={l.source_url} target="_blank" rel="noopener noreferrer">🔗 source</a>
                          )}
                          {l.creator && <span>by {l.creator}</span>}
                          {(l.trigger_words || []).length > 0 && (
                            <span>trigger: <code>{l.trigger_words.join(", ")}</code></span>
                          )}
                          {!l.description && !l.builtin && (
                            <button className="btn sm ghost" style={{ padding: "1px 7px" }}
                              disabled={identifying === l.file_name}
                              onClick={() => handleLoraIdentify(l)}>
                              {identifying === l.file_name ? "looking up…" : "🔍 look up on Civitai"}
                            </button>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      )}

      {running && (
        <div style={{ marginTop: 20, borderTop: "1px solid var(--border)", paddingTop: 14 }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 10 }}>
            <h3 style={{ margin: 0 }}>
              Queue
              {queueActive && (
                <span className="param-hint" style={{ marginLeft: 8, fontWeight: 400 }}>
                  {queueJobs.filter((j) => j.status === "running").length} running ·{" "}
                  {queueJobs.filter((j) => j.status === "queued").length} queued
                </span>
              )}
            </h3>
            <button className="btn sm ghost" onClick={handleClearQueue}>Clear finished</button>
          </div>
          {queueJobs.length === 0 ? (
            <div className="param-hint">No jobs queued yet — Generate or Modify adds one here.</div>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              {queueJobs.map((j) => (
                <div key={j.id} style={{
                  display: "flex", alignItems: "center", gap: 10, padding: "7px 10px",
                  border: "1px solid var(--border)", borderRadius: 8, background: "var(--surface-2)",
                }}>
                  <span className={"status " + (j.status || "queued")}>{j.status || "queued"}</span>
                  <span style={{
                    flex: 1, minWidth: 0, fontSize: 12.5,
                    whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
                  }} title={j.prompt || j.error || ""}>
                    {j.kind === "modify" ? `🖼️ ${j.mode || "modify"}${j.prompt ? " — " + j.prompt : ""}` : (j.prompt || "—")}
                  </span>
                  {j.error && (
                    <span className="param-hint" style={{ color: "var(--red)", flexShrink: 0, maxWidth: 220,
                      overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={j.error}>
                      {j.error}
                    </span>
                  )}
                  {j.status === "queued" && (
                    <button className="icon-btn" title="Cancel" onClick={() => handleCancelJob(j.id)}>✕</button>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {images.length > 0 && (
        <div style={{ marginTop: 20 }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 12 }}>
            <h3 style={{ margin: 0 }}>Gallery</h3>
            <div style={{ display: "flex", gap: 4 }}>
              <button className={"btn sm" + (galleryView === "grid" ? " primary" : " ghost")}
                onClick={() => setGalleryView("grid")}>▦ Grid</button>
              <button className={"btn sm" + (galleryView === "table" ? " primary" : " ghost")}
                onClick={() => setGalleryView("table")}>☰ Table</button>
            </div>
          </div>

          {galleryView === "table" ? (
            <div style={{ overflowX: "auto" }}>
              <table className="assess">
                <thead>
                  <tr>
                    <th></th><th>Prompt</th><th>Negative</th><th>Mode / speed</th>
                    <th>LoRAs</th><th>Date</th><th></th>
                  </tr>
                </thead>
                <tbody>
                  {images.map((img) => {
                    const meta = imageMeta[img] || {};
                    const loras = Array.isArray(meta.loras) ? meta.loras : [];
                    return (
                      <tr key={img}>
                        <td>
                          <img src={`/api/imagegen/images/${img}`} alt="" className="img-pick"
                            title={meta.prompt || img}
                            onClick={() => window.open(`/api/imagegen/images/${img}`, "_blank")} />
                        </td>
                        <td style={{ maxWidth: 260 }}>
                          <div style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
                            title={meta.prompt || ""}>
                            {meta.prompt || "—"}
                          </div>
                        </td>
                        <td style={{ maxWidth: 180 }}>
                          <div style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
                            title={meta.negative || ""}>
                            {meta.negative || "—"}
                          </div>
                        </td>
                        <td className="mono">{meta.mode_label || meta.mode || meta.performance || "—"}</td>
                        <td>
                          {loras.length
                            ? loras.map((l) => (l && l.file_name) || l).filter(Boolean).join(", ")
                            : "—"}
                        </td>
                        <td>{meta.created ? fmtTime(meta.created) : "—"}</td>
                        <td style={{ whiteSpace: "nowrap" }}>
                          <button className="btn sm ghost" style={{ padding: "2px 7px", marginRight: 4 }}
                            disabled={!meta.prompt} title={!meta.prompt ? "No prompt recorded for this image" : ""}
                            onClick={() => handleReuse(img)}>♻️ Reuse</button>
                          <button className="btn sm ghost" style={{ padding: "2px 7px" }}
                            onClick={() => handleModifyThis(img)}>🖼️ Modify</button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          ) : (
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
          )}
        </div>
      )}
    </div>
  );
}
