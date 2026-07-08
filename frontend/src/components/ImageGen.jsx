import React, { useEffect, useRef, useState } from "react";
import { api, toast } from "../lib/api.js";

export default function ImageGen() {
  const [status, setStatus] = useState(null);
  const [images, setImages] = useState([]);
  const [prompt, setPrompt] = useState("");
  const [negative, setNegative] = useState("");
  const [aspect, setAspect] = useState("1152*896");
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState(null);
  const pollRef = useRef(null);

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
      const r = await api("/imagegen/generate", {
        method: "POST",
        body: { prompt, negative, aspect },
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

  if (!status) return <div className="card section-card"><p className="page-sub">Loading…</p></div>;

  const { installed, running, installing, error: statusError, install } = status;
  const displayError = error || statusError;

  return (
    <div className="card section-card">
      <h2>🎨 Image generation (Fooocus)</h2>
      <div className="sub">Local image generation on your GPU</div>

      {displayError && (
        <div className="param-hint" style={{ color: "var(--err)", marginBottom: 12 }}>
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
            {generating ? "This can take a few minutes on a slow GPU…" : "Ready to generate"}
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
              <img
                key={idx}
                src={`/api/imagegen/images/${img}`}
                alt={`Generated ${idx}`}
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
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
