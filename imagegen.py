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

# How long generate() will poll a job before giving up. SDXL on a weak/low-VRAM
# GPU is SLOW (measured ~86s/step on a 4GB P600 → ~40min for 30 steps), so this
# is generous and configurable. Prefer a fast `performance` mode (below) over a
# huge timeout.
GEN_TIMEOUT = int(os.environ.get("IMAGEGEN_TIMEOUT", "2400"))

# Fooocus performance presets → diffusion steps. LCM/Lightning-distilled modes
# cut steps ~4-8x, which is the difference between usable and unusable on weak
# hardware. "Extreme Speed" (LCM, ~8 steps) is a safe fast default (no extra
# LoRA download); "Speed"/"Quality" are the full-step high-quality modes.
PERFORMANCE_MODES = ("Extreme Speed", "Lightning", "Hyper-SD", "Speed", "Quality")
DEFAULT_PERFORMANCE = os.environ.get("IMAGEGEN_PERFORMANCE", "Extreme Speed")

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

        # Install CUDA torch from the cu121 index. We do NOT pin exact versions:
        # the cu121 index drops old builds over time (e.g. 2.1.0 vanished, leaving
        # 2.2.0+), so a hard pin breaks. Latest cu121 wheels still support the
        # Pascal-class P600 (sm_61). Falls back to CPU torch if CUDA wheels fail.
        _set(key, status="installing torch (CUDA 12.1 wheels)", progress=80)
        r = _run([_venv_pip(), "install", "torch", "torchvision", "torchaudio",
                  "--index-url", TORCH_INDEX_URL], cwd=FOOOCUS_DIR)
        if r.returncode != 0:
            _set(key, status="CUDA torch unavailable — installing CPU torch",
                 progress=88)
            r = _run([_venv_pip(), "install", "torch", "torchvision", "torchaudio"],
                     cwd=FOOOCUS_DIR)
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


def _find_server_pids() -> list:
    """Locate running Fooocus-API server processes by their command line.

    The PID file alone is not enough: it goes stale across app restarts and
    manual launches, and a stale file used to make stop_server() silently kill
    nothing while still reporting success (the server then kept holding GPU+RAM,
    starving Ollama). Always fall back to scanning /proc.
    """
    pids = []
    main_py = os.path.join(FOOOCUS_DIR, "main.py")
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        try:
            with open(f"/proc/{entry}/cmdline", "rb") as f:
                cmd = f.read().decode("utf-8", "ignore")
        except OSError:
            continue
        if main_py in cmd:
            pids.append(int(entry))
    return pids


def _kill(pid: int, sig):
    try:
        os.killpg(os.getpgid(pid), sig)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            os.kill(pid, sig)
        except (ProcessLookupError, PermissionError, OSError):
            pass


def stop_server() -> dict:
    """Terminate the Fooocus-API server and VERIFY it is gone.

    Returns {"ok": False, "error": ...} if it survives — never claim success
    we can't confirm (freeing its GPU/RAM is the whole point).
    """
    pids = set(_find_server_pids())
    tracked = _read_pid()
    if tracked:
        pids.add(tracked)
    if not pids:
        try:
            os.remove(_pid_file())
        except OSError:
            pass
        return {"ok": True, "error": None}

    for pid in pids:
        _kill(pid, signal.SIGTERM)
    for _ in range(20):  # up to ~10s for a graceful exit
        time.sleep(0.5)
        if not _find_server_pids():
            break
    else:
        for pid in _find_server_pids():  # still there → force it
            _kill(pid, signal.SIGKILL)
        time.sleep(1)

    try:
        os.remove(_pid_file())
    except OSError:
        pass
    remaining = _find_server_pids()
    if remaining:
        return {"ok": False,
                "error": f"image server still running (pid {remaining[0]}) — "
                         "kill it manually"}
    return {"ok": True, "error": None}


# ---------------- Fooocus's own web UI (optional, separate install) ----------
# The API install (fooocus-api) is headless; the full Fooocus repo ships a
# Gradio UI. When cloned next to it as `fooocus-ui` (config.txt pointing at the
# API install's model folders, so the 6.7GB checkpoint is shared), we can run
# it standalone. Its pinned requirements matched the fooocus-api venv exactly
# at install time, so it reuses that venv — no second torch.
# NOT under ~/.local like the API install: gradio 3.41 403s any /file= path
# containing a dot-segment (`.local` counts) BEFORE consulting allowed_paths,
# which killed every css/js asset and left the UI's checkboxes dead. data/ is
# dot-free and gitignored.
FOOOCUS_UI_DIR = os.environ.get(
    "FOOOCUS_UI_DIR",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "fooocus-ui"))
