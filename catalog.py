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


# ---------------- categories, ranking, dream team (all heuristic, no AI) ----

CATEGORIES = {
    "general": {"icon": "💬", "label": "General chat & writing"},
    "coding": {"icon": "💻", "label": "Coding"},
    "thinking": {"icon": "🧠", "label": "Thinking / reasoning"},
    "vision": {"icon": "👁️", "label": "Vision (images)"},
    "agents": {"icon": "🛠️", "label": "Agents & tool use"},
    "fast": {"icon": "⚡", "label": "Tiny & fast"},
}

_CODING_RE = re.compile(
    r"\bcoder\b|codellama|codestral|starcoder|codegemma|devstral|deepseek-coder|"
    r"codeqwen|\bcode\b|\bcoding\b|\bprogramming\b", re.I)
_THINKING_RE = re.compile(
    r"deepseek-r1|qwq|reason|thinking|\bthink\b|o1|cogito|phi4-reasoning|"
    r"exaone-deep|openthinker|marco-o1", re.I)


def classify(entry: dict) -> list:
    """Assign use-case categories from registry capabilities + name/description."""
    caps = [c.lower() for c in entry.get("capabilities") or []]
    text = f"{entry.get('base', '')} {entry.get('description', '')}"
    cats = []
    if "vision" in caps:
        cats.append("vision")
    if "thinking" in caps or _THINKING_RE.search(text):
        cats.append("thinking")
    if _CODING_RE.search(text):
        cats.append("coding")
    if "tools" in caps:
        cats.append("agents")
    params = entry.get("params_b")
    if params is not None and params <= 4:
        cats.append("fast")
    if "coding" not in cats and "vision" not in cats:
        cats.append("general")
    return cats


# ---------------- local image-generation models (separate ecosystem) --------
# Image models don't run in Ollama — they run in ComfyUI / Fooocus / A1111 /
# diffusers. They are VRAM-bound, not RAM-bound, so they get their own
# assessment. (name, disk_gb, min_vram_gb, runner, tag, blurb)
IMAGE_MODELS = [
    ("SD 1.5", 2.0, 2, "ComfyUI / Automatic1111 / Fooocus", "classic",
     "The classic lightweight model. Runs on modest GPUs and even CPU (slowly). "
     "Huge ecosystem of LoRAs and fine-tunes."),
    ("SD-Turbo", 2.5, 2, "ComfyUI", "fast",
     "Distilled SD that generates in 1–4 steps — near real-time on small GPUs."),
    ("SDXL-Turbo", 6.9, 6, "ComfyUI / Fooocus", "fast",
     "Turbo variant of SDXL: high quality in a few steps, needs a mid-range GPU."),
    ("SDXL 1.0", 6.9, 8, "ComfyUI / Fooocus / Automatic1111", "quality",
     "The mainstream high-quality base model. Comfortable on 8 GB+ VRAM."),
    ("Stable Diffusion 3.5 Medium", 9.0, 9, "ComfyUI", "quality",
     "Newer architecture, strong prompt adherence; wants ~9 GB VRAM."),
    ("FLUX.1 [schnell]", 23.8, 12, "ComfyUI (fp8/GGUF quant ~8 GB)", "flagship",
     "State-of-the-art open model, 1–4 steps. Full weights need lots of VRAM; "
     "quantized GGUF builds run on ~8–12 GB."),
    ("FLUX.1 [dev]", 23.8, 16, "ComfyUI", "flagship",
     "Highest-quality FLUX variant; needs a large GPU (or heavy quantization)."),
]

IMAGE_SETUP = {
    "title": "Running image models locally",
    "note": ("Image generation uses a different runtime than Ollama. Install one "
             "of these once, then load a model below into it:"),
    "runners": [
        {"name": "Fooocus", "url": "https://github.com/lllyasviel/Fooocus",
         "blurb": "Easiest start — one-click, SDXL out of the box, minimal settings."},
        {"name": "ComfyUI", "url": "https://github.com/comfyanonymous/ComfyUI",
         "blurb": "Node-based and powerful; supports every model here including FLUX."},
        {"name": "Automatic1111", "url": "https://github.com/AUTOMATIC1111/stable-diffusion-webui",
         "blurb": "The classic web UI; great for SD 1.5 / SDXL and extensions."},
    ],
}


