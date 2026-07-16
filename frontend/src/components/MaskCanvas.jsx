import React, { useEffect, useRef, useState } from "react";

/* Paint-a-mask overlay for inpainting: the image sits under a transparent
 * canvas; the user brushes over the region to change. Strokes are stored as
 * opaque white on a transparent canvas (shown at reduced opacity so the photo
 * stays visible), and exported as solid white-on-black — the mask format
 * Fooocus expects (white = repaint, black = keep). The canvas runs at the
 * image's NATURAL resolution so the mask always matches the source pixels,
 * whatever size it renders at on screen. */
export default function MaskCanvas({ src, onMask }) {
  const imgRef = useRef(null);
  const canvasRef = useRef(null);
  const drawing = useRef(false);
  const last = useRef(null);
  const [ready, setReady] = useState(false);
  const [brush, setBrush] = useState(40);
  const [erasing, setErasing] = useState(false);
  const [dirty, setDirty] = useState(false);

  // Size the canvas to the image's natural pixels once it loads.
  const onImgLoad = () => {
    const img = imgRef.current, cv = canvasRef.current;
    if (!img || !cv) return;
    cv.width = img.naturalWidth;
    cv.height = img.naturalHeight;
    setBrush(Math.max(20, Math.round(img.naturalWidth / 18)));
    setReady(true);
  };

  useEffect(() => { setReady(false); setDirty(false); onMask(null); }, [src]); // eslint-disable-line

  const toCanvasXY = (e) => {
    const cv = canvasRef.current;
    const r = cv.getBoundingClientRect();
    return {
      x: (e.clientX - r.left) * (cv.width / r.width),
      y: (e.clientY - r.top) * (cv.height / r.height),
    };
  };

  const stroke = (from, to) => {
    const ctx = canvasRef.current.getContext("2d");
    ctx.globalCompositeOperation = erasing ? "destination-out" : "source-over";
    ctx.strokeStyle = "#ffffff";
    ctx.lineWidth = brush;
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    ctx.beginPath();
    ctx.moveTo(from.x, from.y);
    ctx.lineTo(to.x, to.y);
    ctx.stroke();
  };

  const exportMask = () => {
    const cv = canvasRef.current;
    // Solid white strokes composited onto a black background.
    const out = document.createElement("canvas");
    out.width = cv.width; out.height = cv.height;
    const ctx = out.getContext("2d");
    ctx.fillStyle = "#000000";
    ctx.fillRect(0, 0, out.width, out.height);
    ctx.drawImage(cv, 0, 0);
    // Anything painted (any alpha) must be pure white for a crisp mask.
    const px = ctx.getImageData(0, 0, out.width, out.height);
    const d = px.data;
    for (let i = 0; i < d.length; i += 4) {
      const v = d[i + 3] > 0 && (d[i] > 10 || d[i + 1] > 10 || d[i + 2] > 10) ? 255 : 0;
      d[i] = d[i + 1] = d[i + 2] = v; d[i + 3] = 255;
    }
    ctx.putImageData(px, 0, 0);
    return out.toDataURL("image/png");
  };

  const down = (e) => {
    if (!ready) return;
    e.preventDefault();
    canvasRef.current.setPointerCapture(e.pointerId);
    drawing.current = true;
    const p = toCanvasXY(e);
    last.current = p;
    stroke(p, p); // dot on click
  };
  const move = (e) => {
    if (!drawing.current) return;
    const p = toCanvasXY(e);
    stroke(last.current, p);
    last.current = p;
  };
  const up = () => {
    if (!drawing.current) return;
    drawing.current = false;
    setDirty(true);
    onMask(exportMask());
  };

  const clear = () => {
    const cv = canvasRef.current;
    cv.getContext("2d").clearRect(0, 0, cv.width, cv.height);
    setDirty(false);
    onMask(null);
  };

  return (
    <div className="mask-wrap">
      <div className="mask-stage">
        <img ref={imgRef} src={src} alt="" onLoad={onImgLoad} draggable={false} />
        <canvas ref={canvasRef} className="mask-canvas"
          onPointerDown={down} onPointerMove={move}
          onPointerUp={up} onPointerCancel={up} />
      </div>
      <div className="mask-tools">
        <button className={"btn sm" + (!erasing ? " primary" : "")}
          onClick={() => setErasing(false)}>🖌 Paint</button>
        <button className={"btn sm" + (erasing ? " primary" : "")}
          onClick={() => setErasing(true)}>◻ Erase</button>
        <label className="mask-brush">
          size
          <input type="range" min={10} max={160} value={brush}
            onChange={(e) => setBrush(+e.target.value)} />
        </label>
        <button className="btn sm ghost" onClick={clear} disabled={!dirty}>✕ Clear</button>
        <span className="param-hint" style={{ margin: 0 }}>
          {dirty ? "painted area will be re-generated"
                 : "paint over what you want changed"}
        </span>
      </div>
    </div>
  );
}
