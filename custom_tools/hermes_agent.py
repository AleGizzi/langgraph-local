"""Delegate a whole task to Hermes Agent (Nous Research, ~/.hermes) in one-shot mode.

Hermes is a full agent (terminal, files, web, memory) running on the SAME local
Ollama. One-shot mode auto-approves its commands, so this tool is listed in
engine._DESTRUCTIVE_TOOLS and blocked on scheduled / max-savings runs.
Setup + caveats: docs/research/hermes.md.
"""
import os
import shutil
import subprocess

from langchain_core.tools import tool

_WORKDIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "data", "workspaces", "hermes")


@tool
def hermes_agent(task: str, workdir: str = "") -> str:
    """Hand a multi-step task (sysadmin, coding, web research) to Hermes Agent and
    return its final answer. Slow: a cold call can take 3-5 minutes on CPU. Use only
    for jobs that need a real terminal/agent loop, not for simple questions.
    workdir: directory Hermes works in (default: the studio's hermes workspace)."""
    binary = shutil.which("hermes") or os.path.expanduser("~/.local/bin/hermes")
    if not os.path.isfile(binary):
        return "Error: Hermes Agent is not installed (see docs/research/hermes.md)."
    cwd = os.path.expanduser(workdir) if workdir else _WORKDIR
    os.makedirs(cwd, exist_ok=True)
    try:
        r = subprocess.run([binary, "-z", task, "--in", cwd], cwd=cwd,
                           capture_output=True, text=True,
                           timeout=int(os.environ.get("HERMES_TOOL_TIMEOUT", "1800")))
    except subprocess.TimeoutExpired:
        return "Error: Hermes timed out (raise HERMES_TOOL_TIMEOUT)."
    out = (r.stdout or "").strip()
    if r.returncode != 0:
        return f"Error: hermes exited {r.returncode}: {(r.stderr or out)[-1500:]}"
    return out[-8000:] or "(Hermes returned no text)"
