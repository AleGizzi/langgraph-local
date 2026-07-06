"""Live model catalog: discovers every model in the Ollama library by parsing
ollama.com (plain HTTP + regex — no AI involved), caches it on disk, and
refreshes automatically when stale.

- Index page (1 request) lists every model with sizes, capabilities and pulls.
- For the most popular models we also fetch exact download sizes per tag.
- Everything is cached in data/model_catalog.json; a built-in snapshot keeps
  the app useful offline.
"""
import json
import os
import re
import threading
import time

import requests

CACHE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "data", "model_catalog.json")
LIBRARY_URL = "https://ollama.com/library"
MAX_AGE_DAYS = 7          # auto-refresh when older than this
EXACT_SIZE_TOP_N = 45     # fetch per-tag exact sizes for the N most pulled
REQUEST_TIMEOUT = 20

_EMBED_HINTS = ("embed", "embedding", "bge-", "minilm", "reranker", "rerank")

# Offline fallback: a small snapshot so a fresh install without internet
# still gets a useful list (approximate sizes).
BUILTIN_SNAPSHOT = [
    {"name": "qwen2.5:0.5b", "base": "qwen2.5", "size_gb": 0.4, "params_b": 0.5},
    {"name": "qwen2.5:1.5b", "base": "qwen2.5", "size_gb": 1.0, "params_b": 1.5},
    {"name": "qwen2.5:3b", "base": "qwen2.5", "size_gb": 1.9, "params_b": 3},
    {"name": "qwen2.5:7b", "base": "qwen2.5", "size_gb": 4.7, "params_b": 7},
    {"name": "qwen2.5:14b", "base": "qwen2.5", "size_gb": 9.0, "params_b": 14},
    {"name": "qwen2.5:32b", "base": "qwen2.5", "size_gb": 20.0, "params_b": 32},
    {"name": "llama3.2:1b", "base": "llama3.2", "size_gb": 1.3, "params_b": 1},
    {"name": "llama3.2:3b", "base": "llama3.2", "size_gb": 2.0, "params_b": 3},
    {"name": "llama3.1:8b", "base": "llama3.1", "size_gb": 4.9, "params_b": 8},
    {"name": "mistral:7b", "base": "mistral", "size_gb": 4.1, "params_b": 7},
    {"name": "gemma2:9b", "base": "gemma2", "size_gb": 5.4, "params_b": 9},
    {"name": "qwen2.5-coder:7b", "base": "qwen2.5-coder", "size_gb": 4.7, "params_b": 7},
    {"name": "deepseek-r1:7b", "base": "deepseek-r1", "size_gb": 4.7, "params_b": 7},
]

_state = {"refreshing": False, "error": None}
_lock = threading.Lock()


def _params_from_label(label: str):
    m = re.fullmatch(r"(\d+(?:\.\d+)?)[bB]", label.strip())
    if m:
        return float(m.group(1))
    m = re.fullmatch(r"(\d+)[mM]", label.strip())
    if m:
        return round(int(m.group(1)) / 1000, 2)
    return None


def _estimate_size_gb(params_b: float) -> float:
    """Approximate Q4_K_M download size from parameter count."""
    return round(params_b * 0.62 + 0.15, 1)


def _is_embed(name: str, caps: list) -> bool:
    low = name.lower()
    return any(h in low for h in _EMBED_HINTS) or "embedding" in [c.lower() for c in caps]


def _pulls_to_number(text: str) -> float:
    m = re.match(r"([\d.]+)([KMB]?)", text.strip())
    if not m:
        return 0
    mult = {"": 1, "K": 1e3, "M": 1e6, "B": 1e9}[m.group(2)]
    return float(m.group(1)) * mult


def fetch_library_index(session) -> list:
    """One request: every model on ollama.com/library."""
    html = session.get(LIBRARY_URL, timeout=REQUEST_TIMEOUT).text
    models = []
    blocks = html.split('<a href="/library/')[1:]
    for block in blocks:
        slug = re.match(r'([a-z0-9._-]+)"', block)
        if not slug:
            continue
        slug = slug.group(1)
        desc = re.search(r"<p[^>]*>\s*([^<]{3,400}?)\s*</p>", block)
        caps = re.findall(r"x-test-capability[^>]*>([^<]+)</span>", block)
        sizes = re.findall(r"x-test-size[^>]*>([^<]+)</span>", block)
        pulls = re.search(r"x-test-pull-count>([^<]+)</span>", block)
        models.append({
            "slug": slug,
            "description": (desc.group(1).strip() if desc else ""),
            "capabilities": [c.strip() for c in caps],
            "size_labels": [s.strip() for s in sizes],
            "pulls": _pulls_to_number(pulls.group(1)) if pulls else 0,
            "pulls_label": pulls.group(1) if pulls else "",
        })
    return models


