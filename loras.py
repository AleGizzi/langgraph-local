"""LoRA search + download for the Fooocus (SDXL) image-generation backend.

This module talks to two external contracts, both re-verified live against the
real services on 2026-07-12 (re-check if they break):

1) Civitai public REST API — GET https://civitai.com/api/v1/models
   Verified live with:
     curl "https://civitai.com/api/v1/models?query=pokemon+sprite&types=LORA&limit=5"
   Query params used here:
     - query      : free-text search string.
     - types      : "LORA" restricts to LoRA models (vs. Checkpoint/embedding/etc).
     - limit      : page size, **max 100** — the API 400s above that with a
                    ZodError ("Too big: expected number to be <=100").
   A `baseModels` param also exists (confirmed working, e.g.
   `baseModels=SDXL 1.0` filters server-side) but we deliberately do NOT send
   it: it only accepts exact Civitai enum strings ("SDXL 1.0", "SDXL
   Lightning", "Pony", "SD 1.5", ...) so a server-side filter would either
   need one request per exact variant or silently drop compatible-but-
   differently-labelled results. Instead we fetch broadly and classify
   compatibility ourselves per modelVersion (see `_is_compatible`) so
   incompatible results can still be *shown*, just flagged — the owner asked
   to "surface compatibility clearly", not hide mismatches.
   No auth is required for search/listing.

   Response shape (subset used here):
     {"items": [{
         "id": int, "name": str, "description": "<html>",
         "stats": {"downloadCount": int, ...},
         "modelVersions": [{
             "name": str, "baseModel": str,           # e.g. "SDXL 1.0", "SD 1.5", "Pony"
             "stats": {"downloadCount": int, ...},
             "files": [{"name": str, "sizeKB": float,
                        "primary": bool, "downloadUrl": str}, ...]
         }, ...]
     }, ...], "metadata": {...}}
   Confirmed live: a single model can list multiple modelVersions with
   *different* baseModel values (e.g. one SDXL version + one SD 1.5 version
   of the same LoRA) — so compatibility is a per-version, not per-model,
   property. This module emits one search result per modelVersion.

   Downloading: GET <file.downloadUrl> (a civitai.com/api/download/models/<id>
   URL that redirects to a signed CDN URL). Confirmed live: some files 401
   with `{"error":"Unauthorized","message":"The creator of this asset
   requires you to be logged in to download it"}` when fetched anonymously.
   Civitai's documented fix (developer.civitai.com/site/guide/authentication):
   send `Authorization: Bearer <api_key>` (an API key generated from the
   user's Civitai account settings). This module reads that key from the
   optional `CIVITAI_API_KEY` env var and, if set, sends it on every
   download; on a 401/403 it returns a clear error suggesting either setting
   that env var or downloading the file manually and dropping it into
   LORAS_DIR.

2) Fooocus-API `loras` request field — confirmed against the live source of
   mrhan1993/Fooocus-API (fooocusapi/models/common/base.py, `class Lora`):
     class Lora(BaseModel):
         enabled: bool
         model_name: str             # must match a file name in the loras dir
         weight: float = Field(default=0.5, ge=-2, le=2)
   used in `fooocusapi/models/common/requests.py`'s `CommonRequest.loras:
   List[Lora]`, which `POST /v1/generation/text-to-image` (imagegen.py's
   `generate()`) sends as JSON. So the wire shape is:
     "loras": [{"enabled": true, "model_name": "<file name in loras dir>",
                "weight": 0.8}, ...]
   Fooocus-API itself accepts weight in [-2, 2]; this module (and
   `imagegen.generate`) clamp to **[0, 2]** instead — negative weights invert
   a LoRA's effect, which isn't a use case this "style LoRA" feature exposes.

Only SDXL-family LoRAs (baseModel containing "SDXL", or "Pony" — which is an
SDXL-architecture finetune commonly used interchangeably) work on this app's
JuggernautXL/SDXL base. SD 1.5 LoRAs load without error but silently do
nothing on an SDXL base, which is why `search()` returns a `compatible` flag
per result instead of just omitting mismatches.
"""
import json
import os
import re
import threading
import time
from urllib.parse import urlparse

import requests

import imagegen

CIVITAI_API_URL = "https://civitai.com/api/v1/models"
LORA_FILE_EXTS = (".safetensors", ".pt", ".ckpt")