FOOOCUS_UI_PORT = int(os.environ.get("FOOOCUS_UI_PORT", "7865"))


def _find_ui_pids() -> list:
    launch_py = os.path.join(FOOOCUS_UI_DIR, "launch.py")
    pids = []
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        try:
            with open(f"/proc/{entry}/cmdline", "rb") as f:
                cmd = f.read().decode("utf-8", "ignore")
        except OSError:
            continue
        if launch_py in cmd:
            pids.append(int(entry))
    return pids


def ui_status() -> dict:
    """`running` means Gradio actually answers HTTP — a live launch.py process
    that isn't serving yet is `starting`, so the UI doesn't open a dead tab."""
    serving = False
    try:
        requests.get(f"http://127.0.0.1:{FOOOCUS_UI_PORT}/", timeout=1.5)
        serving = True
    except requests.RequestException:
        pass
    return {"installed": os.path.isfile(os.path.join(FOOOCUS_UI_DIR, "launch.py")),
            "running": serving,
            "starting": (not serving) and bool(_find_ui_pids()),
            "url": f"http://127.0.0.1:{FOOOCUS_UI_PORT}",
            "dir": FOOOCUS_UI_DIR}


def start_ui_server() -> dict:
    """Launch Fooocus's own web UI. Stops the API server first — the 4GB GPU
    cannot hold two SDXL processes, so they are mutually exclusive."""
    try:
        st = ui_status()
        if st["running"]:
            return {"ok": True, "url": st["url"], "error": None}
        if not st["installed"]:
            return {"ok": False, "url": None,
                    "error": "Fooocus UI is not installed (expected at "
                             f"{FOOOCUS_UI_DIR})"}
        stopped = stop_server()
        if not stopped["ok"]:
            return {"ok": False, "url": None,
                    "error": "could not free the GPU: " + str(stopped["error"])}
        env = {**os.environ, "GRADIO_SERVER_PORT": str(FOOOCUS_UI_PORT)}
        log_path = os.path.join(FOOOCUS_UI_DIR, "ui.log")
        with open(log_path, "ab") as logf:
            subprocess.Popen(
                [_venv_python(), os.path.join(FOOOCUS_UI_DIR, "launch.py"),
                 "--listen", "127.0.0.1", "--always-low-vram",
                 "--disable-in-browser"],
                cwd=FOOOCUS_UI_DIR, stdout=logf, stderr=subprocess.STDOUT,
                start_new_session=True, env=env)
        return {"ok": True, "url": f"http://127.0.0.1:{FOOOCUS_UI_PORT}",
                "error": None}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "url": None, "error": f"{type(e).__name__}: {e}"}


def stop_ui_server() -> dict:
    """Terminate the Fooocus UI and verify it is gone (same contract as
    stop_server: never report a success we can't confirm)."""
    pids = set(_find_ui_pids())
    if not pids:
        return {"ok": True, "error": None}
    for pid in pids:
        _kill(pid, signal.SIGTERM)
    for _ in range(20):
        time.sleep(0.5)
        if not _find_ui_pids():
            break
    else:
        for pid in _find_ui_pids():
            _kill(pid, signal.SIGKILL)
        time.sleep(1)
    remaining = _find_ui_pids()
    if remaining:
        return {"ok": False, "error": f"Fooocus UI still running "
                                      f"(pid {remaining[0]}) — kill it manually"}
    return {"ok": True, "error": None}


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


def _write_meta(names: list, meta: dict):
    """Sidecar <image>.json per generated image: the prompt and settings that
    produced it. Best-effort — never blocks returning the image itself."""
    import json as _json
    for n in names:
        try:
            with open(_safe_images_path(n) + ".json", "w", encoding="utf-8") as f:
                _json.dump(meta, f, ensure_ascii=False)
        except (OSError, ValueError):
            continue


def image_meta(name: str) -> dict:
    import json as _json
    try:
        with open(_safe_images_path(name) + ".json", encoding="utf-8") as f:
            return _json.load(f)
    except (OSError, ValueError, _json.JSONDecodeError):
        return {}


