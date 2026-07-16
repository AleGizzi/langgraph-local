"""LangGraph engine: compiles a team definition into a graph and runs it,
emitting streaming events through a callback.

Topologies
----------
- single:     one agent answers the task.
- pipeline:   agents run in order; each sees the task plus all prior outputs.
              Optional quality loop: the last agent acts as reviewer and can
              send work back with feedback (bounded by max_revisions).
- supervisor: agent[0] is the supervisor. It repeatedly picks a worker and an
              instruction until it decides to FINISH, then writes the final
              answer itself. Bounded by max_steps.

Local 7B models produce unreliable JSON, so all routing parses defensively
and always falls back to something sane instead of crashing the run.
"""
import json
import operator
import os
import re
import threading
import time
from typing import Annotated, Optional

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

from providers import LLM_IDLE_TIMEOUT, make_llm
from tools import resolve_tools

# One fix cycle for a verifying agent costs three rounds (run → read → write), so
# a budget of 5 could not complete two attempts and the agent silently gave up
# mid-repair. Tunable for anyone who wants a tighter leash.
MAX_TOOL_ROUNDS = int(os.environ.get("MAX_TOOL_ROUNDS", "14"))

# Preferred executor for tool delegation (see _delegate_loop): agents whose
# model can't call tools hand tool work to this model. "provider::model" or
# bare model name (assumed ollama); empty = auto-pick a tool-capable model.
TOOL_DELEGATE_MODEL = os.environ.get("TOOL_DELEGATE_MODEL", "")

# (provider, model) -> bool. Seeded from the catalog's capability tags,
# corrected at runtime when a provider rejects tool binding.
_tool_support_cache = {}


def _model_supports_tools(provider: str, model: str) -> bool:
    key = (provider, model)
    if key in _tool_support_cache:
        return _tool_support_cache[key]
    verdict = None
    try:
        import catalog
        data = catalog.load_cache() or {}
        base = model.split(":")[0].lower()
        for m in data.get("models", []):
            if (m.get("base") or "").lower() == base:
                caps = [c.lower() for c in (m.get("capabilities") or [])]
                verdict = "tools" in caps
                break
    except Exception:  # noqa: BLE001 - catalog is advisory only
        verdict = None
    if verdict is None:
        verdict = True  # optimistic: the runtime error path corrects this
    _tool_support_cache[key] = verdict
    return verdict


def _mark_no_tools(provider: str, model: str):
    _tool_support_cache[(provider, model)] = False


# Accept both the fenced form and a bare "DELEGATE: ..." line — small models
# follow one or the other, rarely both consistently.
_DELEGATE_BLOCK_RE = re.compile(
    r"```delegate\s*\n(.*?)```|^[ \t]*DELEGATE:[ \t]*(.+)$",
    re.DOTALL | re.MULTILINE | re.IGNORECASE)


def _find_delegate_request(text: str):
    m = _DELEGATE_BLOCK_RE.search(text or "")
    if not m:
        return None
    return (m.group(1) or m.group(2) or "").strip() or None


def pick_delegate_model():
    """The tool-capable (provider, model) that executes delegated tool work,
    or None if no local model can call tools."""
    if TOOL_DELEGATE_MODEL:
        prov, sep, mdl = TOOL_DELEGATE_MODEL.partition("::")
        return (prov, mdl) if sep else ("ollama", TOOL_DELEGATE_MODEL)
    try:
        from providers import list_models
        available = list_models()
        for prov in ("ollama", "lmstudio"):
            models = available.get(prov) or []
            pick = (next((m for m in models if m.startswith("qwen2.5:")), None)
                    or next((m for m in models
                             if _model_supports_tools(prov, m)
                             and not re.search(r"r1|think", m, re.I)), None))
            if pick:
                return (prov, pick)
    except Exception:  # noqa: BLE001 - discovery is best-effort
        pass
    return None


def delegate_instructions(tool_list) -> str:
    """System-prompt addendum teaching a tool-less model the DELEGATE protocol."""
    tool_lines = "\n".join(f"- {t.name}: {(t.description or '').strip()[:150]}"
                           for t in tool_list)
    return (
        "\n\n## TOOL ACCESS — READ CAREFULLY\n"
        "You cannot run tools yourself. A tool assistant runs them for you. "
        "Capabilities available through it:\n" + tool_lines + "\n\n"
        "To use a capability, end your reply with a single line:\n"
        "DELEGATE: <one clear, self-contained instruction with every needed value>\n"
        "…and write NOTHING after that line. The assistant's result arrives "
        "in the next message; then you continue.\n"
        "Example:\n"
        "  DELEGATE: search the knowledge base for \"backup policy\" and "
        "return the note text\n\n"
        "STRICT RULES:\n"
        "- NEVER invent, guess or imagine what a capability would return.\n"
        "- If the task needs stored data, files, a URL or a calculation, "
        "your FIRST reply must be a DELEGATE line.\n"
        "- Only write your final answer once you truly have the results."
    )


_CALL_START_RE = re.compile(r'\{\s*"name"\s*:\s*"([A-Za-z0-9_]+)"')
_ARG_KEYS = ("arguments", "parameters", "args", "input")


