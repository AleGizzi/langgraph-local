"""Tools agents can use. All are safe for local use: math is evaluated with
ast (no eval), file access is confined to the run's workspace directory, and
http_get has strict timeouts.
"""
import ast
import datetime
import html
import operator as op
import os
import re
import shutil
import subprocess
import sys
from urllib.parse import unquote

import requests
from langchain_core.tools import tool


def _strip_html(raw: str) -> str:
    """Reduce an HTML document to readable text."""
    raw = re.sub(r"(?is)<(script|style|nav|footer|svg)[^>]*>.*?</\1>", " ", raw)
    raw = re.sub(r"(?i)<br\s*/?>|</(p|div|li|h[1-6]|tr)>", "\n", raw)
    text = html.unescape(re.sub(r"<[^>]+>", " ", raw))
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    return re.sub(r"\n\s*\n\s*\n+", "\n\n", text).strip()

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


@tool
def web_search(query: str) -> str:
    """Search the web and return the top results (title, snippet, URL).
    Use when the task needs current information you don't have. Follow up with
    read_webpage on a URL to read a promising result in full."""
    try:
        r = requests.post(
            "https://html.duckduckgo.com/html/", data={"q": query}, timeout=15,
            headers={"User-Agent": "Mozilla/5.0 (local-agents-studio)"})
        r.raise_for_status()
    except Exception as e:  # noqa: BLE001
        return f"Error searching: {e}"
    # DuckDuckGo's HTML endpoint: no API key, no tracking, works offline-ish.
    hits = re.findall(
        r'result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>.*?'
        r'result__snippet"[^>]*>(.*?)</a>',
        r.text, re.DOTALL)
    if not hits:
        return f"No results for '{query}'."
    out = []
    for url, title, snippet in hits[:6]:
        url = unquote(re.sub(r"^.*?uddg=", "", url).split("&")[0]) if "uddg=" in url else url
        out.append(f"- {_strip_html(title)}\n  {url}\n  {_strip_html(snippet)[:200]}")
    return "\n".join(out)


@tool
def read_webpage(url: str) -> str:
    """Fetch a web page and return its readable text (scripts/markup stripped).
    Use after web_search, or on any URL you need to actually read."""
    try:
        r = requests.get(url, timeout=20,
                         headers={"User-Agent": "Mozilla/5.0 (local-agents-studio)"})
        r.raise_for_status()
    except Exception as e:  # noqa: BLE001
        return f"Error fetching {url}: {e}"
    text = _strip_html(r.text)
    return text[:8000] + ("\n…[truncated]" if len(text) > 8000 else "")


def _missing(path: str, root: str) -> str:
    """Error for a path that isn't there — naming what IS there.

    Models reach for placeholder paths ('/path/to/smoke_test.py') and, told only
    that the file is absent, call again with the same placeholder. Listing the
    real files corrects the mistake in one round instead of burning the budget.
    """
    try:
        have = sorted(f for f in os.listdir(root) if not f.startswith((".", "__")))
    except OSError:
        have = []
    listing = ", ".join(have) if have else "(workspace is empty)"
    return (f"Error: {path} does not exist in the workspace. "
            f"Files here: {listing}. Use a plain relative path, e.g. 'smoke_test.py' — "
            "not an absolute path and not a placeholder.")


