import React, { useEffect, useRef, useState } from "react";
import { api, toast } from "../lib/api.js";

/* Video Maker: idea → LLM shot list → one Fooocus still per shot → ffmpeg
 * assembles Ken Burns pan/zoom + crossfades into an mp4. Honest framing: this
 * is the pipeline a 4GB GPU can actually do — animated slideshows from
 * generated stills, not frame-by-frame video diffusion. */
export default function VideoMaker({ startOpen = false }) {
  const [open, setOpen] = useState(startOpen);
  const [idea, setIdea] = useState("");
  const [nShots, setNShots] = useState(5);
  const [planning, setPlanning] = useState(false);
  const [shots, setShots] = useState([]);        // [{prompt, seconds}]
  const [title, setTitle] = useState("");
  const [projects, setProjects] = useState([]);
  const pollRef = useRef(null);

  const load = () => api("/video").then((d) => setProjects(d.projects || [])).catch(() => {});
  useEffect(() => {
    if (!open) return;
    load();
    pollRef.current = setInterval(load, 12000);
    return () => clearInterval(pollRef.current);
  }, [open]);

  const plan = async () => {
    if (!idea.trim()) { toast("Describe the video first", true); return; }
    setPlanning(true);
    try {
      const r = await api("/video/plan", { method: "POST",
        body: { idea, shots: +nShots || 5 } });
      if (!r.ok) toast(r.error, true);
      else {
        setShots(r.shots);
        if (!title) setTitle(idea.slice(0, 60));
        toast(`${r.shots.length} shots drafted by ${r.planner} — edit them, then generate`);
      }
    } catch (e) { toast(e.message, true); }
    setPlanning(false);
  };

  const createProject = async () => {
    if (shots.length < 2) { toast("A video needs at least 2 shots", true); return; }
    try {
      const r = await api("/video", { method: "POST",
        body: { title: title || idea.slice(0, 60), shots } });
      toast("Stills queued — they render one at a time on the GPU");
      setShots([]); setIdea(""); setTitle("");
      load();
    } catch (e) { toast(e.message, true); }
  };

  const assemble = async (p) => {
    try {
      await api(`/video/${p.id}/assemble`, { method: "POST" });
      toast("Assembling video…");
      load();
    } catch (e) { toast(e.message, true); }
  };

  const del = async (p) => {
    if (!confirm(`Delete video project "${p.title}"?`)) return;
    await api(`/video/${p.id}`, { method: "DELETE" }).catch(() => {});
    load();
  };

  const STATUS = {
    generating: ["⏳", "rendering stills"],
    ready: ["🟢", "stills ready — assemble!"],
    assembling: ["🎞️", "assembling…"],
    done: ["✅", "done"],
    error: ["⚠️", "error"],
  };

  return (
    <div className="card" style={{ padding: 16, marginTop: 16 }}>
      <button className="btn sm ghost" style={{ padding: "4px 8px" }}
        onClick={() => setOpen((o) => !o)}>
        {open ? "▾" : "▸"} 🎬 Video Maker
      </button>
      {open && (
        <div style={{ marginTop: 12 }}>
          <div className="page-sub" style={{ marginBottom: 10 }}>
            An LLM plans the shots, Fooocus renders a still per shot, ffmpeg adds
            pan/zoom and crossfades. (Real video diffusion needs 8-24GB VRAM —
            this is the pipeline a 4GB GPU can honestly deliver.)
          </div>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "flex-end" }}>
            <div style={{ flex: 1, minWidth: 260 }}>
              <label style={{ display: "block", fontSize: 12.5, fontWeight: 500, marginBottom: 4 }}>
                What is the video about?
              </label>
              <textarea rows={2} value={idea} onChange={(e) => setIdea(e.target.value)}
                placeholder="e.g. the four seasons transforming a mountain village"
                style={{ width: "100%", padding: 8, border: "1px solid var(--border)",
                         borderRadius: 6, fontSize: 13, resize: "vertical" }} />
            </div>
            <div>
              <label style={{ display: "block", fontSize: 12.5, fontWeight: 500, marginBottom: 4 }}>Shots</label>
              <input type="number" min={2} max={12} value={nShots}
                onChange={(e) => setNShots(e.target.value)}
                style={{ width: 58, padding: "7px 6px", border: "1px solid var(--border)",
                         borderRadius: 6, fontSize: 13, textAlign: "center" }} />
            </div>
            <button className="btn" onClick={plan} disabled={planning}>
              {planning ? "Drafting…" : "🪄 Draft shots"}
            </button>
          </div>

          {shots.length > 0 && (
            <div style={{ marginTop: 12 }}>
              <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 8 }}>
                <input type="text" value={title} placeholder="Video title"
                  onChange={(e) => setTitle(e.target.value)}
                  style={{ flex: 1, padding: "7px 9px", border: "1px solid var(--border)",
                           borderRadius: 6, fontSize: 13 }} />
                <button className="btn primary" onClick={createProject}>
                  ✨ Generate {shots.length} stills
                </button>
              </div>
              {shots.map((s, i) => (
                <div key={i} className="vm-shot">
                  <span className="vm-shot-n">{i + 1}</span>
                  <textarea rows={2} value={s.prompt}
                    onChange={(e) => setShots((ss) => ss.map((x, j) =>
                      j === i ? { ...x, prompt: e.target.value } : x))} />
                  <span className="vm-shot-secs">
                    <input type="number" min={2} max={8} step={0.5} value={s.seconds}
                      onChange={(e) => setShots((ss) => ss.map((x, j) =>
                        j === i ? { ...x, seconds: +e.target.value || 4 } : x))} />s
                  </span>
                  <button className="icon-btn" title="Remove shot"
                    onClick={() => setShots((ss) => ss.filter((_, j) => j !== i))}>🗑</button>
                </div>
              ))}
            </div>
          )}

          {projects.length > 0 && <div style={{ borderTop: "1px solid var(--border)", margin: "14px 0 10px" }} />}
          {projects.map((p) => {
            const [ico, label] = STATUS[p.status] || ["…", p.status];
            const doneStills = p.shots.filter((s) => s.image).length;
            return (
              <div key={p.id} className="vm-project">
                <div className="vm-project-head">
                  <strong>{p.title}</strong>
                  <span className="vm-status">{ico} {label}
                    {p.status === "generating" && ` (${doneStills}/${p.shots.length} stills)`}
                  </span>
                  <span style={{ flex: 1 }} />
                  {p.status === "ready" && (
                    <button className="btn sm primary" onClick={() => assemble(p)}>🎞️ Assemble</button>
                  )}
                  <button className="icon-btn" onClick={() => del(p)}>🗑</button>
                </div>
                {p.error && <div className="vm-error">{p.error}</div>}
                <div className="vm-strip">
                  {p.shots.map((s, i) => s.image
                    ? <img key={i} src={`/api/imagegen/images/${s.image}`} alt="" title={s.prompt} />
                    : <span key={i} className="vm-pending" title={s.prompt}>⏳</span>)}
                </div>
                {p.video && (
                  <video controls preload="metadata" className="vm-video"
                    src={`/api/video/file/${p.video}`} />
                )}
              </div>
            );
          })}
          {!projects.length && !shots.length && (
            <div className="help" style={{ marginTop: 10 }}>
              No video projects yet — describe an idea above and draft shots.
            </div>
          )}
        </div>
      )}
    </div>
  );
}
