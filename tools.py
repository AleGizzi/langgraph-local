"""Tools agents can use. All are safe for local use: math is evaluated with
ast (no eval), file access is confined to the run's workspace directory, and
http_get has strict timeouts.
"""
import ast
import datetime
import operator as op
import os

import requests
from langchain_core.tools import tool

_OPS = {
    ast.Add: op.add, ast.Sub: op.sub, ast.Mult: op.mul, ast.Div: op.truediv,
    ast.Pow: op.pow, ast.Mod: op.mod, ast.FloorDiv: op.floordiv,
    ast.USub: op.neg, ast.UAdd: op.pos,
}


def _eval_node(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_eval_node(node.left), _eval_node(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_eval_node(node.operand))
    raise ValueError("unsupported expression")


@tool
def calculator(expression: str) -> str:
    """Evaluate a math expression, e.g. '2 * (3 + 4) / 5'. Supports + - * / ** % //."""
    try:
        return str(_eval_node(ast.parse(expression.strip(), mode="eval").body))
    except Exception as e:  # noqa: BLE001
        return f"Error: {e}"


@tool
def current_datetime() -> str:
    """Return the current local date and time."""
    return datetime.datetime.now().strftime("%A, %Y-%m-%d %H:%M:%S")


@tool
def http_get(url: str) -> str:
    """Fetch a URL and return its text content (truncated to 8000 chars)."""
    try:
        r = requests.get(url, timeout=15, headers={"User-Agent": "local-agents/1.0"})
        r.raise_for_status()
        text = r.text
        return text[:8000] + ("\n...[truncated]" if len(text) > 8000 else "")
    except Exception as e:  # noqa: BLE001
        return f"Error fetching {url}: {e}"


def make_workspace_tools(workspace: str):
    """File tools bound to a run's workspace directory (path-traversal safe)."""

    def _safe(path: str) -> str:
        full = os.path.realpath(os.path.join(workspace, path.lstrip("/")))
        if not full.startswith(os.path.realpath(workspace) + os.sep) and \
                full != os.path.realpath(workspace):
            raise ValueError("path escapes workspace")
        return full

    @tool
    def write_file(path: str, content: str) -> str:
        """Write content to a file in the shared workspace. Relative paths only."""
        try:
            full = _safe(path)
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, "w", encoding="utf-8") as f:
                f.write(content)
            return f"Wrote {len(content)} chars to {path}"
        except Exception as e:  # noqa: BLE001
            return f"Error: {e}"

    @tool
    def read_file(path: str) -> str:
        """Read a file from the shared workspace."""
        try:
            with open(_safe(path), encoding="utf-8") as f:
                text = f.read()
            return text[:12000] + ("\n...[truncated]" if len(text) > 12000 else "")
        except Exception as e:  # noqa: BLE001
            return f"Error: {e}"

    @tool
    def list_files(path: str = ".") -> str:
        """List files in the shared workspace."""
        try:
            root = _safe(path)
            items = []
            for base, _dirs, files in os.walk(root):
                for f in files:
                    items.append(os.path.relpath(os.path.join(base, f), workspace))
            return "\n".join(sorted(items)) or "(empty)"
        except Exception as e:  # noqa: BLE001
            return f"Error: {e}"

    return [write_file, read_file, list_files]


TOOL_CATALOG = {
    "calculator": "Math expression evaluator",
    "current_datetime": "Current date and time",
    "http_get": "Fetch a URL (needs internet)",
    "files": "Read/write files in the run workspace",
}


def resolve_tools(names: list, workspace: str) -> list:
    tools = []
    for n in names or []:
        if n == "calculator":
            tools.append(calculator)
        elif n == "current_datetime":
            tools.append(current_datetime)
        elif n == "http_get":
            tools.append(http_get)
        elif n == "files":
            tools.extend(make_workspace_tools(workspace))
    return tools
