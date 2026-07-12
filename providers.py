"""Model providers: Ollama (native API) and LM Studio (OpenAI-compatible API).

Both run locally. Discovery is fault tolerant: a provider that is down simply
returns no models instead of breaking the app.
"""
import os
import time

import requests

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
LMSTUDIO_URL = os.environ.get("LMSTUDIO_URL", "http://localhost:1234/v1")
FOOOCUS_URL = os.environ.get("FOOOCUS_URL", "http://localhost:8888")

# GPU coexistence guard: while the Fooocus image server is running it owns
# most of the GPU; letting Ollama offload then crashes its runner ("llama
# runner process has terminated"). When Fooocus is up we force Ollama to
# CPU-only inference — slower, but it works instead of crashing.
_gpu_guard = {"ts": 0.0, "up": False}


def image_server_running() -> bool:
    now = time.time()
    if now - _gpu_guard["ts"] > 10:
        try:
            requests.get(f"{FOOOCUS_URL}/ping", timeout=0.7)
            _gpu_guard["up"] = True
        except requests.RequestException:
            _gpu_guard["up"] = False
        _gpu_guard["ts"] = now
    return _gpu_guard["up"]

# Models that only produce embeddings; they can't chat so hide them.
_EMBED_HINTS = ("embed", "embedding", "bge-", "nomic-embed")


def _is_chat_model(name: str) -> bool:
    low = name.lower()
    return not any(h in low for h in _EMBED_HINTS)


def list_models() -> dict:
    """Return {"ollama": [...], "lmstudio": [...], "errors": {...}}."""
    out = {"ollama": [], "lmstudio": [], "errors": {}}
    try:
        r = requests.get(f"{OLLAMA_URL}/api/tags", timeout=3)
        r.raise_for_status()
        out["ollama"] = sorted(
            m["name"] for m in r.json().get("models", []) if _is_chat_model(m["name"])
        )
    except Exception as e:  # noqa: BLE001 - provider down is expected
        out["errors"]["ollama"] = str(e)
    try:
        r = requests.get(f"{LMSTUDIO_URL}/models", timeout=3)
        r.raise_for_status()
        out["lmstudio"] = sorted(
            m["id"] for m in r.json().get("data", []) if _is_chat_model(m["id"])
        )
    except Exception as e:  # noqa: BLE001
        out["errors"]["lmstudio"] = str(e)
    return out


def provider_status() -> dict:
    models = list_models()
    return {
        "ollama": {"up": "ollama" not in models["errors"], "url": OLLAMA_URL,
                   "models": len(models["ollama"])},
        "lmstudio": {"up": "lmstudio" not in models["errors"], "url": LMSTUDIO_URL,
                     "models": len(models["lmstudio"])},
    }


# Tunable generation hyperparameters exposed in the agent editor.
# (key, label, min, max, step, default, hint)
PARAM_SPECS = [
    ("temperature", "Temperature", 0.0, 2.0, 0.1, 0.7,
     "Randomness. Low = focused/deterministic, high = creative."),
    ("top_p", "Top-p", 0.05, 1.0, 0.05, 0.9,
     "Nucleus sampling: consider tokens covering this probability mass."),
    ("top_k", "Top-k", 1, 100, 1, 40,
     "Only sample from the k most likely tokens (Ollama only)."),
    ("repeat_penalty", "Repeat penalty", 1.0, 1.5, 0.05, 1.1,
     "Penalize repetition; >1.15 can hurt code output (Ollama only)."),
    ("num_ctx", "Context window", 1024, 32768, 1024, 8192,
     "Tokens of context. More = more RAM for KV cache (Ollama only)."),
    ("num_predict", "Max output tokens", 128, 8192, 128, 2048,
     "Cap on generated tokens per call."),
    ("seed", "Seed", 0, 999999, 1, None,
     "Fix for reproducible outputs; leave empty for random."),
]
PARAM_KEYS = {p[0] for p in PARAM_SPECS}


def clean_params(raw: dict) -> dict:
    """Validate/clamp a hyperparameter dict against PARAM_SPECS."""
    out = {}
    if not isinstance(raw, dict):
        return out
    for key, _label, lo, hi, _step, _default, _hint in PARAM_SPECS:
        if key not in raw or raw[key] in (None, ""):
            continue
        try:
            v = float(raw[key])
        except (TypeError, ValueError):
            continue
        v = min(hi, max(lo, v))
        if key in ("top_k", "num_ctx", "num_predict", "seed"):
            v = int(v)
        out[key] = v
    return out


# Watchdog: if a streaming call produces no chunk for this many seconds the
# call is aborted instead of hanging the run forever (observed with parallel
# 7B requests thrashing Ollama on small GPUs). Generous by default because
# evaluating a long prompt on CPU emits nothing for minutes before the first
# token appears.
LLM_IDLE_TIMEOUT = float(os.environ.get("LLM_IDLE_TIMEOUT", "420"))


def make_llm(provider: str, model: str, params: dict = None):
    """Build a LangChain chat model for the given local provider."""
    import httpx
    p = clean_params(params or {})
    idle = httpx.Timeout(LLM_IDLE_TIMEOUT, connect=10)
    if provider == "ollama":
        from langchain_ollama import ChatOllama
        return ChatOllama(
            base_url=OLLAMA_URL,
            model=model,
            temperature=p.get("temperature", 0.7),
            top_p=p.get("top_p"),
            top_k=p.get("top_k"),
            repeat_penalty=p.get("repeat_penalty"),
            num_ctx=p.get("num_ctx", 8192),
            num_predict=p.get("num_predict", 2048),
            seed=p.get("seed"),
            # CPU-only while the image server owns the GPU (see guard above).
            num_gpu=0 if image_server_running() else None,
            client_kwargs={"timeout": idle},
        )
    if provider == "lmstudio":
        from langchain_openai import ChatOpenAI
        kwargs = {}
        if "seed" in p:
            kwargs["seed"] = p["seed"]
        return ChatOpenAI(
            base_url=LMSTUDIO_URL,
            api_key="lm-studio",
            model=model,
            temperature=p.get("temperature", 0.7),
            top_p=p.get("top_p"),
            max_tokens=p.get("num_predict", 2048),
            streaming=True,
            timeout=idle,
            **kwargs,
        )
    raise ValueError(f"Unknown provider: {provider}")
