"""System introspection: hardware specs, local provider installations, and
model suitability assessment ("can my PC run this?").

Sizing heuristics (GGUF Q4_K_M rule of thumb): the model file size is roughly
the RAM needed for weights; add ~2 GB overhead for KV-cache/context at 8k.
"""
import os
import re
import shutil
import subprocess

import requests

from providers import LMSTUDIO_URL, OLLAMA_URL, _is_chat_model

KV_OVERHEAD_GB = 2.0     # context/KV cache headroom per loaded model
OS_RESERVE_GB = 3.0      # keep this much RAM for the OS/desktop


def _read(path):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


def _run(cmd, timeout=5):
    try:
        return subprocess.run(cmd, capture_output=True, text=True,
                              timeout=timeout).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def _dir_size_gb(path):
    total = 0
    for base, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(base, f))
            except OSError:
                pass
    return round(total / 1e9, 1)


# ---------------- hardware ----------------

def hardware():
    cpuinfo = _read("/proc/cpuinfo")
    m = re.search(r"model name\s*:\s*(.+)", cpuinfo)
    cpu_model = m.group(1).strip() if m else "unknown"
    cores = os.cpu_count() or 1

    meminfo = _read("/proc/meminfo")
    def mem(key):
        mm = re.search(rf"{key}:\s+(\d+)", meminfo)
        return round(int(mm.group(1)) / 1024 / 1024, 1) if mm else 0.0
    ram_total, ram_avail = mem("MemTotal"), mem("MemAvailable")

    gpu = None
    smi = _run(["nvidia-smi", "--query-gpu=name,memory.total,memory.free",
                "--format=csv,noheader,nounits"])
    if smi:
        parts = [p.strip() for p in smi.splitlines()[0].split(",")]
        if len(parts) >= 3:
            gpu = {"name": parts[0], "vram_total_gb": round(int(parts[1]) / 1024, 1),
                   "vram_free_gb": round(int(parts[2]) / 1024, 1), "vendor": "nvidia"}
    if not gpu:
        lspci = _run(["lspci"])
        mm = re.search(r"(?:VGA|3D).*?:\s*(.+)", lspci)
        if mm:
            gpu = {"name": mm.group(1).strip(), "vram_total_gb": None,
                   "vram_free_gb": None, "vendor": "unknown"}

    st = os.statvfs(os.path.expanduser("~"))
    disk_free = round(st.f_bavail * st.f_frsize / 1e9, 1)
    return {"cpu": cpu_model, "cores": cores, "ram_total_gb": ram_total,
            "ram_available_gb": ram_avail, "gpu": gpu, "disk_free_gb": disk_free,
            "os": _run(["uname", "-sr"])}


# ---------------- installations ----------------

def _ollama_install():
    info = {"name": "Ollama", "installed": False, "running": False,
            "url": OLLAMA_URL, "port": None, "binary": None, "version": None,
            "models_dir": None, "models_size_gb": None, "service": None}
    mm = re.search(r":(\d+)", OLLAMA_URL.rsplit(":", 1)[-1] and OLLAMA_URL)
    info["port"] = int(OLLAMA_URL.rsplit(":", 1)[-1]) if OLLAMA_URL.rsplit(":", 1)[-1].isdigit() else 11434
    info["binary"] = shutil.which("ollama")
    info["installed"] = bool(info["binary"])
    try:
        r = requests.get(f"{OLLAMA_URL}/api/version", timeout=3)
        info["running"] = True
        info["version"] = r.json().get("version")
    except Exception:  # noqa: BLE001
        if info["binary"]:
            v = _run(["ollama", "--version"])
            vm = re.search(r"(\d+\.\d+[.\d]*)", v)
            info["version"] = vm.group(1) if vm else None
    candidates = [os.environ.get("OLLAMA_MODELS"),
                  "/usr/share/ollama/.ollama/models",
                  os.path.expanduser("~/.ollama/models")]
    best = None
    for c in candidates:
        if c and os.path.isdir(c):
            size = _dir_size_gb(c)
            if best is None or size > best[1]:
                best = (c, size)
    if best:
        info["models_dir"], info["models_size_gb"] = best
    if _run(["systemctl", "is-active", "ollama"]) == "active":
        info["service"] = "systemd (ollama.service)"
    return info