def list_checkpoints() -> dict:
    """The base-model checkpoints (and LoRAs) Fooocus has on disk. Never raises.

    Fooocus-API exposes them at /v1/engines/all-models. An empty list is normal
    before the server has started — the picker then just shows "Fooocus default".
    """
    try:
        if not backend_status()["running"]:
            return {"ok": False, "models": [], "loras": [],
                    "error": "Fooocus-API server is not running — start it first"}
        r = requests.get(f"{FOOOCUS_URL}/v1/engines/all-models", timeout=(5, 20))
        r.raise_for_status()
        d = r.json() or {}
        return {"ok": True, "error": None,
                "models": [str(m) for m in (d.get("model_filenames") or [])],
                "loras": [str(l) for l in (d.get("lora_filenames") or [])]}
    except requests.RequestException as e:
        return {"ok": False, "models": [], "loras": [],
                "error": f"Fooocus-API request failed: {e}"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "models": [], "loras": [],
                "error": f"{type(e).__name__}: {e}"}


def _lora_entries(loras: list) -> list:
    out = []
    for item in loras or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("file_name") or "").strip()
        if not name:
            continue
        try:
            weight = float(item.get("weight", 0.8))
        except (TypeError, ValueError):
            weight = 0.8
        out.append({"enabled": True, "model_name": name,
                    "weight": max(0.0, min(2.0, weight))})
    return out


def _poll_job(job_id: str) -> tuple:
    """Poll a Fooocus-API job to completion. Returns (result_items, error)."""
    deadline = time.time() + GEN_TIMEOUT
    while time.time() < deadline:
        time.sleep(2)
        jr = requests.get(f"{FOOOCUS_URL}/v1/generation/query-job",
                          params={"job_id": job_id, "require_step_preview": False},
                          timeout=(10, 30))
        jr.raise_for_status()
        jd = jr.json()
        status_str = str(jd.get("job_status", "")).lower()
        stage_str = str(jd.get("job_stage", "")).lower()
        if "error" in status_str or "fail" in status_str \
                or "error" in stage_str or "fail" in stage_str:
            return None, (f"generation failed: "
                          f"{jd.get('job_stage') or jd.get('job_status')}")
        if status_str in ("finished", "success") or stage_str in ("finished", "success") \
                or jd.get("job_result"):
            return jd.get("job_result"), None
    return None, (f"timed out after {GEN_TIMEOUT}s — a low-VRAM GPU can be very "
                  f"slow; use a faster performance mode or check "
                  f"{FOOOCUS_DIR}/server.log")


def resume_job(backend_job_id: str, meta: dict) -> dict:
    """Poll a Fooocus job we already submitted and save its images.

    Fooocus keeps a job's result after it finishes, so if THIS app restarted
    mid-generation (a rebuild, a crash) we can still collect the image instead
    of losing 6 minutes of GPU work.
    """
    try:
        if not backend_status()["running"]:
            return {"ok": False, "images": [], "error": "image server is not running"}
        items, err = _poll_job(backend_job_id)
        if err:
            return {"ok": False, "images": [], "error": err}
        saved = _save_result_items(items)
        if not saved:
            return {"ok": False, "images": [], "error": "no images in the finished job"}
        _write_meta(saved, meta or {})
        return {"ok": True, "images": saved, "error": None}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "images": [], "error": f"{type(e).__name__}: {e}"}


def _run_job(path: str, body: dict, meta: dict, on_job_id=None) -> dict:
    """POST a generation job to `path`, poll it, save the images. Never raises.

    `on_job_id(id)` is called as soon as Fooocus accepts the job, so the caller
    can persist it and resume polling after a restart.
    """
    try:
        if not backend_status()["running"]:
            return {"ok": False, "images": [],
                    "error": "Fooocus-API server is not running — start it first"}
        r = requests.post(f"{FOOOCUS_URL}{path}", json=body, timeout=(10, 60))
        r.raise_for_status()
        data = r.json()
        job_id = data.get("job_id") if isinstance(data, dict) else None
        if job_id and on_job_id:
            try:
                on_job_id(job_id)
            except Exception:  # noqa: BLE001 - persistence must not break the job
                pass

        if not job_id:  # server answered synchronously despite async_process
            items = data if isinstance(data, list) else [data]
            saved = _save_result_items(items)
            if saved:
                _write_meta(saved, meta)
                return {"ok": True, "images": saved, "error": None}
            return {"ok": False, "images": [],
                    "error": "Fooocus-API returned neither a job_id nor an image"}

        items, err = _poll_job(job_id)
        if err:
            return {"ok": False, "images": [], "error": err}
        saved = _save_result_items(items)
        if not saved:
            return {"ok": False, "images": [],
                    "error": "job finished but no images were returned"}
        _write_meta(saved, meta)
        return {"ok": True, "images": saved, "error": None}
    except requests.RequestException as e:
        return {"ok": False, "images": [], "error": f"Fooocus-API request failed: {e}"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "images": [], "error": f"{type(e).__name__}: {e}"}


