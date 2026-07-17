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


def _yaml_str(v) -> str:
    """Quote string values so titles with ':' or '#' stay valid YAML
    (Obsidian's properties panel rejects bare 'title: Task: foo')."""
    s = str(v)
    if isinstance(v, (int, float)) or re.fullmatch(r"[\w-]+", s):
        return s
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _frontmatter(meta: dict) -> str:
    lines = ["---"]
    for k, v in meta.items():
        if isinstance(v, (list, tuple)):
            lines.append(f"{k}: [{', '.join(_yaml_str(x) for x in v)}]")
        else:
            lines.append(f"{k}: {_yaml_str(v)}")
    lines.append("---\n")
    return "\n".join(lines)


def write_note(title: str, content: str, tags=None, meta_extra: dict = None,
               subdir: str = "") -> str:
    """Create a note with frontmatter. Returns the vault-relative path."""
    _ensure()
    # Obsidian tags cannot contain spaces — normalize everything to slugs.
    tags = [_slug(t, "tag") for t in (tags or [])]
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
    # [[Team Name]] is an intentional unresolved wikilink: create that note in
    # Obsidian and its backlinks/graph collect every output this team produced.
    body = (f"> Task: {task.strip()}\n\n"
            f"*Produced by team [[{team_name}]] — run #{run_id}*\n\n"
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
            title = tm.group(1).strip() if tm else fn[:-3]
            if len(title) > 1 and title[0] == '"' and title[-1] == '"':
                # _yaml_str quotes multiword titles; the UI wants them bare.
                title = title[1:-1].replace('\\"', '"').replace("\\\\", "\\")
            out.append({
                "path": rel,
                "title": title,
                "tags": [t.strip() for t in tagm.group(1).split(",") if t.strip()] if tagm else [],
                "size": st.st_size, "modified": st.st_mtime,
            })
    out.sort(key=lambda n: -n["modified"])
    return out


def read_note(rel: str, strip_meta: bool = False) -> str:
    with open(_safe_path(rel), encoding="utf-8") as f:
        text = f.read()
    return _strip_frontmatter(text) if strip_meta else text


# ---------------- vault structure: folders, delete, move, graph ----------------

def _safe_dir(rel: str) -> str:
    """Resolve a vault-relative FOLDER, refusing escapes and the vault root
    itself (deleting the root would destroy the whole brain in one call)."""
    rel = (rel or "").strip().strip("/")
    if not rel:
        raise ValueError("a folder inside the vault is required")
    full = os.path.realpath(os.path.join(KNOWLEDGE_DIR, rel))
    root = os.path.realpath(KNOWLEDGE_DIR)
    if not full.startswith(root + os.sep):
        raise ValueError("path escapes the knowledge vault")
    return full


def _prune_empty_dirs(start: str):
    """Remove now-empty folders upward, stopping at the vault root."""
    root = os.path.realpath(KNOWLEDGE_DIR)
    cur = os.path.realpath(start)
    while cur != root and cur.startswith(root + os.sep):
        try:
            os.rmdir(cur)  # only succeeds when empty
        except OSError:
            break
        cur = os.path.dirname(cur)


def delete_note(rel: str) -> dict:
    path = _safe_path(rel)
    if not os.path.isfile(path):
        return {"ok": False, "error": f"{rel} does not exist"}
    os.remove(path)
    _prune_empty_dirs(os.path.dirname(path))
    return {"ok": True, "error": None}


def delete_folder(rel: str) -> dict:
    """Delete a sub-vault (folder) and every note inside it."""
    import shutil
    try:
        full = _safe_dir(rel)
    except ValueError as e:
        return {"ok": False, "deleted": 0, "error": str(e)}
    if not os.path.isdir(full):
        return {"ok": False, "deleted": 0, "error": f"{rel} is not a folder"}
    count = sum(len([f for f in fs if f.endswith(".md")])
                for _, _, fs in os.walk(full))
    shutil.rmtree(full)
    _prune_empty_dirs(os.path.dirname(full))
    return {"ok": True, "deleted": count, "error": None}


def move_note(rel: str, folder: str) -> dict:
    """Move a note into a (possibly new) sub-vault. folder='' → vault root."""
    src = _safe_path(rel)
    if not os.path.isfile(src):
        return {"ok": False, "path": None, "error": f"{rel} does not exist"}
    folder = (folder or "").strip().strip("/")
    if folder:
        _safe_dir(folder)  # validate before creating anything
        os.makedirs(os.path.join(KNOWLEDGE_DIR, folder), exist_ok=True)
    dest = _unique_path(os.path.join(folder, os.path.basename(rel)))
    os.rename(src, dest)
    _prune_empty_dirs(os.path.dirname(src))
    return {"ok": True, "path": os.path.relpath(dest, KNOWLEDGE_DIR), "error": None}


def folders() -> list:
    """Top-level sub-vaults with note counts (root-level notes count as '')."""
    _ensure()
    root = os.path.realpath(KNOWLEDGE_DIR)
    counts = {}
    for base, _dirs, files in os.walk(root):
        n = len([f for f in files if f.endswith(".md")])
        if not n:
            continue
        rel = os.path.relpath(base, root)
        top = "" if rel == "." else rel.split(os.sep)[0]
        counts[top] = counts.get(top, 0) + n
    return [{"name": k, "notes": v} for k, v in sorted(counts.items())]


_WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)(?:[|#][^\]]*)?\]\]")


def _link_keys(title: str, path: str):
    """The names a wikilink may use to refer to this note (Obsidian matches
    the filename; people usually write the title)."""
    stem = os.path.basename(path)[:-3]
    undated = re.sub(r"^\d{4}-\d{2}-\d{2}-", "", stem)
    return {title.lower().strip(), stem.lower(), undated, _slug(title)}


def graph() -> dict:
    """Nodes and [[wikilink]] edges for the whole vault — Obsidian's graph
    view, computed server-side. Unresolved links become 'ghost' nodes, exactly
    like Obsidian renders them."""
    notes = list_notes()
    by_key = {}
    nodes = []
    for n in notes:
        folder = os.path.dirname(n["path"])
        top = folder.split(os.sep)[0] if folder else ""
        nodes.append({"id": n["path"], "title": n["title"], "folder": top,
                      "ghost": False})
        for k in _link_keys(n["title"], n["path"]):
            by_key.setdefault(k, n["path"])
    edges, ghosts = [], {}
    for n in notes:
        try:
            body = read_note(n["path"], strip_meta=True)
        except (OSError, ValueError):
            continue
        for m in _WIKILINK_RE.finditer(body):
            target = m.group(1).strip()
            hit = by_key.get(target.lower()) or by_key.get(_slug(target))
            if hit:
                if hit != n["path"]:
                    edges.append({"from": n["path"], "to": hit})
            else:
                gid = f"ghost:{_slug(target)}"
                if gid not in ghosts:
                    ghosts[gid] = {"id": gid, "title": target, "folder": "",
                                   "ghost": True}
                edges.append({"from": n["path"], "to": gid})
    nodes.extend(ghosts.values())
    # de-duplicate edges
    seen, uniq = set(), []
    for e in edges:
        key = (e["from"], e["to"])
        if key not in seen:
            seen.add(key)
            uniq.append(e)
    return {"nodes": nodes, "edges": uniq}


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
        # Curated notes out-rank auto-exported run outputs: otherwise agents
        # keep surfacing their own past (possibly wrong) deliverables first.
        if not note["path"].startswith("team-outputs/"):
            score += 1
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
