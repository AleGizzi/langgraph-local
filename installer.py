"""Model installer: pulls models into Ollama (native API, streamed progress)
or LM Studio (lms CLI). Installs run in background threads; the UI polls.
"""
import json
import os
import shutil
import subprocess
import threading
import time

import requests

from providers import OLLAMA_URL

_installs = {}   # key "provider::model" -> state dict
_lock = threading.Lock()


def _key(provider, model):
    return f"{provider}::{model}"


def status_all():
    with _lock:
        return {k: dict(v) for k, v in _installs.items()}


def cancel(provider, model):
    with _lock:
        st = _installs.get(_key(provider, model))
        if st and not st.get("done"):
            st["cancel"] = True
            return True
    return False


def _lms_binary():
    return shutil.which("lms") or (
        os.path.expanduser("~/.lmstudio/bin/lms")
        if os.path.isfile(os.path.expanduser("~/.lmstudio/bin/lms")) else None)


def start(provider: str, model: str):
    key = _key(provider, model)
    with _lock:
        cur = _installs.get(key)
        if cur and not cur.get("done"):
            return {"ok": False, "error": "already installing"}
        _installs[key] = {"provider": provider, "model": model, "progress": 0,
                          "status": "starting", "error": None, "done": False,
                          "cancel": False, "started_at": time.time()}
    worker = _pull_ollama if provider == "ollama" else _pull_lmstudio
    threading.Thread(target=worker, args=(key, model), daemon=True,
                     name=f"install-{model}").start()
    return {"ok": True}


def _set(key, **kw):
    with _lock:
        _installs[key].update(kw)


def _cancelled(key):
    with _lock:
        return _installs[key].get("cancel")


def _pull_ollama(key, model):
    try:
        with requests.post(f"{OLLAMA_URL}/api/pull", json={"name": model},
                           stream=True, timeout=(10, 300)) as r:
            r.raise_for_status()
            for line in r.iter_lines():
                if _cancelled(key):
                    _set(key, done=True, status="cancelled")
                    return
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if ev.get("error"):
                    _set(key, done=True, error=ev["error"], status="error")
                    return
                status = ev.get("status", "")
                total, done = ev.get("total"), ev.get("completed")
                if total and done is not None:
                    _set(key, progress=round(done / total * 100, 1), status=status)
                else:
                    _set(key, status=status)
                if status == "success":
                    _set(key, done=True, progress=100, status="installed")
                    return
        _set(key, done=True, status="installed", progress=100)
    except Exception as e:  # noqa: BLE001
        _set(key, done=True, error=f"{type(e).__name__}: {e}", status="error")


# ---------------- provider installation (first-run wizard) ----------------

OLLAMA_RELEASES_API = "https://api.github.com/repos/ollama/ollama/releases/latest"
OLLAMA_HOME = os.path.expanduser("~/.local/share/local-agents-studio/ollama")
LMSTUDIO_DIR = os.path.expanduser("~/Applications")
# No 'latest' endpoint exists for LM Studio; probe known/likely versions.
LMSTUDIO_VERSIONS = ["0.4.20-1", "0.4.19-1", "0.4.18-1", "0.4.17-1", "0.4.16-1"]
LMSTUDIO_URL_TPL = "https://installers.lmstudio.ai/linux/x64/{v}/LM-Studio-{v}-x64.AppImage"


def in_docker() -> bool:
    return os.path.exists("/.dockerenv") or os.environ.get("RUNNING_IN_DOCKER") == "1"


def install_provider(provider: str):
    """Install Ollama (user-level, no sudo) or download LM Studio."""
    if in_docker():
        return {"ok": False, "error": "Running in Docker — Ollama is provided by "
                                      "the bundled service; nothing to install."}
    key = _key("setup", provider)
    with _lock:
        cur = _installs.get(key)
        if cur and not cur.get("done"):
            return {"ok": False, "error": "already installing"}
        _installs[key] = {"provider": "setup", "model": provider, "progress": 0,
                          "status": "starting", "error": None, "done": False,
                          "cancel": False, "started_at": time.time()}
    worker = _install_ollama if provider == "ollama" else _install_lmstudio
    threading.Thread(target=worker, args=(key,), daemon=True,
                     name=f"setup-{provider}").start()
    return {"ok": True}


def _download(key, url, dest, status_prefix):
    """Stream a download to dest with progress; honors cancel. Returns ok."""
    with requests.get(url, stream=True, timeout=(15, 120),
                      allow_redirects=True) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length") or 0)
        done = 0
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "wb") as f:
            for chunk in r.iter_content(chunk_size=1 << 20):
                if _cancelled(key):
                    return False
                f.write(chunk)
                done += len(chunk)
                if total:
                    _set(key, progress=round(done / total * 100, 1),
                         status=f"{status_prefix} ({done >> 20} / {total >> 20} MB)")
    return True


