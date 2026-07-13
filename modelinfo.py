"""Per-model "what is this good at?" cards.

Everything here is DETERMINISTIC — derived from facts we already have (the
Ollama catalog's capability tags, the model family, parameter count, quant,
whether it's a reasoning/coder model, and this machine's speed estimate). No
LLM is asked to rate models: ratings must be stable and instant.

Scores are 1-10 and deliberately coarse — they answer "which of MY models should
I point at this job?", not "which model is objectively better".

MAINTENANCE: when a new family appears, add it to FAMILY_TRAITS (and to
sprites.SPECIES if you want its creature). Everything else follows from tags.
"""
import re

import sprites

# Jobs a model can be good at. (key, icon, label, one-line meaning)
APTITUDES = [
    ("brainstorming", "💡", "Brainstorming", "generating many varied ideas"),
    ("problem_solving", "🧠", "Problem solving", "multi-step reasoning and analysis"),
    ("execution", "🎯", "Task execution", "following instructions exactly"),
    ("tool_use", "🔧", "Tool & skill use", "calling tools reliably (function calling)"),
    ("coding", "💻", "Coding", "writing correct, runnable code"),
    ("writing", "✍️", "Writing", "long-form prose, reports, editing"),
    ("speed", "⚡", "Speed", "how fast it responds on this machine"),
    ("long_context", "📚", "Long context", "handling large inputs"),
]

# family → (score nudges, blurb)
FAMILY_TRAITS = {
    "qwen2.5-coder": ({"coding": +3, "execution": +1, "brainstorming": -1},
                      "Code specialist."),
    "qwen2.5": ({"execution": +1, "tool_use": +1}, "Strong, balanced all-rounder."),
    "qwen3": ({"problem_solving": +1, "execution": -1},
              "Hybrid reasoning model — thinks before answering."),
    "deepseek-r1": ({"problem_solving": +3, "execution": -2, "speed": -2},
                    "Reasoning specialist: deliberates at length."),
    "deepseek-coder": ({"coding": +3, "execution": +1}, "Code specialist."),
    "llama3.1": ({"tool_use": +1, "writing": +1}, "Well-rounded, solid tool use."),
    "llama3.2": ({"speed": +1}, "Small, fast Llama."),
    "mistral": ({"speed": +1, "writing": +1}, "Fast, articulate generalist."),
    "codestral": ({"coding": +3}, "Code specialist."),
    "gemma3": ({"writing": +1, "execution": +1},
               "Clean writer; cannot call tools natively."),
    "gemma2": ({"writing": +1}, "Clean writer; no native tool use."),
    "phi3.5": ({"problem_solving": +1, "speed": +1}, "Small but sharp reasoner."),
    "phi4": ({"problem_solving": +2}, "Punches above its size on reasoning."),
    "tinyllama": ({"execution": -2, "problem_solving": -2},
                  "Toy-sized: demos and smoke tests only."),
    "smollm2": ({"speed": +2, "problem_solving": -2},
                "Ultra-small: quick, simple replies."),
    "llava": ({"coding": -2}, "Vision model: describes images."),
}

# aptitude → concrete jobs in THIS app. (aptitude, min score, title, why)
# A role is only suggested when the model actually clears its bar — otherwise
# every model gets recommended as an orchestrator, which helps nobody.
ROLE_SUGGESTIONS = [
    ("coding", 7, "Coder agent in a Code Squad",
     "Your best pick for producing runnable files."),
    ("coding", 7, "Code reviewer",
     "Low temperature + the Code Quality Checklist skill."),
    ("problem_solving", 8, "Supervisor / orchestrator in a team",
     "Give it the coordinator seat — it plans and delegates well."),
    ("problem_solving", 8, "Analyst / deep-thinker agent",
     "Point it at analysis-heavy steps, not final formatting."),
    ("writing", 7, "Writer / editor agent",
     "Give it the drafting or polishing step of a pipeline."),
    ("brainstorming", 8, "Brainstormer / ideas agent",
     "Raise temperature (0.9+) and ask for many options."),
    ("tool_use", 7, "Agent that uses tools",
     "Safe to give it calculator / http_get / files / knowledge."),
    ("execution", 7, "Reliable worker agent",
     "Follows instructions closely — a good default pipeline step."),
    ("speed", 8, "Help assistant, quick chats, cheap steps",
     "Use where latency matters more than depth."),
]


def _params_b(model: str, catalog_params=None) -> float:
    if catalog_params:
        return float(catalog_params)
    m = re.search(r"(\d+(?:\.\d+)?)\s*b\b", (model or "").lower())
    if m:
        return float(m.group(1))
    m = re.search(r"(\d+)\s*m\b", (model or "").lower())
    if m:
        return int(m.group(1)) / 1000
    return 7.0


def _family(model: str) -> str:
    base = (model or "").split(":")[0].lower()
    for fam in sorted(FAMILY_TRAITS, key=len, reverse=True):
        if base.startswith(fam):
            return fam
    return base


def _clamp(v):
    return max(1, min(10, int(round(v))))


