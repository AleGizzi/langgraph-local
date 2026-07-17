import React, { useEffect, useMemo, useRef, useState } from "react";
import { api, toast } from "../lib/api.js";
import { Md } from "../lib/markdown.jsx";

function fmtTime(ts) {
  if (!ts) return "";
  return new Date(ts * 1000).toLocaleString([], {
    month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

function splitFrontmatter(text) {
  if (!text.startsWith("---")) return { meta: [], body: text };
  const end = text.indexOf("\n---", 3);
  if (end === -1) return { meta: [], body: text };
  const raw = text.slice(3, end).trim();
  const body = text.slice(end + 4).replace(/^\n+/, "");
  const meta = raw.split("\n").map((l) => {
    const i = l.indexOf(":");
    return i === -1 ? null : [l.slice(0, i).trim(), l.slice(i + 1).trim()];
  }).filter(Boolean);
  return { meta, body };
}

/* Stable folder → color mapping for the graph and folder chips. */
const FOLDER_COLORS = ["#155eef", "#067647", "#b54708", "#6938ef", "#d92d20",
                       "#0e7090", "#c11574", "#3e4784", "#a15c07", "#175cd3"];
function folderColor(name, folderList) {
  if (!name) return "#98a2b3";
  const i = folderList.indexOf(name);
  return FOLDER_COLORS[(i >= 0 ? i : name.length) % FOLDER_COLORS.length];
}

function NoteEditor({ folders, onClose, onSaved }) {
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [folder, setFolder] = useState("notes");
  const save = async () => {
    if (!title.trim() || !content.trim()) { toast("Title and content required", true); return; }
    try {
      await api("/knowledge/note", { method: "POST", body: { title, content, folder } });
      toast(`Note saved to ${folder || "the vault root"}`);
      onSaved();
    } catch (e) { toast(e.message, true); }
  };
  return (
    <div className="modal-back" onClick={(e) => e.target.classList.contains("modal-back") && onClose()}>
      <div className="modal" style={{ maxWidth: 720 }}>
        <div className="modal-head">
          <h2>New note</h2>
          <button className="btn ghost" onClick={onClose}>✕</button>
        </div>
        <div className="modal-body">
          <div className="field">
            <label>Title</label>
            <input type="text" value={title} onChange={(e) => setTitle(e.target.value)}
              placeholder="e.g. Decision: default model choice" />
          </div>
          <div className="field">
            <label>Sub-vault (folder) — group related knowledge so a whole topic can be removed together</label>
            <input type="text" value={folder} list="kb-folder-options"
              onChange={(e) => setFolder(e.target.value)} placeholder="notes" />
            <datalist id="kb-folder-options">
              {folders.filter((f) => f.name).map((f) => <option key={f.name} value={f.name} />)}
            </datalist>
          </div>
          <div className="field">
            <label>Content (Markdown — use [[wikilinks]] to relate notes; links show in the graph)</label>
            <textarea rows={12} value={content} onChange={(e) => setContent(e.target.value)}
              style={{ fontFamily: "var(--mono)", fontSize: 12.5 }} />
          </div>
        </div>
        <div className="modal-foot">
          <button className="btn" onClick={onClose}>Cancel</button>
          <button className="btn primary" onClick={save}>Save to vault</button>
        </div>
      </div>
    </div>
  );
}

/* Obsidian-style graph v2: one organic force layout on canvas, no library.
 * Notes cluster into folder "galaxies" (each sub-vault has an invisible
 * centroid arranged on a ring; its notes feel a gentle pull toward it), links
 * pull related notes together across galaxies, and hovering highlights a note
 * with its neighbors. Colors come from the live CSS variables so the graph
 * matches light/dark mode. */
function VaultGraph({ folders, onOpen }) {
  const canvasRef = useRef(null);
  const [graph, setGraph] = useState(null);
  const nodesRef = useRef([]);
  const edgesRef = useRef([]);
  const hoverRef = useRef(null);

  useEffect(() => { api("/knowledge/graph").then(setGraph).catch(() => {}); }, []);

  const cssVar = (name, fallback) =>
    getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback;

  const draw = () => {
    const cv = canvasRef.current;
    if (!cv) return;
    const W = cv.clientWidth, H = Math.max(420, cv.clientHeight);
    const ctx = cv.getContext("2d");
    ctx.setTransform(devicePixelRatio, 0, 0, devicePixelRatio, 0, 0);
    ctx.clearRect(0, 0, W, H);
    const nodes = nodesRef.current, edges = edgesRef.current;
    const hover = hoverRef.current;
    const textCol = cssVar("--text-3", "#98a2b3");
    const dimText = cssVar("--border-strong", "#d0d5dd");
    const neighbors = new Set();
    if (hover != null) {
      neighbors.add(hover);
      for (const e of edges) {
        if (e.a === hover) neighbors.add(e.b);
        if (e.b === hover) neighbors.add(e.a);
      }
    }
    // edges
    for (const e of edges) {
      const active = hover != null && (e.a === hover || e.b === hover);
      ctx.strokeStyle = active ? cssVar("--accent", "#155eef") : textCol;
      ctx.globalAlpha = hover == null ? 0.28 : active ? 0.9 : 0.07;
      ctx.lineWidth = active ? 1.6 : 1;
      ctx.beginPath();
      ctx.moveTo(nodes[e.a].x, nodes[e.a].y);
      ctx.lineTo(nodes[e.b].x, nodes[e.b].y);
      ctx.stroke();
    }
    ctx.globalAlpha = 1;
    // nodes
    const folderNames = folders.map((f) => f.name).filter(Boolean);
    nodes.forEach((n, i) => {
      const r = 3.5 + Math.min(7, n.deg * 1.5);
      const dimmed = hover != null && !neighbors.has(i);
      ctx.globalAlpha = dimmed ? 0.18 : 1;
      ctx.beginPath();
      ctx.arc(n.x, n.y, r, 0, Math.PI * 2);
      if (n.ghost) {
        ctx.fillStyle = textCol;
        ctx.globalAlpha = dimmed ? 0.1 : 0.35;
        ctx.fill();
        ctx.globalAlpha = dimmed ? 0.18 : 0.8;
        ctx.setLineDash([3, 3]);
        ctx.strokeStyle = textCol;
        ctx.stroke();
        ctx.setLineDash([]);
      } else {
        ctx.fillStyle = folderColor(n.folder, folderNames);
        ctx.fill();
        if (i === hover) {
          ctx.lineWidth = 2;
          ctx.strokeStyle = cssVar("--text", "#101828");
          ctx.stroke();
        }
      }
      // labels: hubs always, everything on hover-neighborhood
      const showLabel = i === hover || (hover != null && neighbors.has(i))
        || (hover == null && n.deg >= 2) || nodes.length <= 25;
      if (showLabel) {
        ctx.globalAlpha = dimmed ? 0.2 : 1;
        ctx.font = (i === hover ? "600 11px" : "10px") + " -apple-system, sans-serif";
        ctx.fillStyle = i === hover ? cssVar("--text", "#101828")
          : hover != null && neighbors.has(i) ? cssVar("--text-2", "#475467") : dimText;
        const label = n.title.length > 30 ? n.title.slice(0, 29) + "…" : n.title;
        ctx.fillText(label, n.x + r + 4, n.y + 3.5);
      }
    });
    ctx.globalAlpha = 1;
  };

  useEffect(() => {
    if (!graph) return;
    const cv = canvasRef.current;
    if (!cv) return;
    const W = cv.clientWidth, H = Math.max(420, cv.clientHeight);
    cv.width = W * devicePixelRatio; cv.height = H * devicePixelRatio;

    const nodes = graph.nodes.map((n) => ({ ...n, x: 0, y: 0, vx: 0, vy: 0, deg: 0 }));
    const idx = Object.fromEntries(nodes.map((n, i) => [n.id, i]));
    const edges = graph.edges
      .filter((e) => idx[e.from] !== undefined && idx[e.to] !== undefined)
      .map((e) => ({ a: idx[e.from], b: idx[e.to] }));
    edges.forEach((e) => { nodes[e.a].deg++; nodes[e.b].deg++; });

    // Layout: unlinked notes get DETERMINISTIC per-folder sunflower clusters
    // arranged on a ring (physics kept blasting them into the walls — twice);
    // only the linked subgraph is force-simulated, in the middle.
    const groupOf = (n) => (n.ghost ? "__ghost__" : n.folder || "__root__");
    const linked = [], loose = [];
    nodes.forEach((n, i) => (n.deg > 0 ? linked : loose).push(i));

    const byGroup = {};
    for (const i of loose) (byGroup[groupOf(nodes[i])] ||= []).push(i);
    const groups = Object.keys(byGroup);
    const GA = Math.PI * (3 - Math.sqrt(5)); // golden angle
    groups.forEach((g, gi) => {
      const members = byGroup[g];
      const ang = (gi / Math.max(1, groups.length)) * Math.PI * 2 - Math.PI / 2;
      const ringR = Math.min(W, H) * 0.36;
      const cx = W / 2 + Math.cos(ang) * ringR;
      const cy = H / 2 + Math.sin(ang) * ringR * 0.82;
      members.forEach((i, mi) => {
        const r = 9 * Math.sqrt(mi + 0.6);
        const th = mi * GA;
        nodes[i].x = Math.max(14, Math.min(W - 120, cx + Math.cos(th) * r));
        nodes[i].y = Math.max(14, Math.min(H - 14, cy + Math.sin(th) * r));
      });
    });

    // force sim for the linked subgraph only (params proven on this vault)
    const lidx = new Map(linked.map((i, li) => [i, li]));
    const L = linked.map((i) => nodes[i]);
    const ledges = edges.filter((e) => lidx.has(e.a) && lidx.has(e.b))
      .map((e) => ({ a: lidx.get(e.a), b: lidx.get(e.b) }));
    L.forEach((n, i) => {
      n.x = W / 2 + Math.cos(i * 2.4) * (40 + i * 5);
      n.y = H / 2 + Math.sin(i * 2.4) * (30 + i * 4);
    });
    for (let it = 0; it < 260; it++) {
      const k = 1 - it / 300;
      for (let i = 0; i < L.length; i++) {
        for (let j = i + 1; j < L.length; j++) {
          const a = L[i], b = L[j];
          const dx = a.x - b.x, dy = a.y - b.y;
          const d2 = Math.max(dx * dx + dy * dy, 60);
          const rep = 380 / d2;
          a.vx += dx * rep * k; a.vy += dy * rep * k;
          b.vx -= dx * rep * k; b.vy -= dy * rep * k;
        }
      }
      for (const e of ledges) {
        const a = L[e.a], b = L[e.b];
        const dx = b.x - a.x, dy = b.y - a.y;
        a.vx += dx * 0.03 * k; a.vy += dy * 0.03 * k;
        b.vx -= dx * 0.03 * k; b.vy -= dy * 0.03 * k;
      }
      for (const n of L) {
        n.vx += (W / 2 - n.x) * 0.022; n.vy += (H / 2 - n.y) * 0.022;
        n.x += Math.max(-10, Math.min(10, n.vx));
        n.y += Math.max(-10, Math.min(10, n.vy));
        n.vx *= 0.55; n.vy *= 0.55;
        n.x = Math.max(20, Math.min(W - 130, n.x));
        n.y = Math.max(18, Math.min(H - 18, n.y));
      }
    }
    nodesRef.current = nodes;
    edgesRef.current = edges;
    hoverRef.current = null;
    draw();
  }, [graph, folders]);

  const nodeAt = (e) => {
    const rect = canvasRef.current.getBoundingClientRect();
    const x = e.clientX - rect.left, y = e.clientY - rect.top;
    let best = null, bd = 14 * 14;
    nodesRef.current.forEach((n, i) => {
      const d = (n.x - x) ** 2 + (n.y - y) ** 2;
      if (d < bd) { bd = d; best = i; }
    });
    return best;
  };

  const move = (e) => {
    const h = nodeAt(e);
    if (h !== hoverRef.current) {
      hoverRef.current = h;
      canvasRef.current.style.cursor = h != null ? "pointer" : "default";
      draw();
    }
  };

  const click = (e) => {
    const i = nodeAt(e);
    if (i == null) return;
    const n = nodesRef.current[i];
    if (!n.ghost) onOpen(n.id);
    else toast(`"${n.title}" is a ghost — linked but no note exists yet`);
  };

  const folderNames = folders.map((f) => f.name).filter(Boolean);
  return (
    <div className="kb-graph card">
      {!graph
        ? <div className="empty" style={{ margin: "auto" }}>Loading graph…</div>
        : graph.nodes.length === 0
          ? <div className="empty" style={{ margin: "auto" }}>
              <div className="big">🕸️</div>No notes yet — the graph draws itself as knowledge accumulates.
            </div>
          : <>
              <canvas ref={canvasRef} onClick={click} onPointerMove={move}
                onPointerLeave={() => { hoverRef.current = null; draw(); }}
                style={{ width: "100%", height: "100%" }} />
              <div className="kb-graph-legend">
                {folderNames.map((f) => (
                  <span key={f}><i style={{ background: folderColor(f, folderNames) }} />{f}</span>
                ))}
                <span><i style={{ background: "#98a2b3", opacity: .5 }} />ghost (linked, not written)</span>
                <span style={{ opacity: .7 }}>hover to explore · click to open</span>
              </div>
            </>}
    </div>
  );
}

export default function Knowledge() {
  const [data, setData] = useState(null);
  const [folders, setFolders] = useState([]);
  const [q, setQ] = useState("");
  const [selected, setSelected] = useState(null);
  const [noteText, setNoteText] = useState("");
  const [editing, setEditing] = useState(false);
  const [view, setView] = useState("list"); // list | graph
  const [collapsed, setCollapsed] = useState({});

  const load = (query = "") => {
    const url = query ? `/knowledge?q=${encodeURIComponent(query)}` : "/knowledge";
    api(url).then(setData).catch(() => {});
    api("/knowledge/folders").then((d) => setFolders(d.folders || [])).catch(() => {});
  };
  useEffect(() => { load(); }, []);

  useEffect(() => {
    if (!selected) { setNoteText(""); return; }
    api(`/knowledge/note?path=${encodeURIComponent(selected)}`)
      .then((d) => setNoteText(d.content)).catch(() => setNoteText("(could not read note)"));
  }, [selected]);

  const items = data ? (data.results || data.notes || []) : [];

  // group by top-level folder ("" = vault root)
  const groups = useMemo(() => {
    const g = {};
    for (const n of items) {
      const top = n.path.includes("/") ? n.path.split("/")[0] : "";
      (g[top] = g[top] || []).push(n);
    }
    return Object.entries(g).sort(([a], [b]) => a.localeCompare(b));
  }, [items]);

  const deleteNote = async (n, e) => {
    e.stopPropagation();
    if (!confirm(`Delete note "${n.title}"?\n\nThis removes ${n.path} from the vault on disk.`)) return;
    try {
      await api(`/knowledge/note?path=${encodeURIComponent(n.path)}`, { method: "DELETE" });
      toast("Note deleted");
      if (selected === n.path) setSelected(null);
      load(q);
    } catch (e2) { toast(e2.message, true); }
  };

  const deleteFolder = async (name, count) => {
    if (!confirm(`Delete the whole "${name}" sub-vault?\n\n${count} note(s) will be removed from disk. `
      + `This is the "forget this topic" operation — it cannot be undone.`)) return;
    try {
      const r = await api(`/knowledge/folder?path=${encodeURIComponent(name)}`, { method: "DELETE" });
      toast(`Sub-vault "${name}" deleted (${r.deleted} notes)`);
      if (selected?.startsWith(name + "/")) setSelected(null);
      load(q);
    } catch (e) { toast(e.message, true); }
  };

  const moveNote = async (folder) => {
    if (folder === "__new__") {
      folder = (prompt("New sub-vault name:") || "").trim();
      if (!folder) return;
    }
    try {
      const r = await api("/knowledge/move", { method: "POST",
        body: { path: selected, folder } });
      toast(`Moved to ${folder || "vault root"}`);
      setSelected(r.path);
      load(q);
    } catch (e) { toast(e.message, true); }
  };

  return (
    <>
      <div className="page-head">
        <div>
          <h1 className="page-title">Knowledge</h1>
          <p className="page-sub">
            A shared Markdown vault — team deliverables are archived here
            automatically and agents can search it with the <code>knowledge</code> tool
          </p>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <button className={"btn" + (view === "graph" ? " primary" : "")}
            onClick={() => setView(view === "graph" ? "list" : "graph")}>
            {view === "graph" ? "📄 Notes" : "🕸️ Graph"}
          </button>
          <button className="btn primary" onClick={() => setEditing(true)}>＋ New note</button>
        </div>
      </div>

      {data && (
        <div className="kb-vaultbar">
          <span className="help">
            📁 <code>{data.stats.dir}</code> · {data.stats.count} notes ·
            {" "}{folders.filter((f) => f.name).length} sub-vaults
          </span>
          <span className="help">
            Open this folder in <strong>Obsidian</strong>, <strong>Logseq</strong> or
            <strong> Foam</strong> — it is a standard vault, no import needed.
          </span>
        </div>
      )}

      {view === "graph" ? (
        <VaultGraph folders={folders}
          onOpen={(path) => { setSelected(path); setView("list"); }} />
      ) : (
      <div className="kb-layout">
        <div className="kb-list card">
          <div className="kb-search">
            <input type="text" value={q} placeholder="Search notes…"
              onChange={(e) => { setQ(e.target.value); }}
              onKeyDown={(e) => { if (e.key === "Enter") load(q); }} />
            <button className="btn sm" onClick={() => load(q)}>Search</button>
            {q && <button className="btn sm ghost" onClick={() => { setQ(""); load(); }}>Clear</button>}
          </div>
          <div className="kb-items">
            {groups.map(([folder, notes]) => (
              <div key={folder || "(root)"}>
                <div className="kb-folder-head">
                  <span className="kb-folder-name"
                    onClick={() => setCollapsed((c) => ({ ...c, [folder]: !c[folder] }))}>
                    {collapsed[folder] ? "▸" : "▾"} {folder
                      ? <><i className="kb-folder-dot"
                          style={{ background: folderColor(folder, folders.map((f) => f.name).filter(Boolean)) }} />
                          {folder}</>
                      : "🗂 (vault root)"} <em>({notes.length})</em>
                  </span>
                  {folder && (
                    <button className="icon-btn" title={`Delete the whole "${folder}" sub-vault`}
                      onClick={() => deleteFolder(folder, notes.length)}>🗑</button>
                  )}
                </div>
                {!collapsed[folder] && notes.map((n) => (
                  <div key={n.path}
                    className={"kb-item" + (selected === n.path ? " active" : "")}
                    onClick={() => setSelected(n.path)}>
                    <div className="kb-item-row">
                      <div className="kb-item-title">{n.title}</div>
                      <button className="icon-btn kb-item-del" title="Delete note"
                        onClick={(e) => deleteNote(n, e)}>🗑</button>
                    </div>
                    {n.snippet
                      ? <div className="kb-item-sub">{n.snippet}</div>
                      : <div className="kb-item-sub">{(n.tags || []).join(", ")} · {fmtTime(n.modified)}</div>}
                  </div>
                ))}
              </div>
            ))}
            {!items.length && (
              <div className="empty" style={{ padding: 32 }}>
                <div className="big">📚</div>
                {q ? "No notes match." : "No notes yet — run a team and its output lands here."}
              </div>
            )}
          </div>
        </div>

        <div className="kb-reader card">
          {selected ? (
            <>
              <div className="kb-reader-head">
                <span className="mono" style={{ fontFamily: "var(--mono)", fontSize: 12 }}>{selected}</span>
                <span style={{ display: "inline-flex", gap: 6, alignItems: "center" }}>
                  <select className="kb-move" value="" title="Move this note to a sub-vault"
                    onChange={(e) => e.target.value !== "" && moveNote(e.target.value)}>
                    <option value="" disabled>📂 Move to…</option>
                    {folders.filter((f) => f.name && selected && !selected.startsWith(f.name + "/"))
                      .map((f) => <option key={f.name} value={f.name}>{f.name}</option>)}
                    <option value="__new__">＋ new sub-vault…</option>
                  </select>
                  <button className="btn sm" onClick={() =>
                    navigator.clipboard.writeText(noteText).then(() => toast("Copied"))}>Copy</button>
                </span>
              </div>
              {(() => {
                const { meta, body } = splitFrontmatter(noteText);
                return (
                  <div className="kb-reader-body">
                    {meta.length > 0 && (
                      <div className="kb-meta">
                        {meta.map(([k, v]) => (
                          <span key={k} className="kb-meta-pill"><b>{k}</b> {v}</span>
                        ))}
                      </div>
                    )}
                    <Md text={body} />
                  </div>
                );
              })()}
            </>
          ) : (
            <div className="empty" style={{ margin: "auto" }}>
              <div className="big">📄</div>Select a note to read it.
            </div>
          )}
        </div>
      </div>
      )}

      {editing && <NoteEditor folders={folders} onClose={() => setEditing(false)}
        onSaved={() => { setEditing(false); load(q); }} />}
    </>
  );
}
