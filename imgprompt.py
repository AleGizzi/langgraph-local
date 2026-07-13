"""AI assistant for image prompts.

Turns a plain description ("a cozy robot reading") into a prompt that actually
works on this setup: SDXL phrasing, the trigger words of the LoRAs you have
installed, and — crucially — the prompts that already produced good images here,
read back from the knowledge vault (imgqueue archives every successful job).

The model is a small local one (same picker logic as the help assistant): this
must be fast and it must never invent LoRA names.
"""
import json
import re

from langchain_core.messages import HumanMessage, SystemMessage

import providers

# Non-reasoning models only: a thinking model burns its budget in <think> and
# returns nothing (measured in help.py).
PREFERRED = ("gemma3:4b", "qwen2.5:7b", "llama3.1:8b", "mistral", "gemma3")

CRAFT_RULES = """\
How to write a good SDXL / Fooocus prompt:
- Describe the SUBJECT first, then its details, then the setting, then the
  style/medium, then lighting and mood. Comma-separated fragments, not prose.
- Be concrete and visual. "a weathered brass diving helmet on a wet dock at
  dawn" beats "something cool and nautical".
- Say the medium explicitly (pixel art, oil painting, 3d render, photo,
  watercolour, GBA sprite…), otherwise you get a generic glossy render.
- Add lighting and composition words when they matter (backlit, golden hour,
  close-up, centered, isometric, plain background).
- Do NOT write instructions to the model ("make it look like…", "please"),
  quality spam ("masterpiece, 8k, trending on artstation"), or negations —
  negations belong in the NEGATIVE prompt.
- Keep it under ~60 words.
The NEGATIVE prompt lists what must NOT appear (blurry, extra limbs, text,
watermark, sprite sheet, duplicate, low quality…). Keep it short and relevant.
"""


def pick_model(models: dict) -> tuple:
    for prov in ("ollama", "lmstudio"):
        available = models.get(prov) or []
        for want in PREFERRED:
            for m in available:
                if m.startswith(want):
                    return prov, m
        usable = [m for m in available
                  if not re.search(r"r1|think|embed|qwen3", m, re.I)]
        if usable:
            return prov, usable[0]
    return "ollama", ""


def _lora_hints() -> list:
    """Installed LoRAs the model may legitimately reference, with their triggers."""
    try:
        import loras
        out = []
        for l in loras.list_local():
            if l.get("builtin"):
                continue  # loaded automatically by the speed presets
            out.append({
                "file_name": l["file_name"],
                "what": (l.get("description") or "")[:160],
                "trigger_words": l.get("trigger_words") or [],
            })
        return out
    except Exception:  # noqa: BLE001
        return []


_STOP = {"the", "and", "for", "with", "this", "that", "model", "style", "lora",
         "image", "images", "you", "your", "was", "are", "trained", "very",
         "beautiful", "attempts", "replicate", "art", "have", "haven", "back",
         "while", "training", "uploaded", "use", "used", "using", "safetensors"}


# Words distinctive enough that a single hit is a real match.
_STRONG = {"gba", "gameboy", "pokemon", "pixel", "sprite", "anime", "cyberpunk",
           "watercolour", "watercolor", "isometric", "voxel", "claymation"}


def _tokens(text: str) -> set:
    return {w for w in re.findall(r"[a-z0-9]+", (text or "").lower())
            if len(w) > 2 and w not in _STOP}


def suggest_loras(text: str) -> list:
    """Pick installed LoRAs whose name/description overlaps the request.

    Deterministic on purpose: a small model kept failing to select the obviously
    matching LoRA, and choosing a file is a lookup, not a creative act.
    """
    want = _tokens(text)
    if not want:
        return []
    # Multi-word cues the tokenizer would otherwise split apart.
    low = (text or "").lower()
    for phrase, tok in (("game boy", "gba"), ("gameboy", "gba"),
                        ("pixel art", "pixel"), ("8-bit", "pixel"),
                        ("16-bit", "pixel"), ("retro game", "gba")):
        if phrase in low:
            want.add(tok)

    hits = []
    for l in _lora_hints():
        have = _tokens(l["file_name"].rsplit(".", 1)[0].replace("_", " ")) \
            | _tokens(l.get("what", "")) | _tokens(" ".join(l.get("trigger_words") or []))
        overlap = want & have
        # One generic word is not a match: a LoRA whose description happens to
        # say "portrait" must not hijack a photorealistic portrait request.
        # Require two overlapping words, or one high-signal style word.
        if len(overlap) >= 2 or (overlap & _STRONG):
            hits.append((len(overlap), l["file_name"], sorted(overlap)))
    hits.sort(reverse=True)
    return [{"file_name": f, "matched": m} for _n, f, m in hits[:2]]