def aptitudes(model: str, capabilities=None, params_b=None, est_tok_s=None) -> dict:
    """Score 1-10 per aptitude from facts, not opinions."""
    caps = [c.lower() for c in (capabilities or [])]
    fam = _family(model)
    p = _params_b(model, params_b)
    thinking = "thinking" in caps or bool(re.search(r"r1|qwq|reason", model, re.I))
    tools_ok = "tools" in caps

    # Size drives capability; speed is its inverse (measured beats estimated).
    size_score = min(10.0, 2 + 2.6 * (p ** 0.42))  # 0.5B≈3.9 · 4B≈6.5 · 7B≈7.4 · 14B≈8.9
    speed_score = 11 - 2.4 * (p ** 0.42)
    if est_tok_s:
        speed_score = 2 + min(8, est_tok_s / 5)
    is_coder = fam.endswith("coder") or fam == "codestral"

    s = {
        "brainstorming": size_score - 0.5,
        "problem_solving": size_score,
        "execution": size_score - 0.3,
        "tool_use": (size_score - 0.5) if tools_ok else 2,
        # A big general model still isn't a code specialist — cap it below the
        # coder families, which earn the top scores via FAMILY_TRAITS.
        "coding": size_score - 1.5 if is_coder else min(size_score - 1.5, 7.5),
        "writing": size_score - 0.5,
        "speed": speed_score,
        "long_context": 5 if p < 4 else (7 if p < 15 else 8),
    }
    if thinking:
        s["problem_solving"] += 2
        s["execution"] -= 1.5
        s["speed"] -= 2
    if "vision" in caps:
        s["long_context"] += 1

    for key, delta in FAMILY_TRAITS.get(fam, ({}, ""))[0].items():
        s[key] = s.get(key, 5) + delta
    if not tools_ok:
        # Delegation covers it in team runs, but it is not native.
        s["tool_use"] = min(s["tool_use"], 3)

    # Bonuses must not let a tiny model outrank real capability: a 1.5B
    # "reasoning" model is still a 1.5B model. Speed/context aren't size-capped.
    ceiling = size_score + 2
    for key in ("brainstorming", "problem_solving", "execution", "tool_use",
                "coding", "writing"):
        s[key] = min(s[key], ceiling)

    return {k: _clamp(v) for k, v in s.items()}


def card(model: str, provider: str = "ollama", capabilities=None, params_b=None,
         size_gb=None, quant=None, est_tok_s=None, verdict=None,
         verdict_label=None, installed=True, description="") -> dict:
    """Everything the model card view needs."""
    caps = [c.lower() for c in (capabilities or [])]
    fam = _family(model)
    p = _params_b(model, params_b)
    thinking = "thinking" in caps or bool(re.search(r"r1|qwq|reason", model, re.I))
    tools_ok = "tools" in caps
    # The catalog's tag is family-wide and can be optimistic: the engine learns
    # at RUNTIME which installed builds actually reject tool binding (it then
    # delegates). Trust that lived experience over the tag.
    try:
        import engine
        known = engine._tool_support_cache.get((provider, model))
        if known is False:
            tools_ok = False
            caps = [c for c in caps if c != "tools"]
    except Exception:  # noqa: BLE001 - engine is optional here
        pass
    apt = aptitudes(model, caps, p, est_tok_s)

    ranked = sorted(APTITUDES, key=lambda a: -apt[a[0]])
    best_keys = [a[0] for a in ranked[:3]]

    # Suggest roles in order of how strong the model actually is at them, and
    # only when it clears that role's bar.
    best_for = sorted(
        ({"title": t, "why": w, "aptitude": k, "score": apt[k]}
         for k, floor, t, w in ROLE_SUGGESTIONS if apt[k] >= floor),
        key=lambda r: -r["score"])[:4]
    if not best_for:
        best_for = [{"title": "Light tasks and experiments",
                     "why": "No standout strength on this machine — fine for "
                            "smoke tests and demos.",
                     "aptitude": "speed", "score": apt["speed"]}]

    avoid, notes = [], []
    if not tools_ok:
        avoid.append("Giving it tools directly in Chat — it errors. In team runs "
                     "the app auto-delegates tool calls to a capable model.")
    if thinking:
        avoid.append("Jobs needing short exact output: it thinks at length, and "
                     "with a small max-tokens it can finish with nothing to say.")
    if apt["coding"] <= 4:
        avoid.append("Production code — use a coder model instead.")
    if p <= 1.5:
        avoid.append("Anything multi-step; it drifts on complex instructions.")

    if thinking:
        notes.append("Reasoning model: give it ≥2000 max tokens.")
    if fam.endswith("coder") or fam == "codestral":
        notes.append("Coder models want low temperature (0.1–0.3).")
    if verdict == "tight":
        notes.append("Tight on this machine's RAM — free memory first (Settings).")

    temp = 0.9 if best_keys[0] == "brainstorming" else (
        0.2 if best_keys[0] in ("coding", "execution") else 0.5)

    sp = sprites.species_for(model)
    st = sprites.stage_for(model, p)

    return {
        "name": model, "provider": provider, "family": fam,
        "params_b": p, "size_gb": size_gb, "quant": quant,
        "capabilities": caps, "installed": installed,
        "description": description or FAMILY_TRAITS.get(fam, ({}, ""))[1],
        "thinking": thinking, "native_tools": tools_ok,
        "est_tok_s": est_tok_s, "verdict": verdict, "verdict_label": verdict_label,
        "aptitudes": [{"key": k, "icon": i, "label": l, "meaning": m,
                       "score": apt[k]} for k, i, l, m in APTITUDES],
        "top_aptitudes": best_keys,
        "best_for": best_for, "avoid": avoid, "notes": notes,
        "suggested_params": {"temperature": temp,
                             "num_predict": 4096 if thinking else 2048,
                             "num_ctx": 8192},
        "species": sp["species"], "stage": st["stage"],
        "level": _clamp(2 + p * 0.9 + (2 if thinking else 0)) * 5,
    }