def salvage_tool_calls(content: str, tool_names) -> list:
    """Recover tool calls a model printed as TEXT instead of calling properly.

    Some models advertise Ollama's `tools` capability and still emit
    `{"name": "run_python", "arguments": {...}}` into the content stream —
    qwen2.5-coder:7b does exactly this. Untreated, tools bind, the model
    "calls" one, nothing executes, and the agent reports success having done
    nothing at all. (Invariant 1: parse model output defensively.)

    Scans with a real JSON decoder rather than a regex, because the arguments
    are routinely a whole source file full of braces, quotes and newlines. A
    non-greedy `{.*?}` truncates at the first `}` inside an f-string or a dict
    literal, fails to parse, and drops the call on the floor — which is exactly
    the silent failure this function exists to prevent.

    Only salvages a call whose name is actually bound and whose arguments decode
    to a JSON object, so prose that merely mentions a tool is never mistaken for
    a call.
    """
    calls, decoder, text = [], json.JSONDecoder(), content or ""
    for m in _CALL_START_RE.finditer(text):
        if m.group(1) not in tool_names:
            continue
        try:
            obj, _end = decoder.raw_decode(text, m.start())
        except ValueError:
            continue
        if not isinstance(obj, dict) or obj.get("name") not in tool_names:
            continue
        args = next((obj[k] for k in _ARG_KEYS if isinstance(obj.get(k), dict)), None)
        if args is None:
            continue
        # Shape must be exactly LangChain's ToolCall — an extra key here makes
        # AIMessage(tool_calls=...) raise.
        calls.append({"name": obj["name"], "args": args,
                      "id": f"salvaged_{len(calls)}"})
    return calls


class RunCancelled(Exception):
    pass


class TeamState(TypedDict, total=False):
    task: str
    # append-only via reducer so parallel branches can write concurrently
    history: Annotated[list, operator.add]   # [{agent, content, ts}]
    feedback: Optional[str]
    revision: int
    supervisor_steps: int
    next_agent: Optional[str]
    instruction: Optional[str]
    final: Optional[str]


def _strip_reasoning(text: str) -> str:
    """Remove <think>...</think> blocks emitted by reasoning models (DeepSeek-R1).

    If the model spent its whole budget thinking (nothing outside the block),
    the thinking itself is the only output we have — return it rather than
    silently producing an empty result.
    """
    stripped = re.sub(r"<think>.*?</think>\s*", "", text, flags=re.DOTALL).strip()
    if stripped:
        return stripped
    return re.sub(r"</?think>", "", text).strip()


# Matches a fenced code block, capturing the info string and the body.
_FENCE_RE = re.compile(r"```([^\n]*)\n(.*?)```", re.DOTALL)
# A relative file path with a real extension (must contain a letter, so
# version strings like "1.2.3" don't match). No spaces, no traversal.
_PATH_RE = re.compile(r"^[\w./-]+\.[A-Za-z][A-Za-z0-9]{0,11}$")
# Header line right before a fence naming the file: "File: x", "**x**", "### x".
_HEADER_RE = re.compile(
    r"(?:^|\n)[ \t]*(?:\*\*|####?\s*|//\s*|#\s*)?"
    r"(?:File|file|FILE|Filename|filename|Path|path)?[:\s]*"
    r"`?([\w./-]+\.[A-Za-z][A-Za-z0-9]{0,11})`?\**[ \t]*$")


def _safe_workspace_path(workspace: str, rel: str) -> str:
    full = os.path.realpath(os.path.join(workspace, rel.lstrip("/")))
    root = os.path.realpath(workspace)
    if full != root and not full.startswith(root + os.sep):
        raise ValueError("path escapes workspace")
    return full


def extract_files(content: str, workspace: str) -> list:
    """Save fenced code blocks that name a file into the run workspace.

    Local models can't be trusted to call write_file for every file, so the
    engine extracts deliverables from the text itself. A block names its file
    either in the fence info string (```python app.py) or in a header line just
    above the fence (File: app.py / **app.py** / ### app.py). Returns the
    relative paths written.
    """
    written = []
    for m in _FENCE_RE.finditer(content or ""):
        info, body = m.group(1).strip(), m.group(2)
        path = None
        # fence info: last token that looks like a path wins (skip bare lang)
        for tok in reversed(info.split()):
            tok = tok.strip("`")
            if _PATH_RE.fullmatch(tok) and ("." in tok):
                # a bare language like "py" has no dot; tok always has one here
                path = tok
                break
        if not path:
            # look at the last non-empty line above the fence
            head = content[:m.start()].rstrip("\n")
            last_line = head.rsplit("\n", 1)[-1] if head else ""
            hm = _HEADER_RE.search("\n" + last_line)
            if hm:
                path = hm.group(1)
        if not path:
            continue
        try:
            full = _safe_workspace_path(workspace, path)
        except ValueError:
            continue
        try:
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, "w", encoding="utf-8") as f:
                f.write(body if body.endswith("\n") else body + "\n")
            written.append(os.path.relpath(full, workspace))
        except OSError:
            continue
    return written


def _history_block(history: list) -> str:
    if not history:
        return "(no previous work yet)"
    parts = []
    for h in sorted(history, key=lambda x: x.get("ts", 0)):
        parts.append(f"### Output from {h['agent']}\n{h['content']}")
    return "\n\n".join(parts)