def fetch_exact_tags(session, slug: str) -> dict:
    """Per-model tags page → {tag: size_gb} for plain size tags + latest."""
    html = session.get(f"{LIBRARY_URL}/{slug}/tags", timeout=REQUEST_TIMEOUT).text
    out = {}
    # Tag name followed (within its chunk) by a size like '4.7GB'.
    for m in re.finditer(
            re.escape(slug) + r":([A-Za-z0-9._-]+)((?:(?!" + re.escape(slug) +
            r":)[\s\S]){0,600}?)([\d.]+)\s*(GB|MB)", html):
        tag, _mid, num, unit = m.group(1), m.group(2), m.group(3), m.group(4)
        if tag in out:
            continue
        # Only simple variants: latest or bare parameter-size tags.
        if tag != "latest" and not re.fullmatch(r"\d+(?:\.\d+)?[bm]", tag):
            continue
        size = float(num) / (1 if unit == "GB" else 1000)
        out[tag] = round(size, 2)
    return out


def refresh(blocking: bool = True):
    """Rebuild the catalog from ollama.com. No AI — pure HTTP + parsing."""
    def _work():
        _state["error"] = None
        try:
            session = requests.Session()
            session.headers["User-Agent"] = "local-agents-studio/1.0"
            index = fetch_library_index(session)
            index = [m for m in index if not _is_embed(m["slug"], m["capabilities"])]
            index.sort(key=lambda m: -m["pulls"])
            entries = []
            for rank, m in enumerate(index):
                exact = {}
                if rank < EXACT_SIZE_TOP_N:
                    try:
                        exact = fetch_exact_tags(session, m["slug"])
                    except Exception:  # noqa: BLE001 - keep going per model
                        pass
                labels = [l for l in m["size_labels"] if _params_from_label(l)]
                if exact:
                    for tag, size_gb in sorted(exact.items()):
                        if tag == "latest" and len(exact) > 1:
                            continue  # latest duplicates a size tag
                        params = _params_from_label(tag) if tag != "latest" else None
                        entries.append({
                            "name": f"{m['slug']}:{tag}" if tag != "latest" else m["slug"],
                            "base": m["slug"], "description": m["description"],
                            "capabilities": m["capabilities"],
                            "pulls_label": m["pulls_label"], "pulls": m["pulls"],
                            "size_gb": size_gb, "params_b": params, "exact": True,
                        })
                elif labels:
                    for label in labels:
                        params = _params_from_label(label)
                        entries.append({
                            "name": f"{m['slug']}:{label.lower()}",
                            "base": m["slug"], "description": m["description"],
                            "capabilities": m["capabilities"],
                            "pulls_label": m["pulls_label"], "pulls": m["pulls"],
                            "size_gb": _estimate_size_gb(params), "params_b": params,
                            "exact": False,
                        })
                else:
                    entries.append({
                        "name": m["slug"], "base": m["slug"],
                        "description": m["description"],
                        "capabilities": m["capabilities"],
                        "pulls_label": m["pulls_label"], "pulls": m["pulls"],
                        "size_gb": None, "params_b": None, "exact": False,
                    })
            data = {"fetched_at": time.time(), "source": "ollama.com",
                    "models": entries}
            os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
            with open(CACHE_PATH, "w", encoding="utf-8") as f:
                json.dump(data, f)
        except Exception as e:  # noqa: BLE001 - offline etc.
            _state["error"] = f"{type(e).__name__}: {e}"
        finally:
            _state["refreshing"] = False

    with _lock:
        if _state["refreshing"]:
            return False
        _state["refreshing"] = True
    if blocking:
        _work()
    else:
        threading.Thread(target=_work, daemon=True, name="catalog-refresh").start()
    return True


def load_cache():
    try:
        with open(CACHE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def get_catalog(auto_refresh: bool = True) -> dict:
    """Cached catalog; kicks off a background refresh when stale."""
    data = load_cache()
    stale = not data or (time.time() - data.get("fetched_at", 0)) > MAX_AGE_DAYS * 86400
    if stale and auto_refresh and not _state["refreshing"]:
        refresh(blocking=False)
    if not data:
        data = {"fetched_at": None, "source": "builtin",
                "models": [dict(m, description="", capabilities=[], pulls=0,
                                pulls_label="", exact=False)
                           for m in BUILTIN_SNAPSHOT]}
    data["refreshing"] = _state["refreshing"]
    data["error"] = _state["error"]
    return data
