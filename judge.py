"""Hallucination-risk estimation for chat replies.

An honest framing matters here: hallucination cannot be MEASURED locally — no
oracle knows the truth. What a small judge model CAN do is estimate how much of
a reply consists of specific factual claims that are not supported by anything
in view (the question, the conversation, tool results, or common knowledge).
That estimate is what we surface, always labeled as an estimate, never as a
measurement. High risk ≠ wrong; low risk ≠ right — it flags where to be
skeptical, especially numbers, names, dates, APIs and citations.
"""
import json
import re

from providers import make_llm
from help import pick_model

_PROMPT = """You estimate hallucination risk in an AI assistant's reply.

Hallucination risk = the share of the reply that asserts SPECIFIC facts
(numbers, dates, names, versions, APIs, quotes, events, prices) that are NOT
supported by: the user's message, the conversation, the tool results below, or
truly common knowledge. General reasoning, opinions, hedged statements and
instructions the user asked for carry low risk. Confident, specific,
unverifiable claims carry high risk.

USER ASKED:
{question}

TOOL RESULTS THE ASSISTANT HAD (may be empty):
{evidence}

ASSISTANT REPLIED:
{reply}

Respond with ONLY this JSON, nothing else:
{{"risk": <0-100 integer>, "reasons": ["<up to 3 short reasons naming the riskiest claims>"]}}"""


def _extract_json(text: str) -> dict:
    """Never trust model output — find and repair the JSON blob."""
    m = re.search(r"\{.*\}", text or "", re.DOTALL)
    if not m:
        return {}
    try:
        return json.loads(m.group(0))
    except ValueError:
        try:  # common repair: trailing commas
            return json.loads(re.sub(r",\s*([}\]])", r"\1", m.group(0)))
        except ValueError:
            return {}


def estimate(question: str, reply: str, evidence: str = "",
             provider: str = None, model: str = None) -> dict:
    """Estimate hallucination risk for one reply. Never raises."""
    if not (reply or "").strip():
        return {"ok": False, "error": "empty reply", "risk": None, "reasons": []}
    if not model:
        from providers import list_models
        provider, model = pick_model(list_models())
    if not model:
        return {"ok": False, "error": "no local model available",
                "risk": None, "reasons": []}
    prompt = _PROMPT.format(
        question=(question or "").strip()[:2000],
        evidence=(evidence or "").strip()[:3000] or "(none)",
        reply=(reply or "").strip()[:6000])
    try:
        llm = make_llm(provider or "ollama", model,
                       {"temperature": 0.1, "num_predict": 300})
        out = llm.invoke(prompt)
        text = out.content if isinstance(out.content, str) else str(out.content)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {e}",
                "risk": None, "reasons": []}
    data = _extract_json(text)
    try:
        risk = max(0, min(100, int(data.get("risk"))))
    except (TypeError, ValueError):
        return {"ok": False, "error": "judge returned no usable score",
                "risk": None, "reasons": []}
    reasons = [str(r)[:160] for r in (data.get("reasons") or [])[:3]
               if str(r).strip()]
    return {"ok": True, "error": None, "risk": risk, "reasons": reasons,
            "judge": model}