def _lmstudio_install():
    info = {"name": "LM Studio", "installed": False, "running": False,
            "url": LMSTUDIO_URL, "port": None, "binary": None, "version": None,
            "models_dir": None, "models_size_gb": None, "home": None, "service": None}
    pm = re.search(r":(\d+)", LMSTUDIO_URL)
    info["port"] = int(pm.group(1)) if pm else 1234
    home = os.path.expanduser("~/.lmstudio")
    legacy = os.path.expanduser("~/.cache/lm-studio")
    if os.path.isdir(home):
        info["home"] = home
    elif os.path.isdir(legacy):
        info["home"] = legacy
    info["installed"] = bool(info["home"])
    lms = shutil.which("lms") or (
        os.path.join(home, "bin", "lms") if os.path.isfile(os.path.join(home, "bin", "lms")) else None)
    info["binary"] = lms
    # Find the AppImage/desktop install if present.
    for d in ("~/Downloads", "~/Applications", "~/.local/bin", "/opt"):
        d = os.path.expanduser(d)
        if not os.path.isdir(d):
            continue
        for f in os.listdir(d):
            if re.match(r"(?i)lm[-_ ]?studio.*\.appimage", f):
                info["app"] = os.path.join(d, f)
                vm = re.search(r"(\d+\.\d+\.\d+)", f)
                info["version"] = info["version"] or (vm.group(1) if vm else None)
    md = os.path.join(info["home"], "models") if info["home"] else None
    if md and os.path.isdir(md):
        info["models_dir"] = md
        info["models_size_gb"] = _dir_size_gb(md)  # symlinked models count ~0
    try:
        requests.get(f"{LMSTUDIO_URL}/models", timeout=3)
        info["running"] = True
    except Exception:  # noqa: BLE001
        pass
    return info


INSTALL_GUIDES = {
    "ollama": {
        "title": "Install Ollama",
        "site": "https://ollama.com/download",
        "steps": [
            {"text": "Install with the official script", "cmd": "curl -fsSL https://ollama.com/install.sh | sh"},
            {"text": "The installer registers a systemd service; check it is running", "cmd": "systemctl status ollama"},
            {"text": "Pull a model suited to your hardware (see assessment below)", "cmd": "ollama pull qwen2.5:7b"},
            {"text": "Test it from the terminal", "cmd": "ollama run qwen2.5:7b \"hello\""},
            {"text": "The API listens on http://localhost:11434 by default. Models are stored in /usr/share/ollama/.ollama/models (service install) or ~/.ollama/models (user install)."},
        ],
    },
    "lmstudio": {
        "title": "Install LM Studio",
        "site": "https://lmstudio.ai/download",
        "steps": [
            {"text": "Download the Linux AppImage from lmstudio.ai/download"},
            {"text": "Make it executable and run it", "cmd": "chmod +x LM-Studio-*.AppImage && ./LM-Studio-*.AppImage"},
            {"text": "In the app: search and download a model (Discover tab), or reuse GGUFs you already have"},
            {"text": "Start the local server: Developer tab → Start Server (default port 1234)", "cmd": "~/.lmstudio/bin/lms server start"},
            {"text": "LM Studio keeps its files in ~/.lmstudio (models, config, the lms CLI in ~/.lmstudio/bin)."},
        ],
    },
}


# ---------------- model suitability ----------------

def _params_from_name(name):
    m = re.search(r"(\d+(?:\.\d+)?)\s*b\b", name.lower())
    return float(m.group(1)) if m else None


