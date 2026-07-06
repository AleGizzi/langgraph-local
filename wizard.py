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
