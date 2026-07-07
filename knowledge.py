"""Knowledge base: a plain-Markdown vault that teams read from and write to.

The whole design is deliberately dumb: it is just a folder of `.md` files with
YAML frontmatter and `[[wikilinks]]`. That means the folder *is* an Obsidian /
Logseq / Foam vault — point any of those at `KNOWLEDGE_DIR` and it just works.
No API, no login, no lock-in.

Run deliverables are auto-exported here so knowledge accumulates over time, and
agents get `knowledge_search` / `knowledge_read` / `knowledge_write` tools so
they can reference prior work and contribute new notes.
"""
import os
import re
import time

KNOWLEDGE_DIR = os.environ.get(
    "AGENTS_KNOWLEDGE",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "knowledge"),
)

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _ensure():
    os.makedirs(KNOWLEDGE_DIR, exist_ok=True)


def _slug(text: str, fallback: str = "note") -> str:
    s = _SLUG_RE.sub("-", (text or "").lower()).strip("-")
    return (s[:60] or fallback)


def _safe_path(rel: str) -> str:
    """Resolve a vault-relative path, refusing anything that escapes the vault."""
    rel = rel.strip().lstrip("/")
    if not rel.endswith(".md"):
        rel += ".md"
    full = os.path.realpath(os.path.join(KNOWLEDGE_DIR, rel))
    root = os.path.realpath(KNOWLEDGE_DIR)
    if full != root and not full.startswith(root + os.sep):
        raise ValueError("path escapes the knowledge vault")
    return full


def _unique_path(rel: str) -> str:
    """Return a non-colliding path, appending -2, -3, … if needed."""
    base = _safe_path(rel)
    if not os.path.exists(base):
        return base
    stem = base[:-3]
    i = 2
    while os.path.exists(f"{stem}-{i}.md"):
        i += 1
    return f"{stem}-{i}.md"


def _frontmatter(meta: dict) -> str:
    lines = ["---"]
    for k, v in meta.items():
        if isinstance(v, (list, tuple)):
            lines.append(f"{k}: [{', '.join(str(x) for x in v)}]")
        else:
            lines.append(f"{k}: {v}")
    lines.append("---\n")
    return "\n".join(lines)


def write_note(title: str, content: str, tags=None, meta_extra: dict = None,
               subdir: str = "") -> str:
    """Create a note with frontmatter. Returns the vault-relative path."""
    _ensure()
    tags = tags or []
    day = time.strftime("%Y-%m-%d")
    rel = os.path.join(subdir, f"{day}-{_slug(title)}.md") if subdir else f"{day}-{_slug(title)}.md"
    if subdir:
        os.makedirs(os.path.join(KNOWLEDGE_DIR, subdir), exist_ok=True)
    path = _unique_path(rel)
    meta = {"title": title, "created": time.strftime("%Y-%m-%d %H:%M"),
            "tags": tags}
    if meta_extra:
        meta.update(meta_extra)
    with open(path, "w", encoding="utf-8") as f:
        f.write(_frontmatter(meta))
        f.write(content.strip() + "\n")
    return os.path.relpath(path, KNOWLEDGE_DIR)


def export_run(run_id: int, team_name: str, task: str, final: str) -> str:
    """Auto-called when a run finishes: archive the deliverable as a note."""
    if not (final or "").strip():
        return ""
    title = task.strip().split("\n")[0][:70] or f"Run {run_id}"
    body = (f"> Task: {task.strip()}\n\n"
            f"*Produced by team **{team_name}** — [[runs]] #{run_id}*\n\n"
            f"---\n\n{final.strip()}")
    return write_note(
        title, body, tags=["team-output", _slug(team_name, "team")],
        meta_extra={"team": team_name, "run_id": run_id, "source": "team-run"},
        subdir="team-outputs")


# ---------------- reads / search ----------------

def _strip_frontmatter(text: str) -> str:
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            return text[end + 4:].lstrip("\n")
    return text


def list_notes() -> list:
    _ensure()
    out = []
    root = os.path.realpath(KNOWLEDGE_DIR)
    for base, _dirs, files in os.walk(root):
        for fn in files:
            if not fn.endswith(".md"):
                continue
            full = os.path.join(base, fn)
            rel = os.path.relpath(full, root)
            try:
                st = os.stat(full)
                with open(full, encoding="utf-8") as f:
                    head = f.read(600)
            except OSError:
                continue
            tm = re.search(r"^title:\s*(.+)$", head, re.M)
            tagm = re.search(r"^tags:\s*\[(.*)\]", head, re.M)
            out.append({
                "path": rel,
                "title": tm.group(1).strip() if tm else fn[:-3],
                "tags": [t.strip() for t in tagm.group(1).split(",") if t.strip()] if tagm else [],
                "size": st.st_size, "modified": st.st_mtime,
            })
    out.sort(key=lambda n: -n["modified"])
    return out


def read_note(rel: str, strip_meta: bool = False) -> str:
    with open(_safe_path(rel), encoding="utf-8") as f:
        text = f.read()
    return _strip_frontmatter(text) if strip_meta else text


def search(query: str, limit: int = 20) -> list:
    """Token-based search across note titles and bodies.

    Splits the query into words and ranks notes by how many distinct terms they
    contain (title matches weighted higher), so "Eiffel Tower height" still finds
    a note that says "the Eiffel Tower is 330 metres tall". Falls back to exact
    phrase matching for the snippet anchor.
    """
    raw = (query or "").strip().lower()
    if not raw:
        return []
    terms = [t for t in _SLUG_RE.sub(" ", raw).split() if len(t) > 1] or [raw]
    scored = []
    for note in list_notes():
        try:
            text = read_note(note["path"], strip_meta=True)
        except OSError:
            continue
        low = text.lower()
        title_low = note["title"].lower()
        matched = [t for t in terms if t in low or t in title_low]
        if not matched:
            continue
        score = len(matched) + sum(1 for t in terms if t in title_low)
        # Snippet anchored on the first matched term (or the phrase).
        anchor = low.find(raw)
        if anchor < 0:
            anchor = min((low.find(t) for t in matched if low.find(t) >= 0), default=0)
        start = max(0, anchor - 60)
        snippet = text[start:anchor + 130].replace("\n", " ").strip()
        scored.append((score, len(matched) == len(terms), {
            "path": note["path"], "title": note["title"],
            "snippet": ("…" + snippet + "…") if snippet else note["title"]}))
    # All-terms matches first, then by score.
    scored.sort(key=lambda s: (s[1], s[0]), reverse=True)
    return [r for _score, _all, r in scored[:limit]]


def stats() -> dict:
    notes = list_notes()
    return {"dir": KNOWLEDGE_DIR, "count": len(notes),
            "bytes": sum(n["size"] for n in notes)}
