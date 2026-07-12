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
                results.append({
                    "id": item.get("id"),
                    "name": item.get("name") or "",
                    "version_name": mv.get("name") or "",
                    "base_model": base,
                    "file_name": f.get("name"),
                    "size_kb": f.get("sizeKB"),
                    "download_url": f.get("downloadUrl"),
                    "downloads": downloads or 0,
                    "description": desc,
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


def download(download_url: str, file_name: str) -> dict:
    """Start a background download of a LoRA file into LORAS_DIR. Returns
    immediately; poll download_status() for progress, keyed by file_name."""
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
    threading.Thread(target=_download_worker, args=(name, url), daemon=True,
                     name=f"lora-download-{name}").start()
    return {"ok": True, "error": None}


def _download_worker(name: str, url: str):
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
        _set(name, done=True, progress=100, status="installed", error=None)
    except requests.RequestException as e:
        _set(name, done=True, status="error", error=f"download failed: {e}")
    except Exception as e:  # noqa: BLE001
        _set(name, done=True, status="error", error=f"{type(e).__name__}: {e}")


def list_local() -> list:
    """LoRA files currently sitting in LORAS_DIR. Creates the dir if missing."""
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
            if os.path.isfile(path):
                out.append({"file_name": entry,
                           "size_mb": round(os.path.getsize(path) / (1024 * 1024), 1)})
    except OSError:
        return out
    out.sort(key=lambda x: x["file_name"].lower())
    return out
