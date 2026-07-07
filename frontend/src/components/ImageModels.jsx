import React, { useEffect, useState } from "react";
import { api } from "../lib/api.js";

export default function ImageModels() {
  const [img, setImg] = useState(null);
  useEffect(() => {
    api("/catalog").then((d) => setImg(d.image)).catch(() => {});
  }, []);
  if (!img) return null;

  return (
    <div className="card section-card">
      <h2>🎨 Local image generation</h2>
      <div className="sub">
        {img.setup.note} These run in a separate app (not Ollama).
      </div>

      <div className="spec-grid" style={{ marginBottom: 14 }}>
        {img.setup.runners.map((r) => (
          <div key={r.name} className="spec-tile">
            <div className="k">Runner</div>
            <div className="v"><a href={r.url} target="_blank" rel="noopener noreferrer">{r.name}</a></div>
            <div className="d">{r.blurb}</div>
          </div>
        ))}
      </div>

      <table className="assess">
        <thead>
          <tr><th>Model</th><th>Download</th><th>Min VRAM</th><th>Runs in</th><th>On this PC</th></tr>
        </thead>
        <tbody>
          {img.models.map((m) => (
            <tr key={m.name}>
              <td>
                <strong>{m.name}</strong>
                <span className="chip" style={{ marginLeft: 6 }}>{m.tag}</span>
                <div className="param-hint" style={{ maxWidth: 460 }}>{m.description}</div>
              </td>
              <td>{m.disk_gb} GB</td>
              <td>{m.min_vram_gb} GB</td>
              <td style={{ fontSize: 12 }}>{m.runner}</td>
              <td>
                <span className={"verdict " + (m.verdict === "no" ? "no" : m.verdict)}
                  title={m.verdict_label}>{m.verdict === "no" ? "won't run" : m.verdict}</span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {img.best && (
        <p className="page-sub" style={{ marginTop: 12 }}>
          Best fit for your GPU: <strong>{img.best.name}</strong> — install {" "}
          <a href={img.setup.runners[0].url} target="_blank" rel="noopener noreferrer">
            {img.setup.runners[0].name}</a>, then download {img.best.name} into it.
        </p>
      )}
    </div>
  );
}
