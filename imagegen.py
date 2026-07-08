"""Local image generation via Fooocus-API (mrhan1993/Fooocus-API).

Vanilla Fooocus (lllyasviel/Fooocus) is a Gradio UI with no stable REST
surface. Fooocus-API (https://github.com/mrhan1993/Fooocus-API) wraps it in a
FastAPI server, so we drive local image generation over plain HTTP instead of
scripting the Gradio UI. This module only *talks to* that server (installs it
into a venv, launches/stops it as a subprocess, POSTs/polls its REST API) —
no heavy ML deps (torch, etc.) are imported into this process.

Fooocus-API contract used below, confirmed against the project's README and
docs/api_doc_en.md (checked July 2026 — re-verify if these break):

  Install (Linux, requires python >= 3.10):
      git clone https://github.com/mrhan1993/Fooocus-API
      cd Fooocus-API
      python -m venv venv && source venv/bin/activate
      pip install -r requirements.txt
      pip install torch==2.1.0 torchvision==0.16.0 torchaudio==2.1.0 \
          --index-url https://download.pytorch.org/whl/cu121
  Model checkpoints are auto-downloaded by Fooocus into the repo on first
  server launch (multi-GB; not triggered by this module's install step).

  Launch:
      python main.py --host 127.0.0.1 --port 8888 --always-low-vram
  `--always-low-vram` is a native Fooocus flag (args_manager.py in the
  vendored Fooocus code) that Fooocus-API's own arg parser
  (fooocusapi/base_args.py) forwards through. It forces Fooocus's LOW_VRAM
  state + aggressive model offloading, which is what a 4GB Quadro P600
  needs (vs. the ~8GB+ Fooocus otherwise wants resident). Default port per
  fooocusapi/base_args.py: 8888.

  Health check: GET /ping -> 200 "pong".

  Text-to-image: POST /v1/generation/text-to-image, JSON body (subset):
      {
        "prompt": str, "negative_prompt": str,
        "aspect_ratios_selection": str (e.g. "1152*896"),
        "image_number": int, "async_process": bool,
        "advanced_params": {"overwrite_step": int}   # -1 = model default
      }
  With async_process=false the server blocks and replies once:
      {"base64": str|null, "url": str, "seed": int, "finish_reason": str}
  We always use async_process=true and poll instead, because a 4GB GPU can
  take minutes per image — long enough to blow past a normal HTTP timeout.
  The initial POST reply then carries a job_id; poll it via:
      GET /v1/generation/query-job?job_id=<id>&require_step_preview=false
  which returns:
      {"job_id", "job_type", "job_stage", "job_progress" (0-100),
       "job_status" ("Finished" on completion), "job_step_preview",
       "job_result": [{"base64": str|null, "url": str, "seed": int,
                        "finish_reason": "SUCCESS"}, ...]}
  Images are served by Fooocus-API itself as URLs
  (http://host:port/files/...) unless require_base64 was set on the
  request. We download the URL (or decode base64, if ever present) and
  save the bytes into IMAGES_DIR ourselves, so generated images survive
  independently of the Fooocus-API process.
"""
import base64
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid
from urllib.parse import urlparse

import requests

FOOOCUS_URL = os.environ.get("FOOOCUS_URL", "http://localhost:8888")
FOOOCUS_DIR = os.environ.get(
    "FOOOCUS_DIR",
    os.path.expanduser("~/.local/share/local-agents-studio/fooocus-api"),
)
IMAGES_DIR = os.environ.get(
    "IMAGES_DIR",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "images"),
)

REPO_URL = "https://github.com/mrhan1993/Fooocus-API"
TORCH_INDEX_URL = "https://download.pytorch.org/whl/cu121"

_installs = {}   # key "fooocus" -> state dict (mirrors installer.py's _installs)
_lock = threading.Lock()


def in_docker() -> bool:
    return os.path.exists("/.dockerenv") or os.environ.get("RUNNING_IN_DOCKER") == "1"


def _set(key, **kw):
    with _lock:
        if key in _installs:
            _installs[key].update(kw)


def _cancelled(key):
    with _lock:
        st = _installs.get(key)
        return bool(st and st.get("cancel"))


def install_status() -> dict:
    with _lock:
        st = _installs.get("fooocus")
        return dict(st) if st else {}


def _venv_python() -> str:
    return os.path.join(FOOOCUS_DIR, "venv", "bin", "python")


def _venv_pip() -> str:
    return os.path.join(FOOOCUS_DIR, "venv", "bin", "pip")


def _pid_file() -> str:
    return os.path.join(FOOOCUS_DIR, ".server.pid")


def _read_pid():
    try:
        with open(_pid_file()) as f:
            return int(f.read().strip())
    except (OSError, ValueError):
        return None


