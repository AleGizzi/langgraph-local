"""AI news / local-LLM training resources, refreshed by a research agent.

A curated link store the user can grow by hand or refresh with an agent that
searches the web and reads pages. The agent returns structured items; we
de-dupe by URL and keep them. Categories keep news, trainings and tools apart.
"""
import json
import os
import re

import storage

CATEGORIES = {
    "news": "recent AI / LLM news and announcements",
    "training": "tutorials, courses and guides for running local LLMs "
                "(Ollama, llama.cpp, fine-tuning, quantization)",
    "tools": "open-source local-AI tools, models and frameworks worth knowing",
}

_WORKSPACE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "workspaces", "resources")

_PROMPT = """You are a research assistant curating links for a developer who runs
LOCAL open-source LLMs. Find CURRENT, high-quality {desc}.

Use web_search (and read_webpage if useful) to find real, working links. Prefer
primary sources (project sites, docs, reputable blogs, GitHub) over listicles.
Avoid paywalled or login-only pages.

Return ONLY a JSON array of up to {n} items, nothing else:
[{{"title": "...", "url": "https://...", "summary": "one sentence on why it's useful"}}]"""


def _extract_items(text: str) -> list:
    m = re.search(r"\[.*\]", text or "", re.DOTALL)
    if not m:
        return []
    try:
        data = json.loads(m.group(0))
    except ValueError:
        try:
            data = json.loads(re.sub(r",\s*([}\]])", r"\1", m.group(0)))
        except ValueError:
            return []
    out = []
    for it in data if isinstance(data, list) else []:
        if not isinstance(it, dict):
            continue
        url = str(it.get("url", "")).strip()
        if not url.startswith("http"):
            continue
        out.append({"title": str(it.get("title", url))[:300], "url": url,
                    "summary": str(it.get("summary", ""))[:600]})
    return out


def refresh(category: str = "news", n: int = 6,
            provider: str = None, model: str = None) -> dict:
    """Run the research agent for one category, store new links. Never raises."""
    import engine
    from providers import list_models
    if category not in CATEGORIES:
        return {"ok": False, "error": f"unknown category '{category}'", "added": 0}
    if not model:
        # A tool-capable model is required (web_search). qwen2.5 is the default.
        models = (list_models().get("ollama") or [])
        model = next((m for m in models if m.startswith("qwen2.5:")), None) \
            or next(iter(models), None)
        provider = "ollama"
    if not model:
        return {"ok": False, "error": "no local model available", "added": 0}

    os.makedirs(_WORKSPACE, exist_ok=True)
    agent = {"name": "Resource scout", "provider": provider or "ollama", "model": model,
             "system_prompt": "You are a precise web research assistant. You only "
                              "return real links you found via search.",
             "params": {"temperature": 0.3}, "tools": ["web_search", "read_webpage"],
             "skills": []}
    prompt = _PROMPT.format(desc=CATEGORIES[category], n=n)
    final, err = "", None
    try:
        for ev in engine.chat_stream(agent, [{"role": "user", "content": prompt}],
                                     _WORKSPACE, {}):
            if ev.get("type") == "done":
                final = ev.get("content") or final
            elif ev.get("type") == "error":
                err = ev.get("content")
    except Exception as e:  # noqa: BLE001
        err = f"{type(e).__name__}: {e}"
    if err and not final:
        return {"ok": False, "error": err, "added": 0}

    items = _extract_items(final)
    added = 0
    for it in items:
        if storage.add_resource({**it, "category": category, "source": "agent"}):
            added += 1
    return {"ok": True, "error": None, "added": added, "found": len(items),
            "model": model}