def _past_prompts(limit: int = 6) -> list:
    """Prompts that already produced an image here (newest first).

    Read from the knowledge vault first (that's where imgqueue archives them),
    falling back to the image metadata sidecars.
    """
    out = []
    try:
        import knowledge
        for note in knowledge.list_notes():
            if not note["path"].startswith("image-prompts/"):
                continue
            body = knowledge.read_note(note["path"], strip_meta=True)
            m = re.search(r"\*\*Prompt\*\*\s*```(.*?)```", body, re.DOTALL)
            if m:
                out.append(m.group(1).strip())
            if len(out) >= limit:
                break
    except Exception:  # noqa: BLE001
        pass
    if not out:
        try:
            import imagegen
            for name in imagegen.list_images()[:limit * 2]:
                p = (imagegen.image_meta(name) or {}).get("prompt")
                if p and p not in out:
                    out.append(p)
                if len(out) >= limit:
                    break
        except Exception:  # noqa: BLE001
            pass
    return out


def _system_prompt() -> str:
    loras_avail = _lora_hints()
    past = _past_prompts()
    parts = [
        "You write prompts for a LOCAL SDXL image generator (Fooocus).",
        "Given the user's plain description, produce the best prompt for it.",
        "", CRAFT_RULES,
    ]
    if loras_avail:
        parts += [
            "\nStyle LoRAs INSTALLED on this machine (only these exist — never "
            "invent others):",
            json.dumps(loras_avail, ensure_ascii=False),
            "RULE: if the user's requested style matches what one of these LoRAs "
            "does, you MUST put its exact file_name in the \"loras\" list, and "
            "put any of its trigger_words into the prompt. If none match, leave "
            "\"loras\" empty.",
        ]
    if past:
        parts += [
            "\nPrompts that already produced good images on this setup — match "
            "their phrasing style when relevant:",
            "\n".join(f"- {p[:160]}" for p in past),
        ]
    parts += [
        "\nRespond ONLY with JSON, no other text:",
        '{"prompt": "<the image prompt>",',
        ' "negative": "<the negative prompt>",',
        ' "loras": [<file_name of any INSTALLED lora to enable, or empty>],',
        ' "notes": "<one short sentence on what you emphasised>"}',
    ]
    return "\n".join(parts)


def assist(request: str, provider: str = None, model: str = None,
           current_prompt: str = "", feedback: str = "") -> dict:
    """Draft (or refine) an image prompt. Never raises."""
    request = (request or "").strip()
    if not request and not current_prompt:
        return {"ok": False, "error": "describe the image you want"}

    models = providers.list_models()
    if not model:
        provider, model = pick_model(models)
    if not model:
        return {"ok": False, "error": "no local model available"}

    user = f"The user wants an image of:\n{request}"
    if current_prompt and feedback:
        user = (f"Original request:\n{request}\n\nCurrent prompt:\n{current_prompt}\n\n"
                f"Revise it according to this feedback:\n{feedback}")

    try:
        llm = providers.make_llm(provider, model,
                                 {"temperature": 0.4, "num_predict": 500})
        resp = llm.invoke([SystemMessage(content=_system_prompt()),
                           HumanMessage(content=user)])
        text = resp.content if isinstance(resp.content, str) else str(resp.content)
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}

    data = None
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        try:
            data = json.loads(m.group(0))
        except json.JSONDecodeError:
            data = None
    if not isinstance(data, dict):
        # Model ignored the schema — use its raw text as the prompt rather than
        # failing outright.
        data = {"prompt": text[:400], "negative": "", "loras": [], "notes": ""}

    installed = {l["file_name"] for l in _lora_hints()}
    prompt = str(data.get("prompt", "")).strip()
    # The model's picks (validated — never trust an invented file name) plus the
    # deterministic matcher, which is what actually catches the obvious cases.
    picked = [l for l in (data.get("loras") or []) if l in installed]
    suggested = suggest_loras(f"{request} {feedback} {prompt}")
    for s in suggested:
        if s["file_name"] not in picked:
            picked.append(s["file_name"])
    return {
        "ok": True, "error": None, "model": model,
        "prompt": prompt,
        "negative": str(data.get("negative", "")).strip(),
        "loras": picked,
        "lora_matches": suggested,
        "notes": str(data.get("notes", "")).strip(),
    }