def _safe_images_path(name: str) -> str:
    """Resolve a filename inside IMAGES_DIR, refusing anything that escapes it."""
    name = os.path.basename(name.strip())
    full = os.path.realpath(os.path.join(IMAGES_DIR, name))
    root = os.path.realpath(IMAGES_DIR)
    if full != root and not full.startswith(root + os.sep):
        raise ValueError("path escapes the images dir")
    return full


def install_backend() -> dict:
    """Start a background install of Fooocus-API into FOOOCUS_DIR. Returns immediately."""
    if shutil.which("git") is None:
        return {"ok": False, "error": "git is required to install Fooocus-API "
                                       "but was not found on PATH"}
    with _lock:
        cur = _installs.get("fooocus")
        if cur and not cur.get("done"):
            return {"ok": False, "error": "already installing"}
        _installs["fooocus"] = {"status": "starting", "progress": 0, "error": None,
                                "done": False, "cancel": False,
                                "started_at": time.time()}
    threading.Thread(target=_install_worker, daemon=True,
                     name="install-fooocus").start()
    return {"ok": True, "error": None}


def _run(cmd, cwd=None):
    """Run a subprocess to completion, capturing output. Returns CompletedProcess."""
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)


def _install_worker():
    key = "fooocus"
    try:
        parent = os.path.dirname(FOOOCUS_DIR.rstrip(os.sep)) or "/"
        os.makedirs(parent, exist_ok=True)

        if _cancelled(key):
            _set(key, done=True, status="cancelled")
            return

        if not os.path.isdir(os.path.join(FOOOCUS_DIR, ".git")):
            _set(key, status="cloning Fooocus-API", progress=5)
            r = _run(["git", "clone", "--depth", "1", REPO_URL, FOOOCUS_DIR])
            if r.returncode != 0:
                _set(key, done=True, status="error",
                     error=f"git clone failed: {r.stderr[-2000:]}")
                return
        else:
            _set(key, status="repo already present", progress=20)

        if _cancelled(key):
            _set(key, done=True, status="cancelled")
            return

        if not os.path.isfile(_venv_python()):
            _set(key, status="creating virtualenv", progress=30)
            r = _run([sys.executable, "-m", "venv",
                      os.path.join(FOOOCUS_DIR, "venv")])
            if r.returncode != 0:
                _set(key, done=True, status="error",
                     error=f"venv creation failed: {r.stderr[-2000:]}")
                return

        if _cancelled(key):
            _set(key, done=True, status="cancelled")
            return

        req = os.path.join(FOOOCUS_DIR, "requirements.txt")
        _set(key, status="installing requirements (this can take several "
                          "minutes)", progress=45)
        r = _run([_venv_pip(), "install", "-r", req], cwd=FOOOCUS_DIR)
        if r.returncode != 0:
            _set(key, done=True, status="error",
                 error=f"pip install -r requirements.txt failed: "
                       f"{r.stderr[-2000:]}")
            return

        if _cancelled(key):
            _set(key, done=True, status="cancelled")
            return

        _set(key, status="installing torch (CUDA 12.1 wheels)", progress=80)
        r = _run([_venv_pip(), "install",
                  "torch==2.1.0", "torchvision==0.16.0", "torchaudio==2.1.0",
                  "--index-url", TORCH_INDEX_URL], cwd=FOOOCUS_DIR)
        if r.returncode != 0:
            _set(key, done=True, status="error",
                 error=f"torch install failed: {r.stderr[-2000:]}")
            return

        _set(key, done=True, progress=100, status="installed", error=None)
    except Exception as e:  # noqa: BLE001
        _set(key, done=True, status="error", error=f"{type(e).__name__}: {e}")


def backend_status() -> dict:
    installed = os.path.isdir(FOOOCUS_DIR) and os.path.isfile(_venv_python())
    running = False
    try:
        r = requests.get(f"{FOOOCUS_URL}/ping", timeout=1.5)
        running = r.ok
    except requests.RequestException:
        running = False
    with _lock:
        inst = dict(_installs.get("fooocus", {}))
    parsed = urlparse(FOOOCUS_URL)
    return {
        "installed": installed,
        "running": running,
        "url": FOOOCUS_URL,
        "port": parsed.port or 8888,
        "dir": FOOOCUS_DIR,
        "installing": bool(inst) and not inst.get("done", True),
        "error": inst.get("error"),
    }


