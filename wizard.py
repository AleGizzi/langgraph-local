"""AI wizard: uses a local LLM to draft skills and custom tools from a
plain-language description, with validation and one auto-fix round for code.
"""
import json
import re

from langchain_core.messages import HumanMessage, SystemMessage

import providers
import tools as tools_mod

SKILL_SYSTEM = """You design "skills" for AI agents. A skill is a reusable block of
instructions appended verbatim to an agent's system prompt to shape its behavior.

Good skill instructions are imperative directives ("Format output as...",
"Always end with...", "Never present a guess as fact"), focused on ONE
behavior, concrete, and testable. They never mention the user, the wizard,
or being an AI.

Respond ONLY with a JSON object, no other text:
{"name": "<2-4 word title>",
 "icon": "<one emoji>",
 "description": "<one line: what this makes an agent do>",
 "instructions": "<the directives, 2-8 sentences>"}"""

TOOL_SYSTEM = """You write custom tools for a local LangGraph agent app.

Rules for a tool file:
- Python only. Import the decorator: from langchain_core.tools import tool
- Each tool is a plain function decorated with @tool, with type-annotated
  arguments and a string return value.
- The docstring is the contract: first line says what the tool does and when
  to use it; mention what each argument means. The model decides when to call
  the tool based on this docstring alone.
- Handle errors inside the function and return them as strings ("Error: ...").
- Available libraries: Python standard library and `requests`. Nothing else.
- No global side effects at import time (no network calls, no file writes at
  module level). Keep it self-contained.

Respond ONLY with one Python code block (```python ... ```), no other text."""


def _text_of(resp) -> str:
    text = resp.content if isinstance(resp.content, str) else str(resp.content)
    return re.sub(r"<think>.*?</think>\s*", "", text, flags=re.DOTALL).strip()


def _call(provider: str, model: str, system: str, user: str) -> str:
    llm = providers.make_llm(provider, model,
                             {"temperature": 0.3, "num_predict": 1600})
    return _text_of(llm.invoke([SystemMessage(content=system),
                                HumanMessage(content=user)]))


def _extract_json(text: str):
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def _extract_code(text: str) -> str:
    m = re.search(r"```(?:python)?\s*\n(.*?)```", text, re.DOTALL)
    return (m.group(1) if m else text).strip() + "\n"


def draft_skill(provider: str, model: str, request: str,
                current: dict = None, feedback: str = None) -> dict:
    user = f"Design a skill for this need:\n{request}"
    if current and feedback:
        user = (f"Original need:\n{request}\n\nCurrent draft:\n"
                f"{json.dumps(current, ensure_ascii=False)}\n\n"
                f"Revise it according to this feedback:\n{feedback}\n"
                "Return the full revised JSON.")
    text = _call(provider, model, SKILL_SYSTEM, user)
    data = _extract_json(text)
    if not isinstance(data, dict) or not data.get("instructions"):
        # Fallback: use the whole answer as instructions rather than failing.
        data = {"name": (request[:40] + "…") if len(request) > 40 else request,
                "icon": "✨", "description": request[:120], "instructions": text}
    return {
        "name": str(data.get("name", ""))[:60].strip() or "New Skill",
        "icon": str(data.get("icon", "✨"))[:8].strip() or "✨",
        "description": str(data.get("description", ""))[:200].strip(),
        "instructions": str(data.get("instructions", "")).strip(),
    }


PERSONA_SYSTEM = """You design a single reusable AGENT PERSONA for a local LLM
orchestration app. Respond ONLY with a JSON object:

{"name": "<2-3 word persona name>", "icon": "<one emoji>",
 "role": "<job title>",
 "description": "<one line: what this persona is good at>",
 "system_prompt": "<3-5 specific sentences defining identity, method and
                   output standards — imperative, no placeholders>",
 "model": "<pick the best fit from AVAILABLE MODELS: coder model for coding
           personas, reasoning model for deep-analysis personas, general
           otherwise>",
 "provider": "<the provider of that model>",
 "params": {"temperature": <0.0-1.0 suited to the role>},
 "tools": [<only from AVAILABLE TOOLS, only if genuinely useful>],
 "skills": [<only from AVAILABLE SKILLS, only if genuinely useful>],
 "flavor": "<ONE short visual accessory idea for this persona's creature
            sprite, e.g. 'carrying a tiny telescope' — max 8 words>"}"""


