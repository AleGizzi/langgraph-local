import React, { useEffect, useState } from "react";
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

function NoteEditor({ onClose, onSaved }) {
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const save = async () => {
    if (!title.trim() || !content.trim()) { toast("Title and content required", true); return; }
    try {
      await api("/knowledge/note", { method: "POST", body: { title, content } });
      toast("Note saved to the vault");
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
            <label>Content (Markdown — use [[wikilinks]] to relate notes)</label>
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

export default function Knowledge() {
  const [data, setData] = useState(null);
  const [q, setQ] = useState("");
  const [selected, setSelected] = useState(null);
  const [noteText, setNoteText] = useState("");
  const [editing, setEditing] = useState(false);

  const load = (query = "") => {
    const url = query ? `/knowledge?q=${encodeURIComponent(query)}` : "/knowledge";
    api(url).then(setData).catch(() => {});
  };
  useEffect(() => { load(); }, []);

  useEffect(() => {
    if (!selected) { setNoteText(""); return; }
    api(`/knowledge/note?path=${encodeURIComponent(selected)}`)
      .then((d) => setNoteText(d.content)).catch(() => setNoteText("(could not read note)"));
  }, [selected]);

  const items = data ? (data.results || data.notes || []) : [];

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
        <button className="btn primary" onClick={() => setEditing(true)}>＋ New note</button>
      </div>

      {data && (
        <div className="kb-vaultbar">
          <span className="help">
            📁 <code>{data.stats.dir}</code> · {data.stats.count} notes
          </span>
          <span className="help">
            Open this folder in <strong>Obsidian</strong>, <strong>Logseq</strong> or
            <strong> Foam</strong> — it is a standard vault, no import needed.
          </span>
        </div>
      )}

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
            {items.map((n) => (
              <div key={n.path}
                className={"kb-item" + (selected === n.path ? " active" : "")}
                onClick={() => setSelected(n.path)}>
                <div className="kb-item-title">{n.title}</div>
                {n.snippet
                  ? <div className="kb-item-sub">{n.snippet}</div>
                  : <div className="kb-item-sub">{(n.tags || []).join(", ")} · {fmtTime(n.modified)}</div>}
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
                <button className="btn sm" onClick={() =>
                  navigator.clipboard.writeText(noteText).then(() => toast("Copied"))}>Copy</button>
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

      {editing && <NoteEditor onClose={() => setEditing(false)}
        onSaved={() => { setEditing(false); load(q); }} />}
    </>
  );
}