LORAS_DIR = os.environ.get(
    "FOOOCUS_LORAS_DIR",
    os.path.join(imagegen.FOOOCUS_DIR, "repositories", "Fooocus", "models", "loras"),
)

SEARCH_TIMEOUT = (10, 20)   # (connect, read) seconds
DOWNLOAD_TIMEOUT = (15, 120)

_downloads = {}   # key: sanitized file_name -> status dict (installer.py-style)
_lock = threading.Lock()

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")

# baseModel values (or substrings thereof) that work on an SDXL checkpoint.
SDXL_FAMILY_KEYWORDS = ("SDXL", "PONY")


def _clean_description(html: str) -> str:
    if not html:
        return ""
    text = _TAG_RE.sub(" ", html)
    text = _WS_RE.sub(" ", text).strip()
    return text[:200]


def _is_compatible(base_model_value: str, want: str) -> bool:
    v = (base_model_value or "").upper()
    w = (want or "SDXL").strip().upper()
    if w == "SDXL":
        return any(k in v for k in SDXL_FAMILY_KEYWORDS)
    return w in v


def search(query: str, base_model: str = "SDXL") -> dict:
    """Search Civitai for LoRAs. Never raises — timeout/HTTP/parse errors come
    back as {"ok": False, "results": [], "error": "..."}."""
    query = (query or "").strip()
    if not query:
        return {"ok": False, "results": [], "error": "query is required"}
    try:
        r = requests.get(
            CIVITAI_API_URL,
            params={"query": query, "types": "LORA", "limit": 30},
            timeout=SEARCH_TIMEOUT,
        )
        r.raise_for_status()
        data = r.json()
    except requests.RequestException as e:
        return {"ok": False, "results": [], "error": f"Civitai search failed: {e}"}
    except ValueError as e:  # bad JSON
        return {"ok": False, "results": [], "error": f"Civitai returned invalid JSON: {e}"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "results": [], "error": f"{type(e).__name__}: {e}"}

    results = []
    try:
        for item in data.get("items") or []:
            if not isinstance(item, dict):
                continue
            desc = _clean_description(item.get("description"))
            item_downloads = (item.get("stats") or {}).get("downloadCount", 0)
            for mv in item.get("modelVersions") or []:
                if not isinstance(mv, dict):
                    continue
                files = [f for f in (mv.get("files") or []) if isinstance(f, dict)]
                f = next((x for x in files if x.get("primary")), files[0] if files else None)
                if not f or not f.get("downloadUrl") or not f.get("name"):
                    continue
                base = mv.get("baseModel") or ""
                downloads = (mv.get("stats") or {}).get("downloadCount", item_downloads)
                model_id = item.get("id")
                version_id = mv.get("id")
                # Page a user can actually open to inspect the LoRA (samples,
                # licence, full description) — Civitai's own model page.
                source_url = (
                    f"https://civitai.com/models/{model_id}"
                    + (f"?modelVersionId={version_id}" if version_id else "")
                ) if model_id else None
                results.append({
                    "id": model_id,
                    "version_id": version_id,
                    "name": item.get("name") or "",
                    "version_name": mv.get("name") or "",
                    "base_model": base,
                    "file_name": f.get("name"),
                    "size_kb": f.get("sizeKB"),
                    "download_url": f.get("downloadUrl"),
                    "downloads": downloads or 0,
                    "description": desc,
                    # Words the LoRA was trained on: putting these in the prompt
                    # is often what actually activates its style.
                    "trigger_words": [w for w in (mv.get("trainedWords") or [])
                                      if isinstance(w, str)][:8],
                    "creator": ((item.get("creator") or {}).get("username")
                                if isinstance(item.get("creator"), dict) else None),
                    "nsfw": bool(item.get("nsfw")),
                    "source_url": source_url,
                    "compatible": _is_compatible(base, base_model),
                })
    except Exception as e:  # noqa: BLE001 - defensive: never let a shape surprise blow up
        return {"ok": False, "results": [], "error": f"unexpected response shape: {e}"}

    results.sort(key=lambda x: (not x["compatible"], -(x["downloads"] or 0)))
    return {"ok": True, "results": results, "error": None}


def _sanitize_file_name(file_name: str) -> str:
    name = os.path.basename((file_name or "").strip())
    if not name:
        raise ValueError("file_name is required")
    if not name.lower().endswith(LORA_FILE_EXTS):
        raise ValueError(f"file_name must end with one of {LORA_FILE_EXTS}")
    return name