# How an existing image can be modified. Each maps to a Fooocus-API v2 endpoint
# (they take the source image as base64, which is why we use v2 here).
#   vary_*     : re-imagine the image, guided by your prompt (classic img2img)
#   upscale_*  : enlarge (prompt is largely ignored)
#   style      : ImagePrompt — borrow the image's look/content for a new image
#   structure  : PyraCanny — keep its edges/composition, restyle via prompt
#   depth      : CPDS — keep its depth/shape, restyle via prompt
#   face       : FaceSwap — carry a face across
#   outpaint   : extend the image outward (no mask needed)
MODIFY_MODES = {
    "vary_subtle":   {"endpoint": "/v2/generation/image-upscale-vary",
                      "uov_method": "Vary (Subtle)",
                      "label": "Vary (subtle) — small changes, same picture",
                      "description": "Re-generates the image staying very close to the "
                        "original. Good for cleaning up small glitches or getting a "
                        "slightly different take without changing the composition."},
    "vary_strong":   {"endpoint": "/v2/generation/image-upscale-vary",
                      "uov_method": "Vary (Strong)",
                      "label": "Vary (strong) — reinterpret it with your prompt",
                      "description": "Re-imagines the image with a lot of freedom, "
                        "steered by your prompt. The subject and layout survive, the "
                        "details, style and mood can change a lot."},
    "upscale_1_5x":  {"endpoint": "/v2/generation/image-upscale-vary",
                      "uov_method": "Upscale (1.5x)", "label": "Upscale 1.5×",
                      "description": "Makes the image 1.5× larger and re-diffuses it "
                        "for real added detail. Slower than the fast upscale but "
                        "sharper. The prompt is ignored."},
    "upscale_2x":    {"endpoint": "/v2/generation/image-upscale-vary",
                      "uov_method": "Upscale (2x)", "label": "Upscale 2×",
                      "description": "Doubles the resolution with re-diffusion for "
                        "real added detail — the slowest option here. The prompt is "
                        "ignored."},
    "upscale_fast":  {"endpoint": "/v2/generation/image-upscale-vary",
                      "uov_method": "Upscale (Fast 2x)",
                      "label": "Upscale 2× (fast, no re-diffusion)",
                      "description": "Doubles the resolution with a plain upscaler — "
                        "quick and safe, but adds no new detail. Use when you just "
                        "need a bigger file."},
    "style":         {"endpoint": "/v2/generation/image-prompt", "cn_type": "ImagePrompt",
                      "label": "Use as style/content reference",
                      "description": "Generates a NEW image from your prompt, using "
                        "this one as a look-and-feel reference. 'Influence' controls "
                        "how strongly it borrows."},
    "structure":     {"endpoint": "/v2/generation/image-prompt", "cn_type": "PyraCanny",
                      "label": "Keep its composition, restyle with prompt",
                      "description": "Traces the image's edges and keeps that layout "
                        "while your prompt repaints everything else — same scene, new "
                        "style or content."},
    "depth":         {"endpoint": "/v2/generation/image-prompt", "cn_type": "CPDS",
                      "label": "Keep its shapes/depth, restyle with prompt",
                      "description": "Preserves the 3D shapes and spatial depth of the "
                        "scene while your prompt changes materials, lighting and "
                        "style. Looser than composition mode."},
    "face":          {"endpoint": "/v2/generation/image-prompt", "cn_type": "FaceSwap",
                      "label": "Face swap",
                      "description": "Uses the face in this image on whatever your "
                        "prompt describes. Works best with a clear, front-facing "
                        "face."},
    "inpaint":       {"endpoint": "/v2/generation/image-inpaint-outpaint",
                      "needs_mask": True,
                      "label": "Inpaint — repaint only the painted area",
                      "description": "Paint over the part you want changed, describe "
                        "the replacement in the prompt, and only that region is "
                        "re-generated — the rest of the image stays untouched. Good "
                        "for removing objects, changing clothes/colors, fixing hands."},
    "outpaint":      {"endpoint": "/v2/generation/image-inpaint-outpaint",
                      "label": "Outpaint — extend the image outward",
                      "description": "Grows the canvas in the directions you pick and "
                        "invents matching content there. The original pixels stay; "
                        "the prompt (optional) guides what appears in the new areas."},
}