def _resolve_ollama_asset():
    """Find the plain linux-amd64 archive on the latest GitHub release."""
    r = requests.get(OLLAMA_RELEASES_API, timeout=15)
    r.raise_for_status()
    assets = r.json().get("assets", [])
    for suffix in ("ollama-linux-amd64.tgz", "ollama-linux-amd64.tar.zst",
                   "ollama-linux-amd64.tar.gz"):
        for a in assets:
            if a["name"] == suffix:
                return a["browser_download_url"], a["name"]
    raise RuntimeError("no linux-amd64 archive found on the latest Ollama release")


def _extract_archive(path, dest):
    import tarfile
    if path.endswith(".zst"):
        import zstandard
        with open(path, "rb") as f, \
                zstandard.ZstdDecompressor().stream_reader(f) as reader, \
                tarfile.open(fileobj=reader, mode="r|") as tf:
            tf.extractall(dest, filter="data")
    else:
        with tarfile.open(path) as tf:
            tf.extractall(dest, filter="data")


def _install_ollama(key):
    try:
        _set(key, status="finding latest Ollama release")
        url, asset_name = _resolve_ollama_asset()
        archive = os.path.join(OLLAMA_HOME, asset_name)
        if not _download(key, url, archive, "downloading Ollama"):
            _set(key, done=True, status="cancelled")
            return
        _set(key, status="extracting (this takes a minute)", progress=100)
        _extract_archive(archive, OLLAMA_HOME)
        os.unlink(archive)
        binary = os.path.join(OLLAMA_HOME, "bin", "ollama")
        os.chmod(binary, 0o755)
        # Put a symlink on the user's PATH for terminal use.
        local_bin = os.path.expanduser("~/.local/bin")
        os.makedirs(local_bin, exist_ok=True)
        link = os.path.join(local_bin, "ollama")
        if not os.path.exists(link):
            os.symlink(binary, link)
        _set(key, status="starting Ollama server")
        env = dict(os.environ)
        host = OLLAMA_URL.split("//", 1)[-1]
        env["OLLAMA_HOST"] = host
        subprocess.Popen([binary, "serve"], start_new_session=True, env=env,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(30):
            time.sleep(1)
            try:
                requests.get(f"{OLLAMA_URL}/api/version", timeout=2)
                _set(key, done=True, progress=100, status="installed")
                return
            except requests.RequestException:
                continue
        _set(key, done=True, status="error",
             error="Ollama installed but the server did not come up on "
                   f"{OLLAMA_URL} — try running 'ollama serve' in a terminal.")
    except Exception as e:  # noqa: BLE001
        _set(key, done=True, status="error", error=f"{type(e).__name__}: {e}")


def _install_lmstudio(key):
    try:
        _set(key, status="finding latest LM Studio release")
        url = None
        version = None
        for v in LMSTUDIO_VERSIONS:
            candidate = LMSTUDIO_URL_TPL.format(v=v)
            try:
                if requests.head(candidate, timeout=10,
                                 allow_redirects=True).status_code == 200:
                    url, version = candidate, v
                    break
            except requests.RequestException:
                continue
        if not url:
            _set(key, done=True, status="error",
                 error="Could not find an LM Studio release automatically — "
                       "download it from https://lmstudio.ai/download")
            return
        dest = os.path.join(LMSTUDIO_DIR, f"LM-Studio-{version}-x64.AppImage")
        if not _download(key, url, dest, f"downloading LM Studio {version}"):
            _set(key, done=True, status="cancelled")
            return
        os.chmod(dest, 0o755)
        _set(key, done=True, progress=100,
             status=f"downloaded to {dest} — launch it once to finish setup "
                    "(it is a desktop app), then start its server from the "
                    "Developer tab")
    except Exception as e:  # noqa: BLE001
        _set(key, done=True, status="error", error=f"{type(e).__name__}: {e}")


def _pull_lmstudio(key, model):
    lms = _lms_binary()
    if not lms:
        _set(key, done=True, status="error",
             error="lms CLI not found — install LM Studio first (see Setup page)")
        return
    try:
        # lms get downloads from the LM Studio catalog / Hugging Face.
        proc = subprocess.Popen([lms, "get", model, "--yes"],
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True)
        last = ""
        for line in proc.stdout:
            if _cancelled(key):
                proc.kill()
                _set(key, done=True, status="cancelled")
                return
            line = line.strip()
            if line:
                last = line[-160:]
                m = None
                for tok in line.replace("%", " % ").split():
                    if tok.replace(".", "", 1).isdigit() and 0 <= float(tok) <= 100:
                        m = float(tok)
                if m is not None and "%" in line:
                    _set(key, progress=m, status=last)
                else:
                    _set(key, status=last)
        code = proc.wait()
        if code == 0:
            _set(key, done=True, progress=100, status="installed")
        else:
            _set(key, done=True, status="error",
                 error=f"lms get exited with code {code}: {last}")
    except Exception as e:  # noqa: BLE001
        _set(key, done=True, error=f"{type(e).__name__}: {e}", status="error")
