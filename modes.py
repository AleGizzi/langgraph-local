"""Run modes: one team, three speed/quality tiers, no duplicate configs.

Borrowed from the portable agent-team framework's "mode = a column, not a copy"
idea, adapted to a local, no-billing world. Here the budget isn't dollars — it's
VRAM, latency, and the tiny local context window — so a mode shifts each agent's
model along its OWN family's installed size ladder:

  - max-savings → the smallest installed model in the same family (fast, cheap
    on VRAM; use when the task is easy or you just want a quick pass)
  - balanced    → the team as authored (no change)
  - quality     → the largest installed model in the same family (slower, better
    on hard tasks)

Only same-family swaps happen (qwen2.5:7b ↔ qwen2.5:14b, never qwen2.5 ↔ gemma3)
so a persona's tuning stays meaningful. A model with no installed sibling in its
family is left exactly as-is. balanced is always a no-op.
"""
import copy
import re

MODES = ("max-savings", "balanced", "quality")


def _family_size(model: str):
    """('qwen2.5-coder:14b') → ('qwen2.5-coder', 14.0). Size None if unparseable."""
    name = (model or "").split(":")[0]
    tag = (model or "").split(":", 1)[1] if ":" in (model or "") else ""
    m = re.search(r"(\d+(?:\.\d+)?)\s*b", tag.lower())
    return name, (float(m.group(1)) if m else None)


def apply_mode(team: dict, mode: str, models_by_provider: dict) -> dict:
    """Return a copy of `team` with each agent's model shifted for `mode`.

    models_by_provider: {"ollama": [names...], "lmstudio": [names...]}.
    """
    if mode not in ("max-savings", "quality"):
        return team  # balanced / unknown → unchanged

    # Group each provider's installed models by family, sorted small→large.
    by_prov_fam = {}
    for prov, names in (models_by_provider or {}).items():
        if not isinstance(names, list):   # skip the "errors" entry, etc.
            continue
        fam = {}
        for mn in names:
            f, s = _family_size(mn)
            if s is not None:
                fam.setdefault(f, []).append((s, mn))
        for f in fam:
            fam[f].sort()
        by_prov_fam[prov] = fam

    t = copy.deepcopy(team)
    for a in t.get("agents", []):
        prov = a.get("provider", "ollama")
        f, _s = _family_size(a.get("model", ""))
        cands = by_prov_fam.get(prov, {}).get(f)
        if not cands:
            continue
        a["model"] = cands[0][1] if mode == "max-savings" else cands[-1][1]
    return t