def image_models(hardware: dict) -> dict:
    """Assess curated image-gen models against this machine's GPU/RAM."""
    gpu = hardware.get("gpu") or {}
    vram = gpu.get("vram_total_gb")
    ram = hardware.get("ram_total_gb", 0)
    out = []
    for name, disk, min_vram, runner, tag, blurb in IMAGE_MODELS:
        if vram and vram >= min_vram:
            verdict = "great" if vram >= min_vram * 1.4 else "ok"
            note = f"Fits your {vram} GB GPU."
        elif vram and vram >= min_vram * 0.6:
            verdict = "tight"
            note = (f"Above your {vram} GB VRAM — needs offloading/quantization "
                    "and will be slow.")
        elif ram >= min_vram + 4:
            # CPU/RAM offload is possible for the small models, very slowly.
            verdict = "tight" if min_vram <= 2 else "no"
            note = ("No GPU headroom; CPU generation is possible but very slow."
                    if verdict == "tight" else
                    f"Needs ~{min_vram} GB VRAM; not practical on this GPU.")
        else:
            verdict = "no"
            note = f"Needs ~{min_vram} GB VRAM."
        out.append({"name": name, "disk_gb": disk, "min_vram_gb": min_vram,
                    "runner": runner, "tag": tag, "description": blurb,
                    "verdict": verdict, "verdict_label": note})
    runnable = [m for m in out if m["verdict"] in ("great", "ok", "tight")]
    best = max((m for m in out if m["verdict"] in ("great", "ok")),
               key=lambda m: m["min_vram_gb"], default=None) or \
        next((m for m in out if m["verdict"] == "tight"), None)
    return {"models": out, "setup": IMAGE_SETUP, "best": best,
            "runnable_count": len(runnable)}


def annotate(models: list) -> dict:
    """Add categories + per-category family rank to each model, and build the
    dream team: the best model for each use case that runs on this machine.

    Ranking = family popularity (pulls) among families with at least one
    runnable variant; dream-team pick = largest variant of the top family
    whose verdict is 'great' (falling back to 'ok').
    """
    for m in models:
        m["categories"] = classify(m)

    fam_rank = {}
    dream = []
    for cat in CATEGORIES:
        fams = {}
        for m in models:
            if cat in m["categories"]:
                fams.setdefault(m["base"], {"pulls": m.get("pulls", 0), "models": []})
                fams[m["base"]]["models"].append(m)
        runnable = {b: f for b, f in fams.items()
                    if any(x.get("verdict") in ("great", "ok") for x in f["models"])}
        ordered = sorted(runnable, key=lambda b: -runnable[b]["pulls"])
        for i, base in enumerate(ordered):
            fam_rank[(cat, base)] = i + 1
        if ordered:
            top = runnable[ordered[0]]["models"]
            pick = max((x for x in top if x.get("verdict") == "great" and x.get("params_b")),
                       key=lambda x: x["params_b"], default=None)
            fallback = "great"
            if not pick:
                fallback = "ok"
                pick = max((x for x in top if x.get("verdict") == "ok" and x.get("params_b")),
                           key=lambda x: x["params_b"], default=None)
            if pick:
                dream.append({
                    "category": cat, **CATEGORIES[cat], "model": pick["name"],
                    "size_gb": pick["size_gb"], "verdict": pick["verdict"],
                    "est_tok_s": pick.get("est_tok_s"),
                    "installed": pick.get("installed", False),
                    "reason": (f"Most popular {CATEGORIES[cat]['label'].lower()} family "
                               f"on Ollama ({pick.get('pulls_label', '?')} pulls) — "
                               f"{pick['name'].split(':')[-1]} is the largest variant that "
                               + ("runs great on this PC."
                                  if fallback == "great" else "runs well on this PC.")),
                })

    for m in models:
        m["ranks"] = {c: fam_rank[(c, m["base"])] for c in m["categories"]
                      if (c, m["base"]) in fam_rank}
    return {"dream_team": dream}


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
