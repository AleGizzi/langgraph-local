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


# Ollama "decision" models (Jev Decision Index family) answer a typed choice in
# ONE forward pass with probabilities via /v1/systemone — no generation, no JSON
# to repair. Preferred over the chat-model classifier when one is installed.
# Preference order; providers.list_models reports installed ones under "decision".
DECISION_PREFERENCE = ["tev1", "d3", "kev", "nimble"]  # measured: docs/research/small-models.md

_KIND_CRITERIA = {
    "trivial": "a greeting, a one-line fact, a tiny transformation",
    "general": "a normal question or short writing task",
    "code": "writing or fixing a small/medium program",
    "code_hard": "a large, multi-file or tricky program needing the strongest coder",
    "research": "needs current info from the web",
    "reasoning": "multi-step logic, math, planning, careful analysis",
    "creative": "story, brainstorm, marketing copy, tone-heavy writing",
}


def _decision_model(models: dict):
    for want in DECISION_PREFERENCE:
        for m in (models.get("decision") or []):
            if m == want or m.startswith(want + ":"):
                return m
    return None


def _classify_decision(request: str, model: str):
    """(kind, reason) from a decision model, or None if the call fails."""
    import requests
    from providers import OLLAMA_URL
    try:
        r = requests.post(f"{OLLAMA_URL}/v1/systemone", timeout=60, json={
            "model": model,
            # decision models run with a ~2k-token working context: keep it short
            "state": request.strip()[:1200],
            "questions": {"kind": {
                "type": "choice",
                "instructions": "Which kind of task is this request?",
                "criteria": _KIND_CRITERIA}}})
        r.raise_for_status()
        ans = (r.json().get("answers") or {}).get("kind") or {}
        k = str(ans.get("choice", "")).strip().lower()
        if k in TIER_PREFERENCE:
            return k, f"p={float(ans.get('probabilities', {}).get(k, 0)):.2f}"
    except Exception:  # noqa: BLE001 - fall back to the chat-model classifier
        pass
    return None


def classify(request: str, models: dict) -> dict:
    """One cheap call → {kind, model, provider, tools, reason}. Never raises;
    falls back to 'general' on any parse failure."""
    from providers import make_llm
    kind = "general"
    reason = "default"
    dmodel = _decision_model(models)
    decided = _classify_decision(request, dmodel) if dmodel else None
    if decided:
        (kind, reason), cmodel = decided, dmodel
    else:
        cprov, cmodel = _classify_model(models)
    if cmodel and not decided:
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