def start_server() -> dict:
    """Launch the Fooocus-API server as a detached background process. No-op if running."""
    try:
        st = backend_status()
        if st["running"]:
            return {"ok": True, "error": None}
        if not st["installed"]:
            return {"ok": False,
                     "error": "Fooocus-API is not installed — run "
                              "install_backend() first"}
        main_py = os.path.join(FOOOCUS_DIR, "main.py")
        if not os.path.isfile(main_py):
            return {"ok": False, "error": f"main.py not found in {FOOOCUS_DIR}"}
        parsed = urlparse(FOOOCUS_URL)
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or 8888
        log_path = os.path.join(FOOOCUS_DIR, "server.log")
        with open(log_path, "ab") as logf:
            proc = subprocess.Popen(
                [_venv_python(), main_py, "--host", host, "--port", str(port),
                 "--always-low-vram"],
                cwd=FOOOCUS_DIR, stdout=logf, stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        try:
            with open(_pid_file(), "w") as f:
                f.write(str(proc.pid))
        except OSError:
            pass
        return {"ok": True, "error": None}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def stop_server() -> dict:
    """Best-effort terminate the tracked Fooocus-API server process."""
    pid = _read_pid()
    if pid:
        try:
            os.killpg(os.getpgid(pid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError, OSError):
            try:
                os.kill(pid, signal.SIGTERM)
            except (ProcessLookupError, PermissionError, OSError):
                pass
    try:
        os.remove(_pid_file())
    except OSError:
        pass
    return {"ok": True}


def _save_result_items(items) -> list:
    os.makedirs(IMAGES_DIR, exist_ok=True)
    saved = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        finish = item.get("finish_reason")
        if finish and str(finish).upper() != "SUCCESS":
            continue
        b64 = item.get("base64")
        url = item.get("url")
        ext = ".png"
        if url:
            try:
                guess = os.path.splitext(urlparse(url).path)[1]
                if guess:
                    ext = guess
            except ValueError:
                pass
        name = f"{int(time.time())}-{uuid.uuid4().hex[:8]}{ext}"
        try:
            dest = _safe_images_path(name)
        except ValueError:
            continue
        try:
            if b64:
                with open(dest, "wb") as f:
                    f.write(base64.b64decode(b64))
                saved.append(name)
            elif url:
                ir = requests.get(url, timeout=(10, 60))
                ir.raise_for_status()
                with open(dest, "wb") as f:
                    f.write(ir.content)
                saved.append(name)
        except Exception:  # noqa: BLE001 - skip this image, keep the rest
            continue
    return saved


def generate(prompt: str, negative: str = "", steps: int = None,
            aspect: str = "1152*896") -> dict:
    """POST a text-to-image job to Fooocus-API and poll it to completion."""
    try:
        st = backend_status()
        if not st["running"]:
            return {"ok": False, "images": [],
                     "error": "Fooocus-API server is not running — start it "
                              "first (see backend_status/start_server)"}

        body = {
            "prompt": prompt,
            "negative_prompt": negative,
            "aspect_ratios_selection": aspect,
            "image_number": 1,
            "async_process": True,
        }
        if steps:
            body["advanced_params"] = {"overwrite_step": int(steps)}

        r = requests.post(f"{FOOOCUS_URL}/v1/generation/text-to-image",
                          json=body, timeout=(10, 30))
        r.raise_for_status()
        data = r.json()
        job_id = data.get("job_id") if isinstance(data, dict) else None

        if not job_id:
            # Defensive: server replied synchronously despite async_process=True.
            items = data if isinstance(data, list) else [data]
            saved = _save_result_items(items)
            if saved:
                return {"ok": True, "images": saved, "error": None}
            return {"ok": False, "images": [],
                     "error": "Fooocus-API did not return a job_id or an image"}

        deadline = time.time() + 600
        result_items = None
        while time.time() < deadline:
            time.sleep(2)
            jr = requests.get(f"{FOOOCUS_URL}/v1/generation/query-job",
                              params={"job_id": job_id,
                                      "require_step_preview": False},
                              timeout=(10, 30))
            jr.raise_for_status()
            jd = jr.json()
            status_str = str(jd.get("job_status", "")).lower()
            stage_str = str(jd.get("job_stage", "")).lower()
            if "error" in status_str or "fail" in status_str \
                    or "error" in stage_str or "fail" in stage_str:
                return {"ok": False, "images": [],
                         "error": f"generation failed: "
                                  f"{jd.get('job_stage') or jd.get('job_status')}"}
            if status_str in ("finished", "success") \
                    or stage_str in ("finished", "success") \
                    or jd.get("job_result"):
                result_items = jd.get("job_result")
                break

        if result_items is None:
            return {"ok": False, "images": [],
                     "error": "timed out waiting for image generation (600s) — "
                              "a 4GB GPU can be slow, try again or check "
                              f"{FOOOCUS_DIR}/server.log"}

        saved = _save_result_items(result_items)
        if not saved:
            return {"ok": False, "images": [],
                     "error": "job finished but no images were returned"}
        return {"ok": True, "images": saved, "error": None}
    except requests.RequestException as e:
        return {"ok": False, "images": [], "error": f"Fooocus-API request failed: {e}"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "images": [], "error": f"{type(e).__name__}: {e}"}


def list_images() -> list:
    """Recent generated image basenames (newest first)."""
    if not os.path.isdir(IMAGES_DIR):
        return []
    entries = []
    for name in os.listdir(IMAGES_DIR):
        path = os.path.join(IMAGES_DIR, name)
        if os.path.isfile(path):
            entries.append((os.path.getmtime(path), name))
    entries.sort(reverse=True)
    return [name for _, name in entries]