def _head(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + "\n…[truncated]"


def _tail(text: str, limit: int) -> str:
    return text if len(text) <= limit else "…[earlier output truncated]\n" + text[-limit:]


def make_run_python(workspace: str):
    """Build the run_python tool bound to this run's workspace.

    WARNING: this executes real code with the user's permissions. It is confined
    to the workspace directory and a 30s timeout, but a script can still do
    anything Python can — it is opt-in per agent for that reason.
    """
    root = os.path.realpath(workspace)

    @tool
    def run_python(path: str) -> str:
        """Run a Python file from the workspace and return its output.

        Use this to VERIFY code you wrote actually runs: write the file first
        (files tool), then run it, then fix whatever the traceback shows.
        Times out after 30 seconds.
        """
        full = os.path.realpath(os.path.join(root, path.lstrip("/")))
        if full != root and not full.startswith(root + os.sep):
            return "Error: path escapes the workspace"
        if not os.path.isfile(full):
            return _missing(path, root)
        try:
            # Mock GPIO by default: gpiozero's mock pin factory lets real
            # Raspberry Pi code execute on a machine with no GPIO header, which
            # is what makes Pi programs verifiable here at all. MockPWMPin is not
            # the default and matters — the plain mock pin raises
            # PinPWMUnsupported, so without it no PWMLED/servo program (anything
            # that fades, dims or sweeps) could ever be verified.
            env = {**os.environ, "GPIOZERO_PIN_FACTORY": "mock",
                   "GPIOZERO_MOCK_PIN_CLASS": "MockPWMPin"}
            p = subprocess.run([sys.executable, full], cwd=root, timeout=30,
                               capture_output=True, text=True, env=env)
        except subprocess.TimeoutExpired:
            return (f"Error: {path} did not finish within 30s. Something is looping or "
                    "blocking — a `while True:`, a `pause()`, or a long sleep running at "
                    "module level. Move it inside `if __name__ == '__main__':` so that "
                    "importing the module does not execute it. Do not simply delete the "
                    "loop.")
        except Exception as e:  # noqa: BLE001
            return f"Error running {path}: {e}"
        parts = [f"exit code: {p.returncode}"]
        if p.stdout.strip():
            parts.append("stdout:\n" + _head(p.stdout.strip(), 3000))
        if p.stderr.strip():
            # TAIL, not head. A Python traceback ends with the line that actually
            # explains the failure and begins with framework frames nobody needs;
            # truncating from the front hands the model 2000 characters of Flask
            # internals with the cause cut off, and it retries blindly instead of
            # fixing anything.
            parts.append("stderr:\n" + _tail(p.stderr.strip(), 2500))
        return "\n".join(parts)

    return run_python


def make_arduino_compile(workspace: str):
    """Build the arduino_compile tool bound to this run's workspace."""
    root = os.path.realpath(workspace)

    @tool
    def arduino_compile(path: str, board: str = "uno") -> str:
        """Compile an Arduino sketch with the real AVR toolchain and report errors.

        `path` is a .ino file in the workspace. `board` is uno, nano, mega or
        leonardo. A sketch is not working until this returns SUCCESS — compile
        errors come back with the exact file, line and message.
        """
        fqbn = {"uno": "arduino:avr:uno", "nano": "arduino:avr:nano",
                "mega": "arduino:avr:mega", "leonardo": "arduino:avr:leonardo"}.get(
                    board.lower())
        if not fqbn:
            return "Error: board must be one of uno, nano, mega, leonardo"
        cli = shutil.which("arduino-cli") or os.path.expanduser("~/.local/bin/arduino-cli")
        if not os.path.exists(cli):
            return "Error: arduino-cli is not installed on this machine."

        full = os.path.realpath(os.path.join(root, path.lstrip("/")))
        if not full.startswith(root + os.sep):
            return "Error: path escapes the workspace"
        if not os.path.isfile(full):
            return _missing(path, root)
        # arduino-cli requires the sketch to live in a directory of the same
        # name (Blink/Blink.ino), which models forget constantly — so stage it
        # into a correct layout instead of failing on a technicality.
        stem = os.path.splitext(os.path.basename(full))[0]
        sketch_dir = os.path.join(root, ".build", stem)
        os.makedirs(sketch_dir, exist_ok=True)
        shutil.copyfile(full, os.path.join(sketch_dir, f"{stem}.ino"))
        try:
            p = subprocess.run([cli, "compile", "--fqbn", fqbn, sketch_dir],
                               capture_output=True, text=True, timeout=180)
        except subprocess.TimeoutExpired:
            return "Error: compile did not finish within 180s"
        except Exception as e:  # noqa: BLE001
            return f"Error running arduino-cli: {e}"
        if p.returncode == 0:
            usage = [ln for ln in p.stdout.splitlines()
                     if "program storage" in ln or "dynamic memory" in ln]
            return "COMPILE SUCCESS for " + board + "\n" + "\n".join(usage)
        # Errors land on stderr; keep the tail, where the diagnostics are.
        return "COMPILE FAILED\n" + _tail((p.stderr or p.stdout).strip(), 2500)

    return arduino_compile


def make_check_stl(workspace: str):
    """Build the check_stl tool bound to this run's workspace."""
    root = os.path.realpath(workspace)

    @tool
    def check_stl(path: str) -> str:
        """Inspect an STL and report whether it is actually 3D-printable.

        Checks the mesh is watertight (a printer cannot slice a mesh with holes),
        has positive volume, is a single connected body, and reports its size in
        mm. Run this on every STL you generate — a model that looks right in code
        can still be an unprintable shell.
        """
        try:
            import trimesh
        except ImportError:
            return "Error: trimesh is not installed."
        full = os.path.realpath(os.path.join(root, path.lstrip("/")))
        if not full.startswith(root + os.sep):
            return "Error: path escapes the workspace"
        if not os.path.isfile(full):
            return _missing(path, root) + " Generate the STL first by running model.py."
        try:
            mesh = trimesh.load(full, force="mesh")
        except Exception as e:  # noqa: BLE001
            return f"Error: could not read {path} as a mesh: {e}"
        if mesh.is_empty or len(mesh.faces) == 0:
            return f"FAIL: {path} contains no geometry."

        x, y, z = mesh.extents
        bodies = mesh.body_count
        lines = [
            f"triangles: {len(mesh.faces)}",
            f"size: {x:.1f} x {y:.1f} x {z:.1f} mm",
            f"volume: {mesh.volume / 1000.0:.2f} cm3",
            f"watertight: {mesh.is_watertight}",
            f"separate bodies: {bodies}",
        ]
        problems = []
        if not mesh.is_watertight:
            problems.append("NOT WATERTIGHT — the mesh has holes and a slicer will "
                            "refuse it or print garbage. Build solids with boolean "
                            "unions, never loose surfaces.")
        if mesh.volume <= 0:
            problems.append("VOLUME IS ZERO OR NEGATIVE — the faces are probably "
                            "inside-out (inverted normals).")
        if bodies > 1:
            problems.append(f"{bodies} DISCONNECTED BODIES — parts float free of each "
                            "other. Union them, or make them overlap.")
        if max(mesh.extents) > 300:
            problems.append(f"{max(mesh.extents):.0f} mm exceeds a typical 256 mm bed.")
        verdict = "STL OK — printable." if not problems else "STL PROBLEMS:\n- " + \
                                                             "\n- ".join(problems)
        return "\n".join(lines) + "\n" + verdict

    return check_stl


@tool
def knowledge_search(query: str) -> str:
    """Search the team's shared knowledge base (past reports and notes) for a
    topic. Use this FIRST when a task might build on prior work. Returns matching
    note paths with snippets; read the full note with knowledge_read."""
    import knowledge
    hits = knowledge.search(query, limit=8)
    if not hits:
        return f"No notes found for '{query}'."
    return "\n".join(f"- [{h['title']}] ({h['path']})\n  {h['snippet']}" for h in hits)


@tool
def knowledge_read(path: str) -> str:
    """Read a full note from the shared knowledge base by its path (as returned
    by knowledge_search). Use to pull in prior findings before doing new work."""
    import knowledge
    try:
        return knowledge.read_note(path, strip_meta=True)[:12000]
    except Exception as e:  # noqa: BLE001
        return f"Error: {e}"


@tool
def knowledge_write(title: str, content: str, folder: str = "notes") -> str:
    """Save a note to the shared knowledge base so future runs can reference it.
    Use for durable findings, decisions, or reference material worth keeping.
    `content` is Markdown; use [[wikilinks]] to relate notes.

    `folder` groups related knowledge into a topic sub-vault (e.g. 'recipes',
    'project-x/decisions') — file notes with their topic so a whole topic can
    be reviewed or removed together. Defaults to 'notes'."""
    import knowledge
    folder = re.sub(r"[^\w/ -]", "", folder or "notes").strip("/ ") or "notes"
    try:
        rel = knowledge.write_note(title, content, tags=["agent-note"],
                                   meta_extra={"source": "agent"}, subdir=folder)
        return f"Saved as {rel}"
    except Exception as e:  # noqa: BLE001
        return f"Error: {e}"


@tool
def generate_image(prompt: str, negative: str = "") -> str:
    """Generate an image locally from a text prompt using the Fooocus backend.
    Use when the task asks for a picture, illustration, logo or visual. `prompt`
    describes the desired image; `negative` (optional) lists things to avoid.
    Returns the saved image path (viewable at /api/imagegen/images/<name>), or an
    error if the image backend is not installed/running (see the Models page)."""
    import imagegen
    st = imagegen.backend_status()
    if not st.get("running"):
        return ("Image backend is not running. Install/start Fooocus from the "
                "Models page (Image generation section) first.")
    res = imagegen.generate(prompt, negative=negative)
    if not res.get("ok"):
        return f"Image generation failed: {res.get('error')}"
    names = res.get("images") or []
    if not names:
        return "No image was returned."
    return "Generated image(s): " + ", ".join(f"/api/imagegen/images/{n}" for n in names)


def make_workspace_tools(workspace: str):
    """File tools bound to a run's workspace directory (path-traversal safe)."""

    def _safe(path: str) -> str:
        full = os.path.realpath(os.path.join(workspace, path.lstrip("/")))
        if not full.startswith(os.path.realpath(workspace) + os.sep) and \
                full != os.path.realpath(workspace):
            raise ValueError("path escapes workspace")
        return full

    def _syntax_error(path: str, content: str):
        """Reject a .py write that would not even parse.

        A model whose edit lands at the wrong indentation corrupts the file, and
        every later run fails on the SyntaxError instead of the real bug — the
        agent then loops forever against a file that cannot import. Refusing the
        write keeps the last good version on disk and hands back the exact line.
        """
        if not path.endswith(".py"):
            return None
        try:
            compile(content, path, "exec")
            return None
        except SyntaxError as e:
            return (f"Error: refused — this would leave {path} unparseable. "
                    f"{type(e).__name__}: {e.msg} (line {e.lineno}). The file is "
                    "unchanged; re-read it and match the existing indentation.")

    @tool
    def write_file(path: str, content: str) -> str:
        """Write content to a file in the shared workspace. Relative paths only."""
        try:
            full = _safe(path)
            bad = _syntax_error(path, content)
            if bad:
                return bad
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, "w", encoding="utf-8") as f:
                f.write(content)
            return f"Wrote {len(content)} chars to {path}"
        except Exception as e:  # noqa: BLE001
            return f"Error: {e}"

    @tool
    def edit_file(path: str, old_text: str, new_text: str) -> str:
        """Replace an exact snippet in a workspace file — the way to FIX one line.

        Prefer this over write_file when changing existing code: you only emit the
        few lines that change, not the whole file. old_text must appear exactly
        once in the file (copy it from read_file, including indentation).
        """
        try:
            full = _safe(path)
            with open(full, encoding="utf-8") as f:
                text = f.read()
            hits = text.count(old_text)
            if hits == 0:
                return ("Error: old_text not found — copy it exactly from read_file, "
                        "including indentation and line breaks.")
            if hits > 1:
                return (f"Error: old_text appears {hits} times; include more "
                        "surrounding lines so it matches exactly one place.")
            updated = text.replace(old_text, new_text)
            bad = _syntax_error(path, updated)
            if bad:
                return bad
            with open(full, "w", encoding="utf-8") as f:
                f.write(updated)
            return f"Edited {path}: replaced 1 occurrence."
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

    return [write_file, edit_file, read_file, list_files]