def chat_stream(agent: dict, messages: list, workspace: str, skill_map: dict):
    """Generator for the Chat page: yields event dicts for one assistant turn.

    `messages` is the prior conversation: [{role: 'user'|'assistant', content}].
    Supports the same tool loop as team runs, bounded by MAX_TOOL_ROUNDS.
    """
    from langchain_core.messages import AIMessage as AIM

    system = (agent.get("system_prompt") or "You are a helpful assistant.").strip()
    for sname in agent.get("skills") or []:
        s = skill_map.get(sname)
        if s and s.get("instructions"):
            system += f"\n\n## Skill: {s['name']}\n{s['instructions']}"

    llm = make_llm(agent.get("provider", "ollama"), agent["model"],
                   dict(agent.get("params") or {}))
    tool_list = resolve_tools(agent.get("tools", []), workspace)
    tool_map = {t.name: t for t in tool_list}

    # Models that can't bind tools (deepseek-r1, gemma3, …) delegate tool work
    # to a tool-capable executor — same DELEGATE protocol as team runs — so
    # tools work in chat regardless of the model picked.
    delegate = None
    if tool_list and not _model_supports_tools(agent.get("provider", "ollama"),
                                               agent["model"]):
        delegate = pick_delegate_model()
        if delegate:
            system += delegate_instructions(tool_list)
            yield {"type": "tool_result",
                   "content": f"ℹ {agent['model']} can't call tools natively — "
                              f"tool requests are delegated to {delegate[1]}."}
        else:
            yield {"type": "tool_result",
                   "content": "ℹ no tool-capable model available — running "
                              "without tools."}
            tool_list, tool_map = [], {}
    if tool_list and not delegate:
        llm = llm.bind_tools(tool_list)

    executor_llm = None
    if delegate:
        executor_llm = make_llm(delegate[0], delegate[1],
                                {"temperature": 0.1, "num_predict": 1200}
                                ).bind_tools(tool_list)

    msgs = [SystemMessage(content=system)]
    for m in messages:
        cls = HumanMessage if m.get("role") == "user" else AIM
        msgs.append(cls(content=str(m.get("content", ""))))

    final = ""
    usage = {"input_tokens": 0, "output_tokens": 0, "tok_s": None}
    for _round in range(MAX_TOOL_ROUNDS + 1):
        full = None
        for chunk in llm.stream(msgs):
            full = chunk if full is None else full + chunk
            if chunk.content:
                text = chunk.content if isinstance(chunk.content, str) else str(chunk.content)
                yield {"type": "token", "content": text}
        if full is None:
            break
        # Track real token counts when the provider reports them. input_tokens
        # of the LAST round is the whole conversation as the model saw it;
        # output accumulates across tool rounds. Ollama's prompt_eval_count
        # skips KV-cached tokens, so this can under-report — the UI pairs it
        # with a deterministic estimate and shows whichever is larger.
        um = getattr(full, "usage_metadata", None) or {}
        if um.get("input_tokens"):
            usage["input_tokens"] = um["input_tokens"]
        usage["output_tokens"] += um.get("output_tokens") or 0
        rm = getattr(full, "response_metadata", None) or {}
        if rm.get("eval_count") and rm.get("eval_duration"):
            usage["tok_s"] = round(rm["eval_count"] / (rm["eval_duration"] / 1e9), 1)
        content = full.content if isinstance(full.content, str) else str(full.content)

        if delegate:
            request = _find_delegate_request(content)
            if not request or _round == MAX_TOOL_ROUNDS:
                final = _strip_reasoning(
                    _DELEGATE_BLOCK_RE.sub("", content).strip())
                break
            yield {"type": "tool_call",
                   "content": f"delegate → {delegate[1]}: {request[:220]}"}
            xmsgs = [SystemMessage(content=(
                        "You are a precise tool-execution assistant. Fulfill the "
                        "request using your tools. Reply with only the factual "
                        "result (values, file paths, retrieved content) — no "
                        "commentary.")),
                     HumanMessage(content=request)]
            result = ""
            for _x in range(MAX_TOOL_ROUNDS + 1):
                resp = executor_llm.invoke(xmsgs)
                xcontent = resp.content if isinstance(resp.content, str) else str(resp.content)
                xcalls = getattr(resp, "tool_calls", []) or []
                if not xcalls:
                    xcalls = salvage_tool_calls(xcontent, tool_map)
                if not xcalls or _x == MAX_TOOL_ROUNDS:
                    result = xcontent
                    break
                xmsgs.append(AIMessage(content=xcontent, tool_calls=xcalls))
                for call in xcalls:
                    name, args = call.get("name"), call.get("args") or {}
                    yield {"type": "tool_call",
                           "content": f"{name}({json.dumps(args, ensure_ascii=False)[:300]})"}
                    fn = tool_map.get(name)
                    try:
                        r = fn.invoke(args) if fn else f"Unknown tool {name}"
                    except Exception as e:  # noqa: BLE001
                        r = f"Tool error: {e}"
                    yield {"type": "tool_result", "content": str(r)[:1000]}
                    xmsgs.append(ToolMessage(content=str(r),
                                             tool_call_id=call.get("id", name)))
            msgs.append(AIM(content=content))
            msgs.append(HumanMessage(content=(
                f"[Tool assistant result]\n{result}\n\n"
                "Now ANSWER THE USER'S ORIGINAL QUESTION using this result — "
                "in plain language, as a normal reply. Do NOT delegate again "
                "unless the original question truly needs a different "
                "capability; do not invent extra calculations or follow-up "
                "steps the user never asked for.")))
            continue

        calls = getattr(full, "tool_calls", []) or []
        if not calls and tool_map:
            calls = salvage_tool_calls(content, tool_map)
        response = AIMessage(content=content, tool_calls=calls)
        calls = response.tool_calls
        if not calls or _round == MAX_TOOL_ROUNDS:
            final = _strip_reasoning(response.content)
            break
        msgs.append(response)
        for call in calls:
            name, args = call.get("name"), call.get("args") or {}
            yield {"type": "tool_call",
                   "content": f"{name}({json.dumps(args, ensure_ascii=False)[:300]})"}
            fn = tool_map.get(name)
            try:
                result = fn.invoke(args) if fn else f"Unknown tool {name}"
            except Exception as e:  # noqa: BLE001
                result = f"Tool error: {e}"
            yield {"type": "tool_result", "content": str(result)[:1000]}
            msgs.append(ToolMessage(content=str(result), tool_call_id=call.get("id", name)))

    # Context-fill report for the UI gauge: what the window holds now (this
    # whole conversation + the reply), against the window actually in effect.
    est = (sum(len(str(getattr(m, "content", ""))) for m in msgs)
           + len(final)) // 4
    from providers import model_context_limit
    yield {"type": "usage",
           "input_tokens": usage["input_tokens"],
           "output_tokens": usage["output_tokens"],
           "est_tokens": est,
           "tok_s": usage["tok_s"],
           "num_ctx": int((agent.get("params") or {}).get("num_ctx") or 8192),
           "model_max": model_context_limit(agent.get("provider", "ollama"),
                                            agent["model"])}
    yield {"type": "done", "content": final}