def _as_base64(source: str) -> str:
    """Accept a data: URL, a raw base64 string, or a gallery image filename."""
    s = (source or "").strip()
    if not s:
        raise ValueError("an image is required")
    if s.startswith("data:"):
        return s.split(",", 1)[1] if "," in s else ""
    if len(s) < 512 and not s.endswith("="):  # looks like a filename
        with open(_safe_images_path(s), "rb") as f:
            return base64.b64encode(f.read()).decode("ascii")
    return s


def modify(source: str, mode: str = "vary_strong", prompt: str = "",
           negative: str = "", performance: str = None, loras: list = None,
           styles: list = None, weight: float = 0.6, stop: float = 0.5,
           outpaint: list = None, aspect: str = "1152*896",
           mask: str = None, base_model: str = None, on_job_id=None) -> dict:
    """Modify an EXISTING image (img2img). `source` is a data URL, raw base64,
    or the filename of an image already in the gallery.

    `mask` (inpaint only) is a data URL / base64 image the same size as the
    source, where WHITE marks the region to repaint and black is kept.

    See MODIFY_MODES for what each mode does. Never raises.
    """
    spec = MODIFY_MODES.get(mode)
    if not spec:
        return {"ok": False, "images": [],
                "error": f"unknown mode '{mode}' (expected one of "
                         f"{', '.join(MODIFY_MODES)})"}
    try:
        img_b64 = _as_base64(source)
    except (OSError, ValueError) as e:
        return {"ok": False, "images": [], "error": f"could not read the image: {e}"}
    if not img_b64:
        return {"ok": False, "images": [], "error": "an image is required"}
    mask_b64 = ""
    if spec.get("needs_mask"):
        try:
            mask_b64 = _as_base64(mask) if mask else ""
        except (OSError, ValueError) as e:
            return {"ok": False, "images": [], "error": f"could not read the mask: {e}"}
        if not mask_b64:
            return {"ok": False, "images": [],
                    "error": "inpaint needs a mask — paint over the area to change"}

    perf = performance if performance in PERFORMANCE_MODES else DEFAULT_PERFORMANCE
    body = {
        "prompt": prompt, "negative_prompt": negative,
        "performance_selection": perf,
        "image_number": 1, "async_process": True,
    }
    if base_model:
        body["base_model_name"] = str(base_model)
    if styles is not None:
        body["style_selections"] = [str(s) for s in styles]
    entries = _lora_entries(loras)
    if entries:
        body["loras"] = entries

    if "uov_method" in spec:                       # vary / upscale
        body["input_image"] = img_b64
        body["uov_method"] = spec["uov_method"]
    elif "cn_type" in spec:                        # image prompt / controlnet
        body["image_prompts"] = [{
            "cn_img": img_b64, "cn_type": spec["cn_type"],
            "cn_weight": max(0.0, min(2.0, float(weight or 0.6))),
            "cn_stop": max(0.0, min(1.0, float(stop or 0.5))),
        }]
        body["aspect_ratios_selection"] = aspect
    elif spec.get("needs_mask"):                   # inpaint
        body["input_image"] = img_b64
        body["input_mask"] = mask_b64
        # Fooocus treats the additional prompt as "what goes in the hole";
        # the main prompt still steers the overall pass.
        body["inpaint_additional_prompt"] = prompt
    else:                                          # outpaint
        body["input_image"] = img_b64
        dirs = [d for d in (outpaint or ["Left", "Right"])
                if d in ("Left", "Right", "Top", "Bottom")]
        body["outpaint_selections"] = dirs or ["Left", "Right"]

    meta = {"prompt": prompt, "negative": negative, "performance": perf,
            "base_model": base_model or "",
            "mode": mode, "mode_label": spec["label"],
            "source": source if len(source or "") < 300 else "(uploaded image)",
            "loras": [{"file_name": e["model_name"], "weight": e["weight"]}
                      for e in entries],
            "created": time.time()}
    return _run_job(spec["endpoint"], body, meta, on_job_id=on_job_id)