TOOL_CATALOG = {
    "calculator": "Math expression evaluator",
    "current_datetime": "Current date and time",
    "http_get": "Fetch a URL (needs internet)",
    "web_search": "Search the web for current information (needs internet)",
    "read_webpage": "Read a web page as clean text (needs internet)",
    "run_python": "Run a Python file from the workspace — executes real code",
    "arduino_compile": "Compile an Arduino sketch with the real AVR toolchain",
    "check_stl": "Check an STL is watertight and 3D-printable",
    "files": "Read/write files in the run workspace",
    "knowledge": "Search/read/write the shared knowledge vault",
    "generate_image": "Generate an image locally (needs Fooocus running)",
}

CUSTOM_TOOLS_DIR = os.environ.get(
    "AGENTS_CUSTOM_TOOLS",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "custom_tools"),
)

CUSTOM_TOOL_TEMPLATE = '''"""Custom tool — one or more @tool functions per file.

The function name becomes the tool name agents call. The docstring is what
the model reads to decide WHEN to use it, so describe the purpose and the
arguments clearly. Return a string (it is fed back to the model).
"""
from langchain_core.tools import tool


@tool
def word_count(text: str) -> str:
    """Count the words in a text. Use when asked how long a text is."""
    return f"{len(text.split())} words"
'''