def _speed_estimate(params_b, gpu):
    """Very rough tokens/sec estimate for Q4 models on this machine."""
    if params_b is None:
        return None
    base = {1: 25, 2: 18, 4: 12, 8: 7, 15: 3.5, 35: 1.5, 75: 0.5}
    est = next(v for k, v in sorted(base.items()) if params_b <= k) if params_b <= 75 else 0.3
    if gpu and gpu.get("vendor") == "nvidia" and (gpu.get("vram_total_gb") or 0) >= 4:
        est *= 1.6  # partial offload bump
    return round(est, 1)


def _verdict(size_gb, ram_total, gpu):
    budget = ram_total - OS_RESERVE_GB
    need = size_gb + KV_OVERHEAD_GB
    if need <= budget * 0.55:
        return "great"
    if need <= budget * 0.8:
        return "ok"
    if need <= budget:
        return "tight"
    return "no"


VERDICT_LABEL = {
    "great": "Runs great — plenty of headroom",
    "ok": "Runs well",
    "tight": "Will run, but close to the RAM limit — expect swapping if much else is open",
    "no": "Not enough RAM — will not run reliably",
}


def assess():
    hw = hardware()
    ram = hw["ram_total_gb"]
    gpu = hw["gpu"]

    installed = []
    try:
        r = requests.get(f"{OLLAMA_URL}/api/tags", timeout=3)
        for m in r.json().get("models", []):
            if not _is_chat_model(m["name"]):
                continue
            size_gb = round(m["size"] / 1e9, 1)
            params = _params_from_name(m["name"]) or _params_from_name(
                m.get("details", {}).get("parameter_size", "") or "")
            v = _verdict(size_gb, ram, gpu)
            installed.append({
                "name": m["name"], "provider": "ollama", "size_gb": size_gb,
                "params_b": params, "quant": m.get("details", {}).get("quantization_level"),
                "verdict": v, "verdict_label": VERDICT_LABEL[v],
                "est_tok_s": _speed_estimate(params, gpu),
            })
    except Exception:  # noqa: BLE001
        pass

    # Parallel capacity: how many ~typical loaded models fit in RAM at once,
    # capped by CPU cores (inference is compute-bound) and — critically — by
    # the GPU: with partial offload (model bigger than VRAM), more than 2
    # concurrent generations thrash the runner (observed: 3rd request stalls).
    typical = max((i["size_gb"] for i in installed), default=4.7)
    by_ram = int(max(1, (ram - OS_RESERVE_GB) // (typical + KV_OVERHEAD_GB)))
    by_cpu = max(1, hw["cores"] // 4)
    caps = [by_ram, by_cpu, 4]
    gpu_note = ""
    if gpu and gpu.get("vram_total_gb") and gpu["vram_total_gb"] < typical + KV_OVERHEAD_GB:
        caps.append(2)
        gpu_note = (f" GPU has {gpu['vram_total_gb']} GB VRAM so models are "
                    "partially offloaded; more than 2 concurrent generations "
                    "would thrash it.")
    capacity = max(1, min(caps))
    return {
        "installed": installed,
        "parallel": {
            "capacity": capacity,
            "reason": (f"{ram} GB RAM fits ~{by_ram} loaded {typical} GB models; "
                       f"{hw['cores']} CPU threads support ~{by_cpu} concurrent "
                       f"generations.{gpu_note} Recommended max: {capacity}."),
        },
        "notes": [
            f"Rule of thumb: a Q4 model needs its file size in RAM plus ~{KV_OVERHEAD_GB:.0f} GB for context.",
            "GPU: " + (f"{gpu['name']} ({gpu['vram_total_gb']} GB VRAM) — Ollama will offload part of the model for a speed boost."
                       if gpu and gpu.get("vram_total_gb") else "no usable GPU detected — inference runs on CPU."),
            "Running agents in parallel loads/keeps multiple models in memory. Using the same model for all agents avoids reloading.",
        ],
    }


def full_report():
    return {
        "hardware": hardware(),
        "installations": {"ollama": _ollama_install(), "lmstudio": _lmstudio_install()},
        "guides": INSTALL_GUIDES,
        "assessment": assess(),
    }
