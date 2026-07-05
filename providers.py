"""Model providers: Ollama (native API) and LM Studio (OpenAI-compatible API).

Both run locally. Discovery is fault tolerant: a provider that is down simply
returns no models instead of breaking the app.
"""
import os

import requests

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
LMSTUDIO_URL = os.environ.get("LMSTUDIO_URL", "http://localhost:1234/v1")

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


def make_llm(provider: str, model: str, temperature: float = 0.7,
             num_ctx: int = 8192):
    """Build a LangChain chat model for the given local provider."""
    if provider == "ollama":
        from langchain_ollama import ChatOllama
        return ChatOllama(
            base_url=OLLAMA_URL,
            model=model,
            temperature=temperature,
            num_ctx=num_ctx,
        )
    if provider == "lmstudio":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            base_url=LMSTUDIO_URL,
            api_key="lm-studio",
            model=model,
            temperature=temperature,
            streaming=True,
        )
    raise ValueError(f"Unknown provider: {provider}")
