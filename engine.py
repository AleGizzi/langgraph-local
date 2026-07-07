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
import re
import threading
import time
from typing import Annotated, Optional

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

from providers import LLM_IDLE_TIMEOUT, make_llm
from tools import resolve_tools

MAX_TOOL_ROUNDS = 5


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
    """Remove <think>...</think> blocks emitted by reasoning models (DeepSeek-R1)."""
    return re.sub(r"<think>.*?</think>\s*", "", text, flags=re.DOTALL).strip()


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
    if tool_list:
        llm = llm.bind_tools(tool_list)

    msgs = [SystemMessage(content=system)]
    for m in messages:
        cls = HumanMessage if m.get("role") == "user" else AIM
        msgs.append(cls(content=str(m.get("content", ""))))

    final = ""
    for _round in range(MAX_TOOL_ROUNDS + 1):
        full = None
        for chunk in llm.stream(msgs):
            full = chunk if full is None else full + chunk
            if chunk.content:
                text = chunk.content if isinstance(chunk.content, str) else str(chunk.content)
                yield {"type": "token", "content": text}
        if full is None:
            break
        response = AIMessage(
            content=full.content if isinstance(full.content, str) else str(full.content),
            tool_calls=getattr(full, "tool_calls", []) or [],
        )
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
        if tool_list:
            llm = llm.bind_tools(tool_list)

        with self.llm_gate:
            last_err = None
            for attempt in (1, 2):
                try:
                    return self._tool_loop(agent, llm, tool_map, list(messages))
                except Exception as e:  # noqa: BLE001 - translate stalls to a clear error
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

    def _tool_loop(self, agent: dict, llm, tool_map: dict, msgs: list) -> str:
        for _round in range(MAX_TOOL_ROUNDS + 1):
            self._check_cancel()
            full = None
            for chunk in llm.stream(msgs):
                self._check_cancel()
                full = chunk if full is None else full + chunk
                if chunk.content:
                    text = chunk.content if isinstance(chunk.content, str) else str(chunk.content)
                    self.emit("token", agent=agent["name"], content=text)
            if full is None:
                return ""
            response = AIMessage(
                content=full.content if isinstance(full.content, str) else str(full.content),
                tool_calls=getattr(full, "tool_calls", []) or [],
            )
            calls = response.tool_calls
            if not calls or _round == MAX_TOOL_ROUNDS:
                return _strip_reasoning(response.content)
            msgs.append(response)
            for call in calls:
                name, args = call.get("name"), call.get("args") or {}
                self.emit("tool_call", agent=agent["name"],
                          content=f"{name}({json.dumps(args, ensure_ascii=False)[:300]})")
                fn = tool_map.get(name)
                try:
                    result = fn.invoke(args) if fn else f"Unknown tool {name}"
                except Exception as e:  # noqa: BLE001
                    result = f"Tool error: {e}"
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