def _set(key, **kw):
    with _lock:
        if key in _downloads:
            _downloads[key].update(kw)


def download_status() -> dict:
    with _lock:
        return {k: dict(v) for k, v in _downloads.items()}


def download(download_url: str, file_name: str, meta: dict = None) -> dict:
    """Start a background download of a LoRA file into LORAS_DIR. Returns
    immediately; poll download_status() for progress, keyed by file_name.

    `meta` (what the search result told us: description, source_url, trigger
    words, base model…) is persisted next to the file as `<file>.json` so the
    UI can still explain the LoRA long after the search results are gone.
    """
    try:
        name = _sanitize_file_name(file_name)
    except ValueError as e:
        return {"ok": False, "error": str(e)}

    url = (download_url or "").strip()
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return {"ok": False, "error": "download_url must be a valid http(s) URL"}

    with _lock:
        cur = _downloads.get(name)
        if cur and not cur.get("done"):
            return {"ok": False, "error": "already downloading"}
        _downloads[name] = {"file_name": name, "download_url": url,
                            "status": "starting", "progress": 0, "error": None,
                            "done": False, "started_at": time.time()}
    threading.Thread(target=_download_worker, args=(name, url, meta or {}),
                     daemon=True, name=f"lora-download-{name}").start()
    return {"ok": True, "error": None}


def _meta_path(name: str) -> str:
    return os.path.join(LORAS_DIR, name + ".json")


def _write_meta(name: str, meta: dict):
    """Sidecar with what this LoRA is and where it came from. Best effort."""
    if not meta:
        return
    keep = {k: meta.get(k) for k in
            ("name", "version_name", "description", "source_url", "base_model",
             "trigger_words", "creator", "downloads", "id", "version_id")
            if meta.get(k) not in (None, "", [])}
    keep["downloaded_at"] = time.time()
    try:
        with open(_meta_path(name), "w", encoding="utf-8") as f:
            json.dump(keep, f, ensure_ascii=False)
    except OSError:
        pass


