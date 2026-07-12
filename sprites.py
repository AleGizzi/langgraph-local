"""Agent sprite system: Pokémon-style creature identity for personas.

Design rules (the owner's spec):
- Every model FAMILY is one SPECIES with fixed distinguishing traits, so all
  qwen-based agents are recognizably the same creature kind, all mistral-based
  another, etc. Species traits are decided HERE in code — never by an LLM —
  so they cannot drift between generations.
- Capability decides EVOLUTION STAGE: small models look like cubs, mid-size
  like adolescents, large ones fully evolved and imposing.
- The persona's role only adds accessories/flavor on top (goggles for coders,
  a scroll for writers…), never changes the species.

The prompt targets the SDXL JuggernautXL base that Fooocus ships; a GBA/pixel
sprite LoRA (see loras.py) biases the output toward the Game Boy Advance look.
"""
import re

# family key → (species name, fixed visual identity)
SPECIES = {
    "qwen": ("Qwenix",
             "an entirely violet purple furred fox-spirit creature, purple fur "
             "all over its body, lighter lavender belly, large amber eyes, "
             "five small floating rune orbs circling it"),
    "deepseek": ("Abyssyn",
                 "a deep-ocean leviathan creature with midnight-blue scales, "
                 "bioluminescent cyan spots, glowing white eyes, small whale fins"),
    "llama": ("Llamon",
              "a fluffy cream-colored llama creature with a confident stance "
              "and a small red adventurer scarf"),
    "mistral": ("Zephyrix",
                "a wind-wisp creature made of swirling teal and white air "
                "currents, trailing cloud puffs, mischievous grin"),
    "gemma": ("Gemlit",
              "a crystalline creature with emerald gem skin, faceted "
              "translucent body, inner green glow"),
    "phi": ("Philuma",
            "a small golden owl creature with oversized round glasses and "
            "star-marked feathers"),
    "smollm": ("Smolt",
               "a tiny round pebble creature with stubby limbs and a single "
               "curious eye, pastel grey"),
    "tinyllama": ("Nanollama",
                  "a pocket-sized fuzzy llama creature, oversized ears, "
                  "beige wool"),
    "codestral": ("Zephyrix",
                  "a wind-wisp creature made of swirling teal and white air "
                  "currents, wearing tiny welding goggles"),
}
DEFAULT_SPECIES = ("Modelmon",
                   "a friendly rounded robot creature with soft grey plating "
                   "and a glowing blue chest light")

# evolution stages by parameter count (billions)
STAGES = [
    (3, "baby form: small, round, oversized head, big innocent eyes, "
        "sitting posture, extremely cute"),
    (9, "adolescent form: upright, sleek, alert and confident, mid-size"),
    (999, "final evolution: large, majestic and imposing, elaborate features, "
          "faint glowing power aura, battle-ready stance"),
]

# role keywords → accessory flavor
ACCESSORIES = [
    (r"code|coder|dev|engineer|program", "wearing tiny round coder goggles"),
    (r"writ|edit|author|content", "holding a small quill and scroll"),
    (r"research|analy|scien", "wearing a explorer's satchel and magnifier"),
    (r"review|critic|judge|qa", "wearing a tiny judge's monocle"),
    (r"orchestr|manager|coordin|lead|pmo", "wearing a small captain's cape"),
    (r"design|art|creativ|image", "holding a tiny paintbrush, paint-splashed"),
    (r"security|guard", "wearing a small shield emblem"),
]


def _family(model: str) -> str:
    base = (model or "").split(":")[0].lower()
    base = re.sub(r"[-_.](instruct|chat|latest|v\d.*|\d+b.*)$", "", base)
    # Longest key first so 'tinyllama' wins over 'llama', 'smollm' over nothing.
    for fam in sorted(SPECIES, key=len, reverse=True):
        if base.startswith(fam) or fam in base:
            return fam
    return ""


def _params_b(model: str, catalog_params=None) -> float:
    if catalog_params:
        return float(catalog_params)
    m = re.search(r"(\d+(?:\.\d+)?)b\b", (model or "").lower())
    if m:
        return float(m.group(1))
    m = re.search(r"(\d+)m\b", (model or "").lower())
    if m:
        return int(m.group(1)) / 1000
    if _family(model) in ("tinyllama", "smollm"):
        return 1.0
    return 7.0  # unknown → assume mid-size


def species_for(model: str) -> dict:
    fam = _family(model)
    name, look = SPECIES.get(fam, DEFAULT_SPECIES)
    return {"family": fam or "unknown", "species": name, "look": look}


def stage_for(model: str, catalog_params=None) -> dict:
    p = _params_b(model, catalog_params)
    for limit, desc in STAGES:
        if p <= limit:
            return {"params_b": p, "stage": STAGES.index((limit, desc)) + 1,
                    "look": desc}
    return {"params_b": p, "stage": 3, "look": STAGES[-1][1]}


def _accessory(role: str, tools=None) -> str:
    text = (role or "").lower()
    for pattern, acc in ACCESSORIES:
        if re.search(pattern, text):
            return acc
    if tools:
        return "wearing a tiny utility belt"
    return ""


def build_sprite_prompt(model: str, role: str = "", tools=None,
                        catalog_params=None, flavor: str = "") -> dict:
    """Deterministic sprite prompt for a persona. Returns prompt + negative
    + the resolved species/stage (stored with the persona for display)."""
    sp = species_for(model)
    st = stage_for(model, catalog_params)
    acc = _accessory(role, tools)
    parts = [
        "pokemon style creature sprite, game boy advance pixel art",
        sp["look"], st["look"],
    ]
    if acc:
        parts.append(acc)
    if flavor:
        parts.append(flavor.strip()[:120])
    parts += ["exactly one single creature, solo, full body, centered, "
              "plain white background",
              "gba 32-bit era palette, crisp pixel outlines"]
    negative = ("sprite sheet, multiple views, grid, several creatures, "
                "photorealistic, 3d render, human, text, watermark, blurry, "
                "background scenery")
    return {"prompt": ", ".join(parts), "negative": negative,
            "species": sp["species"], "family": sp["family"],
            "stage": st["stage"], "params_b": st["params_b"]}
