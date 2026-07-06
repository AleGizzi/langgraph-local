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