def read_meta(name: str) -> dict:
    try:
        with open(_meta_path(name), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _download_worker(name: str, url: str, meta: dict = None):
    try:
        os.makedirs(LORAS_DIR, exist_ok=True)
        dest = os.path.join(LORAS_DIR, name)
        tmp_dest = dest + ".part"
        headers = {}
        api_key = os.environ.get("CIVITAI_API_KEY")
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        _set(name, status="connecting")
        with requests.get(url, headers=headers, stream=True,
                          timeout=DOWNLOAD_TIMEOUT, allow_redirects=True) as r:
            if r.status_code in (401, 403):
                _set(name, done=True, status="error",
                    error=(f"Download requires a Civitai account (HTTP "
                           f"{r.status_code}). Set the CIVITAI_API_KEY env var "
                           "to a key from your Civitai account settings, or "
                           f"download the file manually and drop it into "
                           f"{LORAS_DIR}."))
                return
            r.raise_for_status()
            total = int(r.headers.get("content-length") or 0)
            done_bytes = 0
            _set(name, status="downloading", progress=0)
            with open(tmp_dest, "wb") as f:
                for chunk in r.iter_content(chunk_size=1 << 20):
                    if not chunk:
                        continue
                    f.write(chunk)
                    done_bytes += len(chunk)
                    if total:
                        _set(name, progress=round(done_bytes / total * 100, 1),
                            status=f"downloading ({done_bytes >> 20} / {total >> 20} MB)")
                    else:
                        _set(name, status=f"downloading ({done_bytes >> 20} MB)")
        os.replace(tmp_dest, dest)
        _write_meta(name, meta or {})
        _set(name, done=True, progress=100, status="installed", error=None)
    except requests.RequestException as e:
        _set(name, done=True, status="error", error=f"download failed: {e}")
    except Exception as e:  # noqa: BLE001
        _set(name, done=True, status="error", error=f"{type(e).__name__}: {e}")


# LoRAs that Fooocus ships with (or that users drop in by hand) have no sidecar,
# so describe the ones we know about rather than showing a blank row.
KNOWN_LORAS = {
    "sd_xl_offset_example-lora_1.0.safetensors": {
        "description": "Stability AI's official SDXL offset-noise LoRA. Bundled "
                       "with Fooocus and applied by default at a low weight — it "
                       "deepens contrast and lets images render true blacks/whites "
                       "instead of washed-out greys.",
        "source_url": "https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0",
        "base_model": "SDXL 1.0", "builtin": True,
    },
    "sdxl_lcm_lora.safetensors": {
        "description": "LCM (Latent Consistency Model) distillation LoRA. This is "
                       "what the 'Extreme Speed' performance preset uses to generate "
                       "in ~8 steps instead of 30 — Fooocus loads it automatically, "
                       "so you don't need to select it.",
        "source_url": "https://huggingface.co/latent-consistency/lcm-lora-sdxl",
        "base_model": "SDXL 1.0", "builtin": True,
    },
    "sdxl_lightning_4step_lora.safetensors": {
        "description": "ByteDance SDXL-Lightning LoRA: 4-step generation, used by "
                       "the 'Lightning' performance preset. Loaded automatically.",
        "source_url": "https://huggingface.co/ByteDance/SDXL-Lightning",
        "base_model": "SDXL 1.0", "builtin": True,
    },
    "sdxl_hyper_sd_4step_lora.safetensors": {
        "description": "ByteDance Hyper-SD LoRA: another 4-step accelerator, used "
                       "by the 'Hyper-SD' preset. Loaded automatically.",
        "source_url": "https://huggingface.co/ByteDance/Hyper-SD",
        "base_model": "SDXL 1.0", "builtin": True,
    },
}


def list_local() -> list:
    """LoRA files in LORAS_DIR, each with whatever we know about it: the sidecar
    written at download time, or a builtin description for Fooocus's own files."""
    try:
        os.makedirs(LORAS_DIR, exist_ok=True)
    except OSError:
        return []
    out = []
    try:
        for entry in os.listdir(LORAS_DIR):
            if not entry.lower().endswith(LORA_FILE_EXTS):
                continue
            path = os.path.join(LORAS_DIR, entry)
            if not os.path.isfile(path):
                continue
            info = {"file_name": entry,
                    "size_mb": round(os.path.getsize(path) / (1024 * 1024), 1),
                    "description": "", "source_url": None, "trigger_words": [],
                    "base_model": None, "creator": None, "builtin": False}
            info.update({k: v for k, v in KNOWN_LORAS.get(entry, {}).items()})
            meta = read_meta(entry)
            info.update({k: v for k, v in meta.items() if v not in (None, "", [])})
            out.append(info)
    except OSError:
        return out
    # Builtins last: the user's own downloads are what they care about.
    out.sort(key=lambda x: (x.get("builtin", False), x["file_name"].lower()))
    return out


def identify(file_name: str) -> dict:
    """Backfill metadata for a LoRA that has no sidecar (downloaded before
    sidecars existed, or dropped into the folder by hand).

    Searches Civitai for the file's name and accepts only an exact file-name
    match, so we never mislabel a file with someone else's description.
    """
    try:
        name = _sanitize_file_name(file_name)
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    if not os.path.isfile(os.path.join(LORAS_DIR, name)):
        return {"ok": False, "error": "not found"}
    if name in KNOWN_LORAS:
        return {"ok": True, "meta": KNOWN_LORAS[name], "error": None}

    stem = re.sub(r"\.(safetensors|pt|ckpt)$", "", name, flags=re.I)
    query = re.sub(r"[_\-]+", " ", stem).strip()
    res = search(query)
    if not res.get("ok"):
        return {"ok": False, "error": res.get("error")}
    hit = next((r for r in res["results"]
                if (r.get("file_name") or "").lower() == name.lower()), None)
    if not hit:
        return {"ok": False,
                "error": f"no exact match for '{name}' on Civitai — it may be "
                         "private, renamed, or from another source"}
    _write_meta(name, hit)
    return {"ok": True, "meta": read_meta(name), "error": None}


def delete(file_name: str) -> dict:
    """Remove a LoRA file (and its sidecar) from LORAS_DIR."""
    try:
        name = _sanitize_file_name(file_name)
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    path = os.path.join(LORAS_DIR, name)
    # Confine to LORAS_DIR: never let a crafted name delete outside it.
    root = os.path.realpath(LORAS_DIR)
    if os.path.realpath(path) != os.path.join(root, name):
        return {"ok": False, "error": "invalid path"}
    if not os.path.isfile(path):
        return {"ok": False, "error": "not found"}
    try:
        os.remove(path)
    except OSError as e:
        return {"ok": False, "error": f"could not delete: {e}"}
    try:
        os.remove(_meta_path(name))
    except OSError:
        pass
    with _lock:
        _downloads.pop(name, None)
    return {"ok": True, "error": None}