def load_custom_tools():
    """Discover LangChain tools in custom_tools/*.py.

    Returns (tools_by_name, files) where files is a list of
    {file, tools: [names], error} — broken files never break the app.
    """
    import importlib.util
    from langchain_core.tools import BaseTool

    by_name, files = {}, []
    if not os.path.isdir(CUSTOM_TOOLS_DIR):
        return by_name, files
    for fn in sorted(os.listdir(CUSTOM_TOOLS_DIR)):
        if not fn.endswith(".py") or fn.startswith("_"):
            continue
        path = os.path.join(CUSTOM_TOOLS_DIR, fn)
        entry = {"file": fn, "tools": [], "error": None}
        try:
            spec = importlib.util.spec_from_file_location(
                f"agents_custom_tools_{fn[:-3]}", path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            for obj in vars(mod).values():
                if isinstance(obj, BaseTool):
                    by_name[obj.name] = obj
                    entry["tools"].append(obj.name)
            if not entry["tools"]:
                entry["error"] = "No @tool functions found in this file."
        except Exception as e:  # noqa: BLE001 - user code can fail arbitrarily
            entry["error"] = f"{type(e).__name__}: {e}"
        files.append(entry)
    return by_name, files


def validate_tool_code(code: str):
    """Load tool code from a temp file. Returns (tool_names, error)."""
    import importlib.util
    import tempfile
    from langchain_core.tools import BaseTool

    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False,
                                     encoding="utf-8") as f:
        f.write(code)
        path = f.name
    try:
        spec = importlib.util.spec_from_file_location("agents_wizard_check", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        names = [o.name for o in vars(mod).values() if isinstance(o, BaseTool)]
        if not names:
            return [], ("No tool found. Decorate a function with @tool from "
                        "langchain_core.tools.")
        return names, None
    except Exception as e:  # noqa: BLE001 - generated code can fail arbitrarily
        return [], f"{type(e).__name__}: {e}"
    finally:
        os.unlink(path)


def full_catalog() -> dict:
    """Everything the UI and validators need to know about tools."""
    custom_by_name, files = load_custom_tools()
    custom = []
    for entry in files:
        for name in entry["tools"]:
            custom.append({"name": name, "file": entry["file"],
                           "description": (custom_by_name[name].description or "")[:200]})
    return {
        "builtin": [{"name": k, "description": v} for k, v in TOOL_CATALOG.items()],
        "custom": custom,
        "files": files,
        "template": CUSTOM_TOOL_TEMPLATE,
    }


def valid_tool_names() -> set:
    custom_by_name, _files = load_custom_tools()
    return set(TOOL_CATALOG) | set(custom_by_name)


def resolve_tools(names: list, workspace: str) -> list:
    custom_by_name, _files = load_custom_tools()
    tools = []
    for n in names or []:
        if n == "calculator":
            tools.append(calculator)
        elif n == "current_datetime":
            tools.append(current_datetime)
        elif n == "http_get":
            tools.append(http_get)
        elif n == "web_search":
            tools.append(web_search)
        elif n == "read_webpage":
            tools.append(read_webpage)
        elif n == "run_python":
            tools.append(make_run_python(workspace))
        elif n == "arduino_compile":
            tools.append(make_arduino_compile(workspace))
        elif n == "check_stl":
            tools.append(make_check_stl(workspace))
        elif n == "files":
            tools.extend(make_workspace_tools(workspace))
        elif n == "knowledge":
            tools.extend([knowledge_search, knowledge_read, knowledge_write])
        elif n == "generate_image":
            tools.append(generate_image)
        elif n in custom_by_name:
            tools.append(custom_by_name[n])
    return tools
