"""Classifier-router + model-tier picker for local models.

The local analogue of routing between cloud model tiers: one CHEAP call with a
small fast model classifies a request, then we hand the whole thing to the
best-suited specialist / model. Classify-once-then-dispatch is deliberately NOT
a supervisor loop — on local 7Bs a looping orchestrator re-reads growing
context every hop and often costs more tokens than it saves.
"""
import json
import re

# Task kind → the model TIER best suited to it, most-preferred first. Resolved
# against what's actually installed at call time (fallbacks below).
TIER_PREFERENCE = {
    "trivial":   ["gemma3:4b", "qwen2.5:7b", "llama3.1:8b", "mistral"],
    "general":   ["qwen2.5:7b", "llama3.1:8b", "gemma3:12b", "mistral"],
    "code":      ["qwen2.5-coder:7b", "qwen2.5-coder:14b", "qwen2.5-coder:3b",
                  "qwen2.5:7b"],
    "code_hard": ["qwen2.5-coder:14b", "qwen2.5-coder:7b", "qwen2.5:7b"],
    "research":  ["qwen2.5:7b", "llama3.1:8b", "gemma3:12b"],
    "reasoning": ["qwen2.5-coder:14b", "qwen3:30b-a3b", "deepseek-r1:14b",
                  "qwen2.5:7b"],
    "creative":  ["qwen2.5:7b", "gemma3:12b", "llama3.1:8b"],
}

# Tools each kind should get (empty = none).
KIND_TOOLS = {
    "research": ["web_search", "read_webpage"],
    "code": ["files", "run_python"],
    "code_hard": ["files", "run_python"],
}

_CLASSIFY_PROMPT = """Classify this request into exactly one kind. Reply with ONLY
a JSON object, no other text:
{{"kind": "<one of: trivial, general, code, code_hard, research, reasoning, creative>", "reason": "<8 words max>"}}

Kinds:
- trivial: a greeting, a one-line fact, a tiny transformation. Cheapest model.
- general: a normal question or short writing task.
- code: writing or fixing a small/medium program.
- code_hard: a large, multi-file or tricky program needing the strongest coder.
- research: needs current info from the web.
- reasoning: multi-step logic, math, planning, careful analysis.
- creative: story, brainstorm, marketing copy, tone-heavy writing.

Request:
{request}

JSON:"""


def _installed(models: dict) -> list:
    out = []
    for prov in ("ollama", "lmstudio"):
        for m in (models.get(prov) or []):
            out.append((prov, m))
    return out


def pick_model_for_kind(kind: str, models: dict):
    """(provider, model) for a kind, snapped to what's installed."""
    inst = _installed(models)
    by_name = {m: (p, m) for p, m in inst}
    for want in TIER_PREFERENCE.get(kind, TIER_PREFERENCE["general"]):
        # exact, then prefix match (qwen2.5:7b matches qwen2.5:7b-instruct-…)
        if want in by_name:
            return by_name[want]
        for p, m in inst:
            if m.startswith(want):
                return (p, m)
    return inst[0] if inst else ("ollama", "")


def _classify_model(models: dict):
    """A small, fast, non-reasoning model to run the classification itself."""
    for want in ("gemma3:4b", "qwen2.5:7b", "llama3.1:8b", "mistral", "gemma3"):
        for prov in ("ollama", "lmstudio"):
            for m in (models.get(prov) or []):
                if m.startswith(want) and not re.search(r"r1|think|qwen3", m, re.I):
                    return prov, m
    inst = _installed(models)
    return inst[0] if inst else ("ollama", "")


def classify(request: str, models: dict) -> dict:
    """One cheap call → {kind, model, provider, tools, reason}. Never raises;
    falls back to 'general' on any parse failure."""
    from providers import make_llm
    cprov, cmodel = _classify_model(models)
    kind = "general"
    reason = "default"
    if cmodel:
        try:
            llm = make_llm(cprov, cmodel, {"temperature": 0.0, "num_predict": 80})
            out = llm.invoke(_CLASSIFY_PROMPT.format(request=request.strip()[:1200]))
            text = out.content if isinstance(out.content, str) else str(out.content)
            m = re.search(r"\{.*\}", text, re.DOTALL)
            if m:
                data = json.loads(m.group(0))
                k = str(data.get("kind", "")).strip().lower()
                if k in TIER_PREFERENCE:
                    kind = k
                reason = str(data.get("reason", ""))[:80]
        except Exception:  # noqa: BLE001 - classification is best-effort
            pass
    prov, model = pick_model_for_kind(kind, models)
    return {"kind": kind, "provider": prov, "model": model,
            "tools": KIND_TOOLS.get(kind, []), "reason": reason,
            "classifier_model": cmodel}