def draft_persona(provider: str, model: str, request: str, models: dict,
                  tools: list, skills: list, current: dict = None,
                  feedback: str = None) -> dict:
    """Draft a persona from a natural-language description."""
    ctx = (f"AVAILABLE MODELS: "
           f"{json.dumps({p: models.get(p) or [] for p in ('ollama', 'lmstudio')})}\n"
           f"AVAILABLE TOOLS: {json.dumps(tools)}\n"
           f"AVAILABLE SKILLS: {json.dumps(skills)}")
    user = f"{ctx}\n\nDesign a persona for this description:\n{request}"
    if current and feedback:
        user = (f"{ctx}\n\nOriginal description:\n{request}\n\nCurrent draft:\n"
                f"{json.dumps(current, ensure_ascii=False)}\n\nRevise per this "
                f"feedback:\n{feedback}\nReturn the full revised JSON.")
    llm = providers.make_llm(provider, model,
                             {"temperature": 0.4, "num_predict": 1200})
    text = _text_of(llm.invoke([SystemMessage(content=PERSONA_SYSTEM),
                                HumanMessage(content=user)]))
    data = _extract_json(text)
    if not isinstance(data, dict):
        data = {}
    valid_models = {(p, m) for p in ("ollama", "lmstudio")
                    for m in (models.get(p) or [])}
    prov, mdl = data.get("provider", "ollama"), str(data.get("model") or "")
    if (prov, mdl) not in valid_models:
        team = _normalize_team({"agents": [{"name": "x", "role": data.get("role", "")}]},
                               models, [], [])
        prov, mdl = team["agents"][0]["provider"], team["agents"][0]["model"]
    return {
        "name": str(data.get("name") or request[:30])[:40].strip() or "New Persona",
        "icon": str(data.get("icon") or "🧑")[:8],
        "role": str(data.get("role", ""))[:80],
        "description": str(data.get("description", ""))[:200],
        "system_prompt": str(data.get("system_prompt", "")).strip(),
        "provider": prov, "model": mdl,
        "params": data.get("params") if isinstance(data.get("params"), dict) else {},
        "tools": [t for t in (data.get("tools") or []) if t in tools],
        "skills": [s for s in (data.get("skills") or []) if s in skills],
        "flavor": str(data.get("flavor", ""))[:80],
    }


TEAM_SYSTEM = """You design multi-agent TEAMS for a local LLM orchestration app.
A team is a JSON object:

{"name": "<2-4 words>", "icon": "<one emoji>", "description": "<one line>",
 "topology": "single" | "pipeline" | "supervisor" | "graph",
 "settings": {"quality_loop": bool, "max_revisions": 2, "max_steps": 8,
              "parallel": bool},
 "agents": [{"name": "<unique short name>", "role": "<job title>",
             "provider": "<from available models>", "model": "<from available models>",
             "system_prompt": "<2-4 specific sentences defining who this agent is,
                               what it produces and its standards — no placeholders>",
             "params": {"temperature": <0.0-1.0>},
             "tools": [<only from the available tools list, only if truly useful>],
             "skills": [<only from the available skills list, only if truly useful>]}],
 "graph": <ONLY when topology is "graph">
          {"nodes": [{"id": "n1", "agent": "<agent name>"}, ...],
           "edges": [{"source": "start"|"<id>", "target": "<id>"|"end"}, ...]}}

Topology guide — pick what matches the user's description:
- "supervisor": the FIRST agent is an orchestrator/coordinator/manager/PMO that
  delegates work to the other agents dynamically and synthesizes the result.
  Use whenever the user describes an orchestrator, manager, lead or PMO.
- "pipeline": agents work in a fixed sequence, each building on the previous.
  Set quality_loop=true and put a reviewer LAST when review/QA of the final
  output is wanted at the end of a sequence.
- "graph": independent groups work in parallel branches that merge (set
  settings.parallel=true). Edges flow start → branches → merge agent → end.
- "single": one agent only.

Hard rules:
- 3 to 6 agents ideal; NEVER more than 8 (each agent is a slow local-model call).
  If the user asks for "a team of X", represent it as 1-2 strong X agents, not many.
- Every agent name unique. Every model/tool/skill ONLY from the provided lists;
  give coding agents a coder model when one is available.
- Low temperature (0.1-0.3) for reviewers/orchestrators, higher (0.6-0.8) for
  creative writers.
Respond ONLY with the JSON object, no other text."""