class TeamRunner:
    """Runs one team on one task, emitting events via `emit(type, **kw)`."""

    def __init__(self, team: dict, task: str, workspace: str, emit, cancel_event,
                 max_concurrency: int = 1):
        self.team = team
        self.task = task
        self.workspace = workspace
        self.emit = emit
        self.cancel = cancel_event
        self.agents = {a["name"]: a for a in team["agents"]}
        self.settings = team.get("settings", {})
        try:
            import storage
            self.skill_map = {s["name"]: s for s in storage.list_skills()}
        except Exception:  # noqa: BLE001 - skills are optional
            self.skill_map = {}
        # Gates concurrent LLM calls: >1 only when the parallel toggle is on
        # and the hardware assessment says the machine can take it.
        self.llm_gate = threading.Semaphore(max(1, max_concurrency))

    # ---------------- LLM helpers ----------------

    def _llm_for(self, agent: dict):
        params = dict(agent.get("params") or {})
        # Back-compat: older teams stored temperature at the top level.
        if "temperature" not in params and agent.get("temperature") is not None:
            params["temperature"] = agent["temperature"]
        return make_llm(agent.get("provider", "ollama"), agent["model"], params)

    def _check_cancel(self):
        if self.cancel.is_set():
            raise RunCancelled()

    def _stream_call(self, agent: dict, messages: list) -> str:
        """Call the agent's LLM with its tools, streaming tokens out.

        Runs a bounded tool loop: while the model requests tool calls,
        execute them and feed results back.
        """
        llm = self._llm_for(agent)
        tool_list = resolve_tools(agent.get("tools", []), self.workspace)
        tool_map = {t.name: t for t in tool_list}
        provider = agent.get("provider", "ollama")
        # Models that can't bind tools (reasoning models like deepseek-r1)
        # delegate tool work to a tool-capable executor instead of erroring.
        use_delegate = bool(tool_list) and not _model_supports_tools(provider, agent["model"])
        if tool_list and not use_delegate:
            llm = llm.bind_tools(tool_list)

        with self.llm_gate:
            if use_delegate:
                return self._delegate_loop(agent, tool_list, list(messages))
            last_err = None
            for attempt in (1, 2):
                try:
                    return self._tool_loop(agent, llm, tool_map, list(messages))
                except Exception as e:  # noqa: BLE001 - translate stalls to a clear error
                    if tool_list and "does not support tools" in str(e).lower():
                        # Catalog was wrong/missing — remember and delegate.
                        _mark_no_tools(provider, agent["model"])
                        self.emit("decision", agent=agent["name"],
                                  content=f"{agent['model']} can't use tools natively "
                                          "— delegating tool work to a capable model.")
                        return self._delegate_loop(agent, tool_list, list(messages))
                    name = type(e).__name__.lower()
                    if not ("timeout" in name or "timed out" in str(e).lower()):
                        raise
                    last_err = e
                    if attempt == 1:
                        # Ollama keeps the evaluated prompt prefix cached, so a
                        # retry resumes much faster than the first attempt.
                        self.emit("decision", agent=agent["name"],
                                  content=f"Stream stalled after {LLM_IDLE_TIMEOUT:.0f}s "
                                          "with no output — retrying once…")
                        self._check_cancel()
            raise RuntimeError(
                f"{agent['name']}: model stream stalled twice (no output for "
                f"{LLM_IDLE_TIMEOUT:.0f}s). The model server is likely overloaded — "
                "try fewer parallel agents, a smaller model, or a smaller context "
                "window."
            ) from last_err

    # ---------------- tool delegation (models without native tool support) --

    def _delegate_model(self):
        """Pick (and cache) the tool-capable model that executes delegated tool work."""
        if not hasattr(self, "_delegate_cached"):
            self._delegate_cached = pick_delegate_model()
        return self._delegate_cached

    def _delegate_loop(self, agent: dict, tool_list: list, msgs: list) -> str:
        """Tool use for models that can't bind tools natively.

        The primary model keeps doing what it's good at (e.g. reasoning) and
        requests capabilities in a fenced ```delegate block; a tool-capable
        executor model performs the actual tool calls and the result is fed
        back. Bounded like the native tool loop.
        """
        name = agent["name"]
        delegate = self._delegate_model()
        if not delegate:
            self.emit("decision", agent=name,
                      content="No tool-capable model available for delegation — "
                              "running without tools.")
            llm = self._llm_for(agent)
            return self._tool_loop(agent, llm, {}, msgs)

        dprov, dmodel = delegate
        self.emit("decision", agent=name,
                  content=f"{agent['model']} can't call tools natively — tool "
                          f"requests will be delegated to {dmodel}.")
        msgs = list(msgs)
        msgs[0] = SystemMessage(content=msgs[0].content + delegate_instructions(tool_list))
        llm = self._llm_for(agent)

        executor_agent = {"name": name, "model": dmodel, "provider": dprov,
                          "params": {"temperature": 0.1, "num_predict": 1200}}
        executor_llm = make_llm(dprov, dmodel, executor_agent["params"])
        executor_llm = executor_llm.bind_tools(tool_list)
        tool_map = {t.name: t for t in tool_list}

        text = ""
        for _round in range(MAX_TOOL_ROUNDS + 1):
            text = self._tool_loop(agent, llm, {}, msgs)
            request = _find_delegate_request(text)
            if not request or _round == MAX_TOOL_ROUNDS:
                return _DELEGATE_BLOCK_RE.sub("", text).strip()
            self.emit("decision", agent=name,
                      content=f"🤝 delegated to {dmodel}: {request[:140]}")
            result = self._tool_loop(
                executor_agent, executor_llm, tool_map,
                [SystemMessage(content=(
                    "You are a precise tool-execution assistant. Fulfill the "
                    "request using your tools. Reply with only the factual "
                    "result (values, file paths, retrieved content) — no "
                    "commentary.")),
                 HumanMessage(content=request)],
                emit_tokens=False)
            msgs.append(AIMessage(content=text))
            msgs.append(HumanMessage(content=(
                f"[Tool assistant result]\n{result}\n\n"
                "Now COMPLETE YOUR ORIGINAL TASK using this result — as a "
                "normal reply. Do NOT delegate again unless the task truly "
                "needs a different capability; do not invent extra steps "
                "nobody asked for.")))
        return _DELEGATE_BLOCK_RE.sub("", text).strip()

    # How to read an execution tool's result. A verifier agent's own prose
    # cannot be trusted about these — run 61's Verifier reported "the smoke
    # test passed" while its last run_python result was exit code 1.
    _EXEC_PASS = {
        "run_python": lambda r: r.startswith("exit code: 0"),
        "arduino_compile": lambda r: r.startswith("COMPILE SUCCESS"),
        "check_stl": lambda r: "STL OK" in r,
    }

    def _tool_loop(self, agent: dict, llm, tool_map: dict, msgs: list,
                   emit_tokens: bool = True) -> str:
        # Small models fall into calling the same tool with the same arguments
        # over and over — re-running a failing test without ever fixing it, and
        # burning the whole round budget. Nothing in the transcript tells them
        # they are repeating themselves, so we do.
        seen_calls = {}
        last_exec = None  # (tool_name, passed) of the newest execution-tool result
        for _round in range(MAX_TOOL_ROUNDS + 1):
            self._check_cancel()
            full = None
            for chunk in llm.stream(msgs):
                self._check_cancel()
                full = chunk if full is None else full + chunk
                if chunk.content and emit_tokens:
                    text = chunk.content if isinstance(chunk.content, str) else str(chunk.content)
                    self.emit("token", agent=agent["name"], content=text)
            if full is None:
                return ""
            content = full.content if isinstance(full.content, str) else str(full.content)
            calls = getattr(full, "tool_calls", []) or []
            if not calls and tool_map:
                calls = salvage_tool_calls(content, tool_map)
                if calls:
                    self.emit("decision", agent=agent["name"],
                              content=f"{agent['model']} printed its tool call as text "
                                      "instead of calling it — recovered "
                                      f"{', '.join(c['name'] for c in calls)}.")
            response = AIMessage(content=content, tool_calls=calls)
            if not calls or _round == MAX_TOOL_ROUNDS:
                final = _strip_reasoning(response.content)
                if last_exec and not last_exec[1]:
                    # The agent may claim anything; the tool results are the
                    # record. Stamp the truth on the report so downstream agents
                    # and the user never act on a fabricated pass.
                    final += (f"\n\n---\n⚠ **[Automatic verification check] NOT "
                              f"VERIFIED** — the last `{last_exec[0]}` result in "
                              "this turn FAILED. Any claim of success above is "
                              "wrong; the work needs another pass.")
                return final
            msgs.append(response)
            for call in calls:
                name, args = call.get("name"), call.get("args") or {}
                self.emit("tool_call", agent=agent["name"],
                          content=f"{name}({json.dumps(args, ensure_ascii=False)[:300]})")
                sig = f"{name}:{json.dumps(args, sort_keys=True, ensure_ascii=False)}"
                seen_calls[sig] = seen_calls.get(sig, 0) + 1
                fn = tool_map.get(name)

                if seen_calls[sig] > 2 and name not in ("write_file", "edit_file",
                                                        "read_file", "list_files"):
                    # Enforced, not advised: a 7B told "stop repeating" repeats
                    # anyway (run 60 re-ran the same failing test 11 times). The
                    # third identical execution is refused until an edit changes
                    # the workspace, which resets the counter below.
                    result = (
                        f"[Loop guard] REFUSED — this is the {seen_calls[sig]}th "
                        f"identical {name} call and nothing in the workspace has "
                        "changed, so the result would be identical too. Either fix "
                        "the code first (read_file the failing file, then edit_file "
                        "the specific line the last error names), or stop and report "
                        "the last error as your final answer.")
                else:
                    try:
                        result = fn.invoke(args) if fn else f"Unknown tool {name}"
                    except Exception as e:  # noqa: BLE001
                        result = f"Tool error: {e}"
                    if name in self._EXEC_PASS:
                        last_exec = (name, self._EXEC_PASS[name](str(result)))
                    if name in ("write_file", "edit_file") and \
                            not str(result).startswith("Error"):
                        # The workspace changed — stale repeat counts no longer apply.
                        seen_calls.clear()
                        seen_calls[sig] = 1
                    elif seen_calls[sig] > 1:
                        result = (
                            f"{result}\n\n[Loop guard] Same call, same result, "
                            f"{seen_calls[sig]} times now. Fix the code before running "
                            "again — the next identical call will be refused.")

                self.emit("tool_result", agent=agent["name"], content=str(result)[:1000])
                msgs.append(ToolMessage(content=str(result), tool_call_id=call.get("id", name)))
        return ""

    # ---------------- node builders ----------------

    def _agent_system_prompt(self, agent: dict) -> str:
        base = agent.get("system_prompt", "").strip() or "You are a helpful assistant."
        for sname in agent.get("skills") or []:
            skill = self.skill_map.get(sname)
            if skill and skill.get("instructions"):
                base += f"\n\n## Skill: {skill['name']}\n{skill['instructions']}"
        rules = (
            "\n\nRules: Do the work directly and completely. Never ask the user "
            "questions. Produce clean, final, well-formatted Markdown output. "
            "Do not include meta commentary about being an AI."
        )
        # An agent that can EXECUTE (run code, compile, validate) must not also be
        # told to deliver files as `File:` text blocks. Offered both, a small model
        # takes the text route — so a verifier "fixes" a file by printing it, never
        # runs anything, and reports success having executed nothing. Builders keep
        # the convention: it is their delivery path and a safety net when they fail
        # to call write_file.
        can_execute = any(t in (agent.get("tools") or [])
                          for t in ("run_python", "arduino_compile", "check_stl"))
        if can_execute:
            rules += (
                "\nYou have tools that actually run things. Files change ONLY through "
                "write_file / edit_file, and correctness is established ONLY by running "
                "your tools. Do NOT print a file as a `File:` block or a code fence and "
                "call it delivered — text in your reply changes nothing on disk and "
                "verifies nothing. Every claim you make about whether something works "
                "must be backed by a tool result in this conversation."
            )
        else:
            rules += (
                "\nWhen your deliverable includes files (code, configs, docs), output "
                "EACH complete file as a fenced code block immediately preceded by a "
                "line of the form `File: relative/path.ext` — those files are saved "
                "to the run workspace automatically, so never abbreviate their "
                "contents or use placeholders."
            )
        return base + rules

    def _worker_node(self, agent: dict):
        name = agent["name"]

        def node(state: TeamState):
            self._check_cancel()
            self.emit("agent_start", agent=name,
                      meta={"role": agent.get("role", ""), "model": agent["model"],
                            "provider": agent.get("provider", "ollama")})
            user = (
                f"## Task\n{state['task']}\n\n"
                f"## Work so far from your teammates\n{_history_block(state.get('history', []))}"
            )
            if state.get("feedback"):
                user += (
                    f"\n\n## Reviewer feedback on the previous attempt (revision "
                    f"{state.get('revision', 0)})\nYou MUST address every point:\n"
                    f"{state['feedback']}"
                )
            if state.get("instruction"):
                user += f"\n\n## Your specific assignment right now\n{state['instruction']}"
            user += "\n\nNow produce your contribution."
            content = self._stream_call(agent, [
                SystemMessage(content=self._agent_system_prompt(agent)),
                HumanMessage(content=user),
            ])
            self.emit("agent_end", agent=name, content=content)
            # Materialize any files the agent declared (File: path + fence).
            for rel in extract_files(content, self.workspace):
                self.emit("artifact", agent=name, content=rel)
            return {"history": [{"agent": name, "content": content, "ts": time.time()}]}

        return node

    # ---------------- pipeline topology ----------------

    def _build_pipeline(self):
        agents = self.team["agents"]
        quality_loop = bool(self.settings.get("quality_loop")) and len(agents) >= 2
        max_rev = int(self.settings.get("max_revisions", 2))
        g = StateGraph(TeamState)

        workers = agents[:-1] if quality_loop else agents
        reviewer = agents[-1] if quality_loop else None

        for a in workers:
            g.add_node(a["name"], self._worker_node(a))
        g.add_edge(START, workers[0]["name"])
        for prev, nxt in zip(workers, workers[1:]):
            g.add_edge(prev["name"], nxt["name"])

        if not quality_loop:
            def finalize(state: TeamState):
                hist = state.get("history", [])
                return {"final": hist[-1]["content"] if hist else ""}
            g.add_node("_finalize", finalize)
            g.add_edge(workers[-1]["name"], "_finalize")
            g.add_edge("_finalize", END)
            return g.compile()

        rev_name = reviewer["name"]

        def review_node(state: TeamState):
            self._check_cancel()
            self.emit("agent_start", agent=rev_name,
                      meta={"role": reviewer.get("role", "reviewer"),
                            "model": reviewer["model"],
                            "provider": reviewer.get("provider", "ollama")})
            hist = state.get("history", [])
            sys = self._agent_system_prompt(reviewer) + (
                "\n\nYou are the final quality gate. Review the work below against "
                "the task. Reply starting with exactly one word on the first line: "
                "APPROVED if the work fully satisfies the task, or REVISE if not. "
                "If REVISE, follow with a short numbered list of concrete fixes."
            )
            user = (f"## Task\n{state['task']}\n\n## Work to review\n"
                    f"{_history_block(hist)}\n\nVerdict:")
            content = self._stream_call(reviewer, [
                SystemMessage(content=sys), HumanMessage(content=user)])
            approved = content.strip().upper().startswith("APPROVED")
            verdict = "approved" if approved else "revise"
            self.emit("agent_end", agent=rev_name, content=content,
                      meta={"verdict": verdict})
            out = {"history": [{"agent": rev_name, "content": content, "ts": time.time()}]}
            if approved or state.get("revision", 0) >= max_rev:
                # final = last worker output before the review
                worker_outs = [h for h in hist if h["agent"] != rev_name]
                out["final"] = worker_outs[-1]["content"] if worker_outs else ""
                out["next_agent"] = "END"
                if not approved:
                    self.emit("decision", agent=rev_name,
                              content=f"Max revisions ({max_rev}) reached; shipping best attempt.")
            else:
                out["feedback"] = content
                out["revision"] = state.get("revision", 0) + 1
                out["next_agent"] = workers[0]["name"]
                self.emit("decision", agent=rev_name,
                          content=f"Revision {out['revision']} requested → {workers[0]['name']}")
            return out

        g.add_node(rev_name, review_node)
        g.add_edge(workers[-1]["name"], rev_name)
        g.add_conditional_edges(
            rev_name,
            lambda s: s.get("next_agent", "END"),
            {workers[0]["name"]: workers[0]["name"], "END": END},
        )
        return g.compile()

    # ---------------- supervisor topology ----------------

    def _build_supervisor(self):
        agents = self.team["agents"]
        sup = agents[0]
        workers = agents[1:]
        worker_names = [w["name"] for w in workers]
        max_steps = int(self.settings.get("max_steps", 8))
        g = StateGraph(TeamState)

        def parse_route(text: str) -> tuple:
            """Extract (next, instruction) defensively from model output."""
            m = re.search(r"\{.*\}", text, re.DOTALL)
            if m:
                try:
                    data = json.loads(m.group(0))
                    nxt = str(data.get("next", "")).strip()
                    for w in worker_names:
                        if w.lower() == nxt.lower():
                            return w, str(data.get("instruction", ""))
                    if nxt.upper() == "FINISH":
                        return "FINISH", ""
                except (json.JSONDecodeError, AttributeError, TypeError):
                    pass
            if re.search(r"\bFINISH\b", text, re.IGNORECASE):
                return "FINISH", ""
            for w in worker_names:  # last resort: first worker named in text
                if re.search(re.escape(w), text, re.IGNORECASE):
                    return w, text[:500]
            return "FINISH", ""

        def supervisor_node(state: TeamState):
            self._check_cancel()
            steps = state.get("supervisor_steps", 0)
            hist = state.get("history", [])
            if steps >= max_steps:
                self.emit("decision", agent=sup["name"],
                          content=f"Max steps ({max_steps}) reached; finishing.")
                return {"next_agent": "FINISH", "supervisor_steps": steps + 1}
            self.emit("agent_start", agent=sup["name"],
                      meta={"role": "supervisor", "model": sup["model"],
                            "provider": sup.get("provider", "ollama")})
            roster = "\n".join(
                f"- {w['name']}: {w.get('role', '')}. {w.get('system_prompt', '')[:150]}"
                for w in workers)
            sys = self._agent_system_prompt(sup) + (
                "\n\nYou are the team supervisor. You delegate work; you do not do "
                "the work yourself.\nYour team:\n" + roster +
                "\n\nDecide the single next step. Respond ONLY with JSON, no other "
                'text: {"next": "<exact worker name or FINISH>", "instruction": '
                '"<clear, specific instruction for that worker>"}\n'
                "Choose FINISH only when the collected work fully covers the task."
            )
            user = (f"## Task\n{state['task']}\n\n## Work collected so far\n"
                    f"{_history_block(hist)}\n\nJSON decision:")
            content = self._stream_call(sup, [
                SystemMessage(content=sys), HumanMessage(content=user)])
            nxt, instruction = parse_route(content)
            self.emit("agent_end", agent=sup["name"], content=content,
                      meta={"decision": nxt})
            self.emit("decision", agent=sup["name"],
                      content=(f"→ {nxt}: {instruction[:200]}" if nxt != "FINISH"
                               else "→ FINISH (synthesizing final answer)"))
            return {"next_agent": nxt, "instruction": instruction,
                    "supervisor_steps": steps + 1}

        def synthesize_node(state: TeamState):
            self._check_cancel()
            self.emit("agent_start", agent=sup["name"],
                      meta={"role": "synthesis", "model": sup["model"],
                            "provider": sup.get("provider", "ollama")})
            sys = self._agent_system_prompt(sup) + (
                "\n\nWrite the final deliverable for the task by synthesizing your "
                "team's work into one polished, complete answer. Output only the "
                "deliverable itself."
            )
            user = (f"## Task\n{state['task']}\n\n## Team work\n"
                    f"{_history_block(state.get('history', []))}\n\nFinal deliverable:")
            content = self._stream_call(sup, [
                SystemMessage(content=sys), HumanMessage(content=user)])
            self.emit("agent_end", agent=sup["name"], content=content)
            return {"final": content}

        g.add_node("_supervisor", supervisor_node)
        g.add_node("_synthesize", synthesize_node)
        for w in workers:
            g.add_node(w["name"], self._worker_node(w))
            g.add_edge(w["name"], "_supervisor")
        g.add_edge(START, "_supervisor")
        g.add_conditional_edges(
            "_supervisor",
            lambda s: s.get("next_agent") or "FINISH",
            {**{n: n for n in worker_names}, "FINISH": "_synthesize"},
        )
        g.add_edge("_synthesize", END)
        return g.compile()

    # ---------------- custom graph topology ----------------

    def _build_graph(self):
        """Build an arbitrary DAG from team['graph'] = {nodes, edges}.

        Nodes: [{id, agent}] where agent references a team agent by name.
        Edges: [{source, target}] using node ids plus the virtual ids
        'start' and 'end'. Fan-out runs branches in parallel supersteps
        (actual LLM concurrency is gated by the parallel semaphore); fan-in
        waits for all incoming branches.
        """
        spec = self.team.get("graph") or {}
        nodes = {n["id"]: n for n in spec.get("nodes", [])}
        edges = spec.get("edges", [])

        g = StateGraph(TeamState)
        for nid, n in nodes.items():
            agent = self.agents[n["agent"]]
            g.add_node(nid, self._worker_node(agent))

        # Group incoming edges per target: a list source means "wait for all".
        incoming = {}
        for e in edges:
            incoming.setdefault(e["target"], []).append(e["source"])

        end_sources = []
        for target, sources in incoming.items():
            srcs = [START if s == "start" else s for s in sources]
            if target == "end":
                end_sources = srcs
                continue
            g.add_edge(srcs if len(srcs) > 1 else srcs[0], target)

        def finalize(state: TeamState):
            hist = sorted(state.get("history", []), key=lambda x: x.get("ts", 0))
            if not hist:
                return {"final": ""}
            # Final = latest output of each node that feeds 'end'.
            end_agents = [nodes[s]["agent"] for s in end_sources if s in nodes]
            tail = []
            for a in end_agents:
                matches = [h for h in hist if h["agent"] == a]
                if matches:
                    tail.append(matches[-1])
            tail = tail or hist[-1:]
            if len(tail) == 1:
                return {"final": tail[-1]["content"]}
            return {"final": "\n\n".join(
                f"## {h['agent']}\n\n{h['content']}" for h in tail)}

        g.add_node("_finalize", finalize)
        if end_sources:
            g.add_edge(end_sources if len(end_sources) > 1 else end_sources[0],
                       "_finalize")
        g.add_edge("_finalize", END)
        return g.compile()

    def _build_single(self):
        agent = self.team["agents"][0]
        g = StateGraph(TeamState)

        def node(state: TeamState):
            result = self._worker_node(agent)(state)
            result["final"] = result["history"][-1]["content"]
            return result

        g.add_node(agent["name"], node)
        g.add_edge(START, agent["name"])
        g.add_edge(agent["name"], END)
        return g.compile()

    # ---------------- run ----------------

    def run(self) -> str:
        topology = self.team.get("topology", "pipeline")
        if not self.team.get("agents"):
            raise ValueError("Team has no agents")
        if topology == "graph":
            graph = self._build_graph()
        elif topology == "single" or len(self.team["agents"]) == 1:
            graph = self._build_single()
        elif topology == "supervisor":
            graph = self._build_supervisor()
        else:
            graph = self._build_pipeline()

        recursion = 10 + 6 * (int(self.settings.get("max_steps", 8)) +
                              int(self.settings.get("max_revisions", 2))) \
                    * max(1, len(self.team["agents"]))
        final_state = graph.invoke(
            {"task": self.task, "history": [], "revision": 0, "supervisor_steps": 0},
            config={"recursion_limit": recursion},
        )
        final = final_state.get("final") or ""
        if not final and final_state.get("history"):
            final = final_state["history"][-1]["content"]
        return final