def generate(prompt: str, negative: str = "", steps: int = None,
            aspect: str = "1152*896", performance: str = None,
            loras: list = None, styles: list = None, base_model: str = None,
            on_job_id=None) -> dict:
    """POST a text-to-image job to Fooocus-API and poll it to completion.

    `performance` picks a Fooocus preset (see PERFORMANCE_MODES); the default is
    a fast LCM/distilled mode so generation is tolerable on weak GPUs. `steps`
    optionally overrides the step count directly. `loras` is an optional list
    of {"file_name": str, "weight": float} — each becomes a Fooocus-API
    `Lora` entry {"enabled": true, "model_name": file_name, "weight": weight}
    (see loras.py's module docstring for where that shape was confirmed).
    Weights are clamped to [0, 2] (Fooocus-API itself allows [-2, 2], but
    negative weights aren't a use case this app exposes). Malformed entries
    are skipped rather than raising, per this module's "never raise" contract.

    `base_model` is a checkpoint filename from list_checkpoints(); omit it to
    let Fooocus use whatever it is configured with.
    """
    try:
        st = backend_status()
        if not st["running"]:
            return {"ok": False, "images": [],
                     "error": "Fooocus-API server is not running — start it "
                              "first (see backend_status/start_server)"}

        perf = performance if performance in PERFORMANCE_MODES else DEFAULT_PERFORMANCE
        body = {
            "prompt": prompt,
            "negative_prompt": negative,
            "aspect_ratios_selection": aspect,
            "performance_selection": perf,
            "image_number": 1,
            "async_process": True,
        }
        if base_model:
            body["base_model_name"] = str(base_model)
        if steps:
            body["advanced_params"] = {"overwrite_step": int(steps)}
        if styles is not None:
            # [] disables Fooocus's "Prompt Expansion" style, which otherwise
            # appends dozens of flavor words that dilute precise prompts
            # (learned generating creature sprites).
            body["style_selections"] = [str(s) for s in styles]
        if loras:
            lora_entries = []
            for item in loras:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("file_name") or "").strip()
                if not name:
                    continue
                try:
                    weight = float(item.get("weight", 0.8))
                except (TypeError, ValueError):
                    weight = 0.8
                weight = max(0.0, min(2.0, weight))
                lora_entries.append({"enabled": True, "model_name": name,
                                      "weight": weight})
            if lora_entries:
                body["loras"] = lora_entries

        r = requests.post(f"{FOOOCUS_URL}/v1/generation/text-to-image",
                          json=body, timeout=(10, 30))
        r.raise_for_status()
        data = r.json()
        job_id = data.get("job_id") if isinstance(data, dict) else None
        if job_id and on_job_id:
            try:
                on_job_id(job_id)
            except Exception:  # noqa: BLE001 - persistence must not break the job
                pass

        gen_meta = {"prompt": prompt, "negative": negative, "aspect": aspect,
                    "performance": perf, "base_model": base_model or "",
                    "loras": [{"file_name": i.get("file_name"),
                               "weight": i.get("weight")} for i in (loras or [])
                              if isinstance(i, dict)],
                    "created": time.time()}

        if not job_id:
            # Defensive: server replied synchronously despite async_process=True.
            items = data if isinstance(data, list) else [data]
            saved = _save_result_items(items)
            if saved:
                _write_meta(saved, gen_meta)
                return {"ok": True, "images": saved, "error": None}
            return {"ok": False, "images": [],
                     "error": "Fooocus-API did not return a job_id or an image"}

        deadline = time.time() + GEN_TIMEOUT
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
                     "error": f"timed out waiting for image generation "
                              f"({GEN_TIMEOUT}s) — a low-VRAM GPU can be very slow; "
                              "use a faster performance mode or check "
                              f"{FOOOCUS_DIR}/server.log"}

        saved = _save_result_items(result_items)
        if not saved:
            return {"ok": False, "images": [],
                     "error": "job finished but no images were returned"}
        _write_meta(saved, gen_meta)
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
        if name.endswith(".json"):  # metadata sidecars, not images
            continue
        path = os.path.join(IMAGES_DIR, name)
        if os.path.isfile(path):
            entries.append((os.path.getmtime(path), name))
    entries.sort(reverse=True)
    return [name for _, name in entries]