def _grid_positions(node_ids: list) -> dict:
    pos = {"start": {"x": 20, "y": 220},
           "end": {"x": 320 + max(1, len(node_ids)) * 240, "y": 220}}
    for i, nid in enumerate(node_ids):
        pos[nid] = {"x": 240 + (i % 3) * 240, "y": 90 + (i // 3) * 170}
    return pos


def _normalize_team(data: dict, models: dict, tools: list, skills: list) -> dict:
    """Repair a model-drafted team into something the API will accept.

    Local models get schemas mostly-right; this fixes the common failures
    (bad model names, duplicate agents, invalid topology/graph) instead of
    rejecting the draft.
    """
    def pick_model(coder: bool):
        for prov in ("ollama", "lmstudio"):
            lst = models.get(prov) or []
            if coder:
                m = next((x for x in lst if re.search(r"coder", x, re.I)
                          and not re.search(r"r1|think", x, re.I)), None)
                if m:
                    return prov, m
            m = next((x for x in lst if re.search(r"^(qwen|llama|mistral|gemma)", x, re.I)
                      and not re.search(r"r1|coder|think", x, re.I)), None)
            if m:
                return prov, m
            if lst:
                return prov, lst[0]
        return "ollama", ""

    valid_models = {(p, m) for p in ("ollama", "lmstudio") for m in (models.get(p) or [])}
    agents, seen = [], set()
    for a in (data.get("agents") or [])[:8]:
        if not isinstance(a, dict):
            continue
        name = str(a.get("name") or "Agent").strip()[:40] or "Agent"
        base, i = name, 2
        while name.lower() in seen:
            name = f"{base} {i}"
            i += 1
        seen.add(name.lower())
        prov = a.get("provider", "ollama")
        mdl = str(a.get("model") or "")
        if (prov, mdl) not in valid_models:
            coderish = bool(re.search(r"code|coder|dev|engineer|program",
                                      f"{name} {a.get('role','')}", re.I))
            prov, mdl = pick_model(coderish)
        params = a.get("params") if isinstance(a.get("params"), dict) else {}
        agents.append({
            "name": name, "role": str(a.get("role", ""))[:80],
            "provider": prov, "model": mdl,
            "system_prompt": str(a.get("system_prompt", "")).strip(),
            "params": params,
            "tools": [t for t in (a.get("tools") or []) if t in tools],
            "skills": [s for s in (a.get("skills") or []) if s in skills],
        })
    if not agents:
        prov, mdl = pick_model(False)
        agents = [{"name": "Agent", "role": "", "provider": prov, "model": mdl,
                   "system_prompt": "", "params": {}, "tools": [], "skills": []}]

    topology = data.get("topology")
    if topology not in ("single", "pipeline", "supervisor", "graph"):
        topology = "pipeline" if len(agents) > 1 else "single"
    if topology == "supervisor" and len(agents) < 2:
        topology = "single"
    if len(agents) == 1:
        topology = "single"

    settings_in = data.get("settings") if isinstance(data.get("settings"), dict) else {}
    settings = {"quality_loop": bool(settings_in.get("quality_loop")),
                "max_revisions": 2, "max_steps": 8,
                "parallel": bool(settings_in.get("parallel"))}

    out = {"name": str(data.get("name") or "New Team")[:60],
           "icon": str(data.get("icon") or "🤖")[:8],
           "description": str(data.get("description", ""))[:300],
           "topology": topology, "settings": settings, "agents": agents}

    if topology == "graph":
        g = data.get("graph") if isinstance(data.get("graph"), dict) else {}
        agent_names = {a["name"] for a in agents}
        nodes = [{"id": str(n.get("id") or f"n{i+1}"), "agent": n.get("agent")}
                 for i, n in enumerate(g.get("nodes") or [])
                 if isinstance(n, dict) and n.get("agent") in agent_names]
        ids = {n["id"] for n in nodes}
        edges = [{"source": str(e.get("source")), "target": str(e.get("target"))}
                 for e in (g.get("edges") or []) if isinstance(e, dict)
                 and str(e.get("source")) in ids | {"start"}
                 and str(e.get("target")) in ids | {"end"}]
        has_start = any(e["source"] == "start" for e in edges)
        has_end = any(e["target"] == "end" for e in edges)
        if not nodes or not has_start or not has_end:
            # Graph too broken to trust — degrade to a plain pipeline.
            out["topology"] = "pipeline"
        else:
            out["graph"] = {"nodes": nodes, "edges": edges,
                            "positions": _grid_positions([n["id"] for n in nodes])}
    return out


def draft_team(provider: str, model: str, request: str, models: dict,
               tools: list, skills: list, current: dict = None,
               feedback: str = None) -> dict:
    """Draft a full team definition from a natural-language description."""
    ctx = (f"AVAILABLE MODELS (provider: models): "
           f"{json.dumps({p: models.get(p) or [] for p in ('ollama', 'lmstudio')})}\n"
           f"AVAILABLE TOOLS: {json.dumps(tools)}\n"
           f"AVAILABLE SKILLS: {json.dumps(skills)}")
    user = f"{ctx}\n\nDesign a team for this description:\n{request}"
    if current and feedback:
        user = (f"{ctx}\n\nOriginal description:\n{request}\n\nCurrent draft:\n"
                f"{json.dumps(current, ensure_ascii=False)}\n\n"
                f"Revise it according to this feedback:\n{feedback}\n"
                "Return the full revised JSON.")
    llm = providers.make_llm(provider, model,
                             {"temperature": 0.4, "num_predict": 3500})
    text = _text_of(llm.invoke([SystemMessage(content=TEAM_SYSTEM),
                                HumanMessage(content=user)]))
    data = _extract_json(text)
    if not isinstance(data, dict):
        data = {"name": request[:40], "description": request[:200], "agents": []}
    return _normalize_team(data, models, tools, skills)


def draft_tool(provider: str, model: str, request: str,
               current_code: str = None, feedback: str = None) -> dict:
    user = f"Write a tool for this need:\n{request}"
    if current_code and feedback:
        user = (f"Original need:\n{request}\n\nCurrent code:\n```python\n"
                f"{current_code}\n```\n\nRevise it according to this feedback:\n"
                f"{feedback}\nReturn the full revised file.")
    code = _extract_code(_call(provider, model, TOOL_SYSTEM, user))
    names, error = tools_mod.validate_tool_code(code)

    if error:
        # One auto-fix round: show the model its own error.
        fix_user = (f"Original need:\n{request}\n\nThis code fails to load:\n"
                    f"```python\n{code}\n```\n\nError:\n{error}\n\n"
                    "Return the full corrected file.")
        code2 = _extract_code(_call(provider, model, TOOL_SYSTEM, fix_user))
        names2, error2 = tools_mod.validate_tool_code(code2)
        if not error2:
            code, names, error = code2, names2, None

    suggestion = (re.sub(r"\W+", "_", names[0]).strip("_") + ".py") if names else "my_tool.py"
    return {"code": code, "tools": names, "error": error,
            "filename_suggestion": suggestion}


SCHEDULE_SYSTEM = """You design a SCHEDULED TASK for a local-LLM agent app. The
task runs unattended on an interval. Given a plain-language description, output
ONLY a JSON object:
{
  "name": "short label",
  "prompt": "clear, self-contained instruction the agent runs every time",
  "interval_seconds": <900|3600|21600|43200|86400|604800>,
  "tools": ["only from the AVAILABLE TOOLS given"],
  "track_number": <true if the task produces a single number to chart over time>,
  "notify": <true if the user should be alerted each run>,
  "knowledge_folder": "<slug>" or null (set when results should accumulate as notes)
}
Rules:
- If the task needs the internet (news, prices, research), include web_search and
  read_webpage in tools.
- Prompts that report a value to track should ask for the number explicitly.
- Prefer daily (86400) unless the description implies otherwise.
- Keep the prompt concrete and give the agent everything it needs."""


def draft_schedule(provider: str, model: str, request: str, tools: list,
                   current: dict = None, feedback: str = None) -> dict:
    """Draft a scheduled-task config from a natural-language description."""
    ctx = f"AVAILABLE TOOLS: {json.dumps(tools)}"
    user = f"{ctx}\n\nDesign a scheduled task for:\n{request}"
    if current and feedback:
        user = (f"{ctx}\n\nOriginal request:\n{request}\n\nCurrent draft:\n"
                f"{json.dumps(current, ensure_ascii=False)}\n\nRevise per this "
                f"feedback:\n{feedback}\nReturn the full revised JSON.")
    data = _extract_json(_call(provider, model, SCHEDULE_SYSTEM, user)) or {}

    allowed_intervals = {900, 3600, 21600, 43200, 86400, 604800}
    try:
        interval = int(data.get("interval_seconds", 86400))
    except (TypeError, ValueError):
        interval = 86400
    if interval not in allowed_intervals:
        # snap to the nearest allowed interval
        interval = min(allowed_intervals, key=lambda v: abs(v - interval))

    want_tools = [t for t in (data.get("tools") or []) if t in tools]
    folder = data.get("knowledge_folder")
    folder = re.sub(r"[^\w/ -]", "", str(folder)).strip("/ ") if folder else None

    return {
        "name": str(data.get("name") or request[:40])[:120].strip() or "Scheduled task",
        "prompt": str(data.get("prompt") or request).strip(),
        "interval_seconds": interval,
        "tools": want_tools,
        "track_number": bool(data.get("track_number", False)),
        "notify": bool(data.get("notify", False)),
        "knowledge_folder": folder or None,
    }
