"""Local Agents Studio — a Dify-style UI for LangGraph agent teams running on
local models (Ollama / LM Studio). Single-user, fully local.
"""
import json
import os
import queue
import re
import time

import requests
from flask import Flask, Response, abort, jsonify, request, send_from_directory

import providers
import seeds
import storage
import sysinfo
from runmanager import WORKSPACES, manager
import tools as tools_mod
from tools import CUSTOM_TOOLS_DIR

app = Flask(__name__, static_folder="static", static_url_path="/static")
app.config["JSON_AS_ASCII"] = False

storage.init_db()

# Startup side effects (marking orphaned runs, seeding, queue workers) must NOT
# fire when this module is merely imported by tooling — an `import app` syntax
# check once marked a live run "Interrupted by server restart" because these
# ran against the real database. Set AGENTS_SKIP_STARTUP=1 for such imports.
if not os.environ.get("AGENTS_SKIP_STARTUP"):
    storage.mark_stale_runs()
    seeds.seed_if_empty()

    # Kick a background catalog refresh at startup if the cache is stale
    # (get_catalog handles the staleness check; no-op when fresh or offline).
    import catalog as _catalog  # noqa: E402
    _catalog.get_catalog(auto_refresh=True)

    # Recover image jobs a restart interrupted (resumes polling in-flight
    # Fooocus jobs so their images aren't lost) and start the queue worker.
    import imgqueue as _imgqueue  # noqa: E402
    _imgqueue.start()

# Used by the SPA to detect that the server (and likely the bundle) changed
# under an open tab, and offer a reload instead of running stale code.
# (time imported at top)
SERVER_STARTED = time.time()

VALID_TOPOLOGIES = {"single", "pipeline", "supervisor", "graph"}


def _validate_graph(agents: list, graph: dict) -> dict:
    """Validate a custom pipeline: known agents, valid edges, acyclic,
    reachable from start, and at least one node feeding end."""
    if not isinstance(graph, dict):
        abort(400, "graph topology requires a graph definition")
    nodes = graph.get("nodes") or []
    edges = graph.get("edges") or []
    agent_names = {a["name"] for a in agents}
    ids = set()
    for n in nodes:
        nid = str(n.get("id") or "").strip()
        if not nid or nid in ("start", "end"):
            abort(400, "every graph node needs a unique id (not 'start'/'end')")
        if nid in ids:
            abort(400, f"duplicate node id: {nid}")
        ids.add(nid)
        if n.get("agent") not in agent_names:
            abort(400, f"node '{nid}' references unknown agent '{n.get('agent')}'")
    if not ids:
        abort(400, "graph needs at least one node")
    clean_edges = []
    for e in edges:
        s, t = str(e.get("source", "")), str(e.get("target", ""))
        if s not in ids | {"start"} or t not in ids | {"end"}:
            abort(400, f"edge {s}->{t} references unknown node")
        if (s, t) not in {(x["source"], x["target"]) for x in clean_edges}:
            clean_edges.append({"source": s, "target": t})
    # reachability + cycle check (Kahn) over real nodes
    starts = {e["target"] for e in clean_edges if e["source"] == "start"}
    if not starts:
        abort(400, "graph needs at least one edge from start")
    if not any(e["target"] == "end" for e in clean_edges):
        abort(400, "graph needs at least one edge to end")
    indeg = {i: 0 for i in ids}
    adj = {i: [] for i in ids}
    for e in clean_edges:
        if e["source"] in ids and e["target"] in ids:
            indeg[e["target"]] += 1
            adj[e["source"]].append(e["target"])
    queue = [i for i in ids if indeg[i] == 0]
    seen = 0
    while queue:
        cur = queue.pop()
        seen += 1
        for nxt in adj[cur]:
            indeg[nxt] -= 1
            if indeg[nxt] == 0:
                queue.append(nxt)
    if seen != len(ids):
        abort(400, "graph contains a cycle — pipelines must be acyclic")
    # every node reachable from start
    reach = set()
    frontier = list(starts)
    while frontier:
        cur = frontier.pop()
        if cur in reach or cur not in ids:
            continue
        reach.add(cur)
        frontier.extend(adj[cur])
    unreachable = ids - reach
    if unreachable:
        abort(400, f"nodes not reachable from start: {', '.join(sorted(unreachable))}")
    positions = graph.get("positions") or {}
    return {"nodes": [{"id": n["id"], "agent": n["agent"]} for n in nodes],
            "edges": clean_edges,
            "positions": {k: v for k, v in positions.items()
                          if isinstance(v, dict) and k in ids | {"start", "end"}}}


def _validate_team(data: dict):
    if not isinstance(data, dict):
        abort(400, "invalid body")
    name = (data.get("name") or "").strip()
    if not name:
        abort(400, "team name is required")
    topology = data.get("topology", "pipeline")
    if topology not in VALID_TOPOLOGIES:
        abort(400, f"topology must be one of {sorted(VALID_TOPOLOGIES)}")
    agents = data.get("agents") or []
    if not agents:
        abort(400, "at least one agent is required")
    if topology == "supervisor" and len(agents) < 2:
        abort(400, "supervisor topology needs a supervisor plus at least one worker")
    seen = set()
    for a in agents:
        aname = (a.get("name") or "").strip()
        if not aname:
            abort(400, "every agent needs a name")
        if aname.lower() in seen:
            abort(400, f"duplicate agent name: {aname}")
        seen.add(aname.lower())
        a["name"] = aname
        if not a.get("model"):
            abort(400, f"agent '{aname}' needs a model")
        if a.get("provider") not in ("ollama", "lmstudio"):
            a["provider"] = "ollama"
        try:
            a["temperature"] = min(2.0, max(0.0, float(a.get("temperature", 0.7))))
        except (TypeError, ValueError):
            a["temperature"] = 0.7
        a["params"] = providers.clean_params(a.get("params"))
        valid_tools = tools_mod.valid_tool_names()
        valid_skills = {s["name"] for s in storage.list_skills()}
        a["tools"] = [t for t in (a.get("tools") or []) if t in valid_tools]
        a["skills"] = [s for s in (a.get("skills") or []) if s in valid_skills]
    graph = None
    if topology == "graph":
        graph = _validate_graph(agents, data.get("graph"))
    settings = data.get("settings") or {}
    clean = {}
    if settings.get("quality_loop"):
        clean["quality_loop"] = True
    if settings.get("parallel"):
        clean["parallel"] = True
    try:
        clean["max_revisions"] = min(5, max(0, int(settings.get("max_revisions", 2))))
    except (TypeError, ValueError):
        clean["max_revisions"] = 2
    try:
        clean["max_steps"] = min(20, max(1, int(settings.get("max_steps", 8))))
    except (TypeError, ValueError):
        clean["max_steps"] = 8
    out = {"name": name, "icon": (data.get("icon") or "🤖")[:8],
           "description": data.get("description", ""), "topology": topology,
           "agents": agents, "settings": clean}
    if graph is not None:
        out["graph"] = graph
    return out


@app.get("/")
def index():
    return send_from_directory("static/dist", "index.html")


@app.get("/api/health")
def health():
    return jsonify({"ok": True, "providers": providers.provider_status(),
                    "server_started": SERVER_STARTED})


@app.get("/api/models")
def models():
    return jsonify(providers.list_models())


@app.get("/api/models/card")
def model_card():
    """'What is this model best used for?' — deterministic aptitude card.

    Facts come from the live catalog (capability tags, params, size) and the
    hardware assessment (speed estimate, RAM verdict); scoring is in
    modelinfo.py. Query: ?name=<model>&provider=<ollama|lmstudio>
    """
    import catalog as catalog_mod
    import modelinfo
    name = (request.args.get("name") or "").strip()
    if not name:
        abort(400, "name is required")
    provider = request.args.get("provider") or "ollama"

    facts = {}
    base = name.split(":")[0].lower()
    for m in (catalog_mod.load_cache() or {}).get("models", []):
        if m.get("name") == name:
            facts = m
            break
        if not facts and (m.get("base") or "").lower() == base:
            facts = m  # family fallback: capabilities are family-wide
    hw = sysinfo.hardware()
    assessed = next((i for i in sysinfo.assess()["installed"] if i["name"] == name), {})

    return jsonify(modelinfo.card(
        name, provider=provider,
        capabilities=facts.get("capabilities"),
        params_b=assessed.get("params_b") or facts.get("params_b"),
        size_gb=assessed.get("size_gb") or facts.get("size_gb"),
        quant=assessed.get("quant"),
        est_tok_s=assessed.get("est_tok_s")
        or sysinfo._speed_estimate(facts.get("params_b"), hw["gpu"]),
        verdict=assessed.get("verdict") or facts.get("verdict"),
        verdict_label=assessed.get("verdict_label") or facts.get("verdict_label"),
        installed=bool(assessed),
        description=facts.get("description", "")))


@app.get("/api/help/agent")
def help_agent():
    """Config for the in-app help assistant (posted back to /api/chat)."""
    import help as help_mod
    cfg = help_mod.agent_config(providers.list_models())
    return jsonify({"agent": cfg, "available": bool(cfg["model"])})


@app.get("/api/tools")
def tools_catalog():
    return jsonify(tools_mod.full_catalog())


def _safe_tool_file(filename: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_\-]+\.py", filename):
        abort(400, "tool file name must be like my_tool.py")
    return os.path.join(CUSTOM_TOOLS_DIR, filename)


@app.get("/api/tools/files/<filename>")
def tool_file_get(filename):
    path = _safe_tool_file(filename)
    if not os.path.isfile(path):
        abort(404)
    with open(path, encoding="utf-8") as f:
        return jsonify({"file": filename, "code": f.read()})


@app.put("/api/tools/files/<filename>")
def tool_file_put(filename):
    path = _safe_tool_file(filename)
    code = (request.get_json(force=True) or {}).get("code", "")
    if not code.strip():
        abort(400, "code is required")
    os.makedirs(CUSTOM_TOOLS_DIR, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(code)
    # Reload immediately so the response reports syntax/import errors.
    catalog = tools_mod.full_catalog()
    entry = next((x for x in catalog["files"] if x["file"] == filename), None)
    return jsonify({"file": filename, "loaded": entry["tools"] if entry else [],
                    "error": entry["error"] if entry else "file not seen by loader"})


@app.delete("/api/tools/files/<filename>")
def tool_file_delete(filename):
    path = _safe_tool_file(filename)
    if os.path.isfile(path):
        os.remove(path)
    return jsonify({"ok": True})


# ---------------- image generation (Fooocus) ----------------

@app.get("/api/imagegen/status")
def imagegen_status():
    import imagegen
    st = imagegen.backend_status()
    st["install"] = imagegen.install_status()
    return jsonify(st)


@app.post("/api/imagegen/install")
def imagegen_install():
    import imagegen
    return jsonify(imagegen.install_backend())


@app.post("/api/imagegen/start")
def imagegen_start():
    import imagegen
    return jsonify(imagegen.start_server())


@app.post("/api/imagegen/stop")
def imagegen_stop():
    import imagegen
    return jsonify(imagegen.stop_server())


@app.post("/api/imagegen/generate")
def imagegen_generate():
    import imagegen
    body = request.get_json(force=True) or {}
    prompt = (body.get("prompt") or "").strip()
    if not prompt:
        abort(400, "prompt is required")
    return jsonify(imagegen.generate(
        prompt, negative=body.get("negative", ""),
        steps=body.get("steps"), aspect=body.get("aspect") or "1152*896",
        performance=body.get("performance"), loras=body.get("loras")))


@app.get("/api/imagegen/modes")
def imagegen_modes():
    """The ways an existing image can be modified (for the UI's mode picker)."""
    import imagegen
    return jsonify({"modes": [
        {"key": k, "label": v["label"],
         "description": v.get("description", ""),
         "needs_mask": bool(v.get("needs_mask")),
         "needs_prompt": ("cn_type" in v or "Vary" in v.get("uov_method", "")
                          or v.get("needs_mask", False))}
        for k, v in imagegen.MODIFY_MODES.items()]})


@app.post("/api/imagegen/modify")
def imagegen_modify():
    """Modify an existing image (img2img): vary, upscale, restyle, outpaint."""
    import imagegen
    body = request.get_json(force=True) or {}
    source = body.get("image") or body.get("source") or ""
    if not source:
        abort(400, "image is required (data URL, base64, or a gallery filename)")
    return jsonify(imagegen.modify(
        source, mode=body.get("mode") or "vary_strong",
        prompt=body.get("prompt", ""), negative=body.get("negative", ""),
        performance=body.get("performance"), loras=body.get("loras"),
        weight=body.get("weight", 0.6), stop=body.get("stop", 0.5),
        outpaint=body.get("outpaint"), mask=body.get("mask"),
        aspect=body.get("aspect") or "1152*896"))


@app.get("/api/imagegen/ui")
def imagegen_ui_status():
    """Fooocus's own web UI (optional standalone install): installed/running."""
    import imagegen
    return jsonify(imagegen.ui_status())


@app.post("/api/imagegen/ui/start")
def imagegen_ui_start():
    """Start Fooocus's own UI (stops the API server first — one GPU)."""
    import imagegen
    return jsonify(imagegen.start_ui_server())


@app.post("/api/imagegen/ui/stop")
def imagegen_ui_stop():
    import imagegen
    return jsonify(imagegen.stop_ui_server())


@app.post("/api/imagegen/prompt-assist")
def imagegen_prompt_assist():
    """AI help for writing the image prompt (knows your LoRAs + past prompts)."""
    import imgprompt
    body = request.get_json(force=True) or {}
    return jsonify(imgprompt.assist(
        body.get("request", ""),
        provider=body.get("provider"), model=body.get("model"),
        current_prompt=body.get("current_prompt", ""),
        feedback=body.get("feedback", "")))


# ---------------- image job queue ----------------

@app.get("/api/imagegen/queue")
def imagegen_queue_get():
    import imgqueue
    return jsonify(imgqueue.status())


@app.post("/api/imagegen/queue")
def imagegen_queue_add():
    """Queue one or more image jobs (they run one at a time, in order)."""
    import imgqueue
    body = request.get_json(force=True) or {}
    kind = body.get("kind") or "generate"
    params = body.get("params") or {}
    if kind == "generate" and not (params.get("prompt") or "").strip():
        abort(400, "params.prompt is required")
    if kind == "modify" and not (params.get("image") or params.get("source")):
        abort(400, "params.image is required")
    res = imgqueue.add(kind, params, count=body.get("count", 1))
    if not res.get("ok"):
        abort(400, res.get("error"))
    return jsonify(res)


@app.post("/api/imagegen/queue/<job_id>/cancel")
def imagegen_queue_cancel(job_id):
    import imgqueue
    return jsonify(imgqueue.cancel(job_id))


@app.post("/api/imagegen/queue/clear")
def imagegen_queue_clear():
    import imgqueue
    return jsonify(imgqueue.clear_finished())


@app.get("/api/imagegen/gallery")
def imagegen_gallery():
    import imagegen
    names = imagegen.list_images()
    return jsonify({"images": names,
                    "meta": {n: imagegen.image_meta(n) for n in names}})


# ---------------- LoRAs (Fooocus/SDXL style LoRAs from Civitai) ----------------

@app.get("/api/loras")
def loras_index():
    import loras
    return jsonify({"local": loras.list_local(), "downloads": loras.download_status()})


@app.get("/api/loras/search")
def loras_search():
    import loras
    q = (request.args.get("q") or "").strip()
    if not q:
        abort(400, "q is required")
    base = request.args.get("base") or "SDXL"
    return jsonify(loras.search(q, base_model=base))


@app.post("/api/loras/download")
def loras_download():
    import loras
    body = request.get_json(force=True) or {}
    url = (body.get("download_url") or "").strip()
    name = (body.get("file_name") or "").strip()
    if not url or not name:
        abort(400, "download_url and file_name are required")
    # Everything the search told us about this LoRA is persisted with the file,
    # so the UI can still explain it later.
    meta = {k: body.get(k) for k in
            ("name", "version_name", "description", "source_url", "base_model",
             "trigger_words", "creator", "downloads", "id", "version_id")}
    return jsonify(loras.download(url, name, meta=meta))


@app.post("/api/loras/identify")
def loras_identify():
    """Look up a local LoRA on Civitai to fill in its description/source."""
    import loras
    body = request.get_json(force=True) or {}
    name = (body.get("file_name") or "").strip()
    if not name:
        abort(400, "file_name is required")
    return jsonify(loras.identify(name))


@app.delete("/api/loras/<path:file_name>")
def loras_delete(file_name):
    import loras
    res = loras.delete(file_name)
    if not res.get("ok"):
        abort(400, res.get("error") or "could not delete")
    return jsonify(res)


@app.get("/api/imagegen/images/<path:filename>")
def imagegen_image(filename):
    import imagegen
    return send_from_directory(os.path.realpath(imagegen.IMAGES_DIR), filename)


# ---------------- knowledge base ----------------

@app.get("/api/knowledge")
def knowledge_list():
    import knowledge
    q = request.args.get("q", "").strip()
    if q:
        return jsonify({"stats": knowledge.stats(), "results": knowledge.search(q, limit=50)})
    return jsonify({"stats": knowledge.stats(), "notes": knowledge.list_notes()})


@app.get("/api/knowledge/note")
def knowledge_note():
    import knowledge
    rel = request.args.get("path", "")
    try:
        return jsonify({"path": rel, "content": knowledge.read_note(rel)})
    except (OSError, ValueError):
        abort(404)


@app.post("/api/knowledge/note")
def knowledge_note_create():
    import knowledge
    body = request.get_json(force=True) or {}
    title = (body.get("title") or "").strip()
    content = body.get("content") or ""
    if not title or not content.strip():
        abort(400, "title and content are required")
    folder = re.sub(r"[^\w/ -]", "", (body.get("folder") or "notes")).strip("/ ") or "notes"
    rel = knowledge.write_note(title, content, tags=["manual"],
                               meta_extra={"source": "manual"}, subdir=folder)
    return jsonify({"path": rel})


@app.delete("/api/knowledge/note")
def knowledge_note_delete():
    import knowledge
    r = knowledge.delete_note(request.args.get("path", ""))
    if not r["ok"]:
        abort(404, r["error"])
    return jsonify(r)


@app.get("/api/knowledge/folders")
def knowledge_folders():
    import knowledge
    return jsonify({"folders": knowledge.folders()})


@app.delete("/api/knowledge/folder")
def knowledge_folder_delete():
    """Delete a whole sub-vault — the 'forget this topic' operation."""
    import knowledge
    r = knowledge.delete_folder(request.args.get("path", ""))
    if not r["ok"]:
        abort(400, r["error"])
    return jsonify(r)


@app.post("/api/knowledge/move")
def knowledge_note_move():
    import knowledge
    body = request.get_json(force=True) or {}
    r = knowledge.move_note(body.get("path", ""), body.get("folder", ""))
    if not r["ok"]:
        abort(400, r["error"])
    return jsonify(r)


@app.get("/api/knowledge/graph")
def knowledge_graph():
    import knowledge
    return jsonify(knowledge.graph())


# ---------------- chat ----------------

def _validate_chat(data: dict) -> dict:
    if not isinstance(data, dict):
        abort(400, "invalid body")
    msgs = [m for m in (data.get("messages") or [])
            if isinstance(m, dict) and m.get("role") in ("user", "assistant")]
    title = (data.get("title") or "").strip()
    if not title:
        first = next((m["content"] for m in msgs if m["role"] == "user"), "")
        title = (str(first)[:64] or "New chat").strip()
    return {"title": title, "agent": data.get("agent") or {},
            "messages": [{"role": m["role"], "content": str(m.get("content", ""))}
                         for m in msgs]}


@app.get("/api/chats")
def chats_list():
    return jsonify(storage.list_chats())


@app.post("/api/chats")
def chats_create():
    return jsonify(storage.create_chat(_validate_chat(request.get_json(force=True))))


@app.get("/api/chats/<int:cid>")
def chats_get(cid):
    chat_obj = storage.get_chat(cid)
    if not chat_obj:
        abort(404)
    return jsonify(chat_obj)


@app.put("/api/chats/<int:cid>")
def chats_update(cid):
    if not storage.get_chat(cid):
        abort(404)
    return jsonify(storage.update_chat(cid, _validate_chat(request.get_json(force=True))))


@app.delete("/api/chats/<int:cid>")
def chats_delete(cid):
    storage.delete_chat(cid)
    return jsonify({"ok": True})

@app.post("/api/chat")
def chat():
    import engine
    body = request.get_json(force=True) or {}
    agent = body.get("agent") or {}
    if not agent.get("model"):
        abort(400, "agent.model is required")
    if agent.get("provider") not in ("ollama", "lmstudio"):
        agent["provider"] = "ollama"
    agent["params"] = providers.clean_params(agent.get("params"))
    valid_tools = tools_mod.valid_tool_names()
    valid_skills = {s["name"] for s in storage.list_skills()}
    agent["tools"] = [t for t in (agent.get("tools") or []) if t in valid_tools]
    agent["skills"] = [s for s in (agent.get("skills") or []) if s in valid_skills]
    messages = [m for m in (body.get("messages") or [])
                if isinstance(m, dict) and m.get("role") in ("user", "assistant")]
    if not messages:
        abort(400, "messages are required")
    workspace = os.path.join(WORKSPACES, "chat")
    os.makedirs(workspace, exist_ok=True)
    skill_map = {s["name"]: s for s in storage.list_skills()}

    def generate():
        try:
            for ev in engine.chat_stream(agent, messages, workspace, skill_map):
                yield _sse(ev)
        except Exception as e:  # noqa: BLE001
            msg = f"{type(e).__name__}: {e}"
            if "does not support tools" in msg.lower():
                # The catalog thought this model could bind tools and the
                # provider disagreed — remember that, so the NEXT message goes
                # down the delegation path instead of erroring again.
                engine._mark_no_tools(agent.get("provider", "ollama"),
                                      agent.get("model", ""))
                msg += (" — this model can't call tools natively. Send your "
                        "message again: tool work will now be delegated to a "
                        "tool-capable model automatically.")
            yield _sse({"type": "error", "content": msg})

    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ---------------- wizard ----------------

@app.post("/api/wizard")
def wizard_generate():
    import wizard
    body = request.get_json(force=True) or {}
    kind = body.get("kind")
    req = (body.get("request") or "").strip()
    if kind not in ("skill", "tool", "team", "persona"):
        abort(400, "kind must be 'skill', 'tool', 'team' or 'persona'")
    if not req:
        abort(400, "describe what you need")
    provider = body.get("provider") if body.get("provider") in ("ollama", "lmstudio") else "ollama"
    model = body.get("model") or ""
    if not model:
        abort(400, "model is required")
    try:
        if kind == "skill":
            draft = wizard.draft_skill(provider, model, req,
                                       current=body.get("current"),
                                       feedback=body.get("feedback"))
        elif kind == "team":
            draft = wizard.draft_team(
                provider, model, req,
                models=providers.list_models(),
                tools=sorted(tools_mod.valid_tool_names()),
                skills=[s["name"] for s in storage.list_skills()],
                current=body.get("current"), feedback=body.get("feedback"))
        elif kind == "persona":
            draft = wizard.draft_persona(
                provider, model, req,
                models=providers.list_models(),
                tools=sorted(tools_mod.valid_tool_names()),
                skills=[s["name"] for s in storage.list_skills()],
                current=body.get("current"), feedback=body.get("feedback"))
        else:
            draft = wizard.draft_tool(provider, model, req,
                                      current_code=body.get("current_code"),
                                      feedback=body.get("feedback"))
    except Exception as e:  # noqa: BLE001 - surface LLM/provider errors cleanly
        abort(502, f"wizard generation failed: {type(e).__name__}: {e}")
    return jsonify({"kind": kind, "draft": draft})


# ---------------- skills ----------------

def _validate_skill(data: dict) -> dict:
    if not isinstance(data, dict) or not (data.get("name") or "").strip():
        abort(400, "skill name is required")
    if not (data.get("instructions") or "").strip():
        abort(400, "skill instructions are required")
    return {"name": data["name"].strip(), "icon": (data.get("icon") or "✨")[:8],
            "description": data.get("description", ""),
            "instructions": data["instructions"].strip()}


@app.get("/api/skills")
def skills_list():
    return jsonify(storage.list_skills())


@app.post("/api/skills")
def skills_create():
    return jsonify(storage.create_skill(_validate_skill(request.get_json(force=True))))


@app.put("/api/skills/<int:sid>")
def skills_update(sid):
    if not storage.get_skill(sid):
        abort(404)
    return jsonify(storage.update_skill(sid, _validate_skill(request.get_json(force=True))))


@app.delete("/api/skills/<int:sid>")
def skills_delete(sid):
    storage.delete_skill(sid)
    return jsonify({"ok": True})


@app.get("/api/system")
def system_report():
    import installer
    report = sysinfo.full_report()
    report["docker"] = installer.in_docker()
    return jsonify(report)


@app.get("/api/system/memory")
def system_memory():
    return jsonify(sysinfo.memory_report())


@app.post("/api/system/free-memory")
def system_free_memory():
    """Free RAM the app itself is holding: unload Ollama models and/or stop the
    image server. Returns before/after so the UI can show what was reclaimed."""
    import imagegen
    body = request.get_json(force=True) or {}
    before = sysinfo.memory_report()
    done = []

    if body.get("unload_models", True):
        for m in before["ollama_loaded"]:
            try:
                # keep_alive=0 tells Ollama to drop the model immediately.
                requests.post(f"{providers.OLLAMA_URL}/api/generate",
                              json={"model": m["name"], "keep_alive": 0},
                              timeout=10)
                done.append(f"unloaded {m['name']}")
            except requests.RequestException as e:
                done.append(f"could not unload {m['name']}: {e}")

    if body.get("stop_image_server", True) and before["image_server"]["running"]:
        res = imagegen.stop_server()
        done.append("stopped image server" if res.get("ok")
                    else f"image server: {res.get('error')}")

    time.sleep(1.5)  # let the kernel reclaim
    after = sysinfo.memory_report()
    return jsonify({"actions": done, "before": before, "after": after,
                    "freed_gb": round(after["available_gb"] - before["available_gb"], 1)})
    import installer
    body = request.get_json(force=True) or {}
    provider = body.get("provider")
    if provider not in ("ollama", "lmstudio"):
        abort(400, "provider must be ollama or lmstudio")
    return jsonify(installer.install_provider(provider))


# ---------------- model catalog & installer ----------------

@app.get("/api/catalog")
def catalog_get():
    import catalog
    data = catalog.get_catalog()
    hw = sysinfo.hardware()
    installed = set()
    models = providers.list_models()
    for name in models.get("ollama", []):
        installed.add(name)
        installed.add(name.split(":")[0])
    for m in data["models"]:
        if m.get("size_gb"):
            v = sysinfo._verdict(m["size_gb"], hw["ram_total_gb"], hw["gpu"])
            m["verdict"] = v
            m["verdict_label"] = sysinfo.VERDICT_LABEL[v]
            m["est_tok_s"] = sysinfo._speed_estimate(m.get("params_b"), hw["gpu"])
        else:
            m["verdict"] = "unknown"
            m["verdict_label"] = "Size unknown — open the model page on ollama.com"
            m["est_tok_s"] = None
        m["installed"] = m["name"] in installed or (
            m["name"].endswith(":latest") and m["name"][:-7] in installed)
    extra = catalog.annotate(data["models"])
    data["dream_team"] = extra["dream_team"]
    data["categories"] = catalog.CATEGORIES
    # Image generation (separate runtime, VRAM-bound) — assess and add the best
    # runnable one to the dream team under a 🎨 role.
    img = catalog.image_models(hw)
    data["image"] = img
    if img.get("best"):
        b = img["best"]
        data["dream_team"].append({
            "category": "image", "icon": "🎨", "label": "Image generation",
            "model": b["name"], "size_gb": b["disk_gb"], "verdict": b["verdict"],
            "est_tok_s": None, "installed": False, "image": True,
            "runner": b["runner"],
            "reason": (f"Best local image model for your GPU — {b['verdict_label']} "
                       f"Runs in {b['runner']}."),
        })
    runnable = [m for m in data["models"] if m.get("verdict") in ("great", "ok", "tight")]
    sweet = max((m for m in data["models"] if m.get("verdict") == "great"
                 and m.get("params_b")), key=lambda m: m["params_b"], default=None)
    data["summary"] = {"total": len(data["models"]), "runnable": len(runnable),
                       "sweet_spot": sweet["name"] if sweet else None}
    return jsonify(data)


@app.post("/api/catalog/refresh")
def catalog_refresh():
    import catalog
    started = catalog.refresh(blocking=False)
    return jsonify({"started": started})


@app.post("/api/install")
def install_start():
    import installer
    body = request.get_json(force=True) or {}
    provider = body.get("provider")
    model = (body.get("model") or "").strip()
    if provider not in ("ollama", "lmstudio") or not model:
        abort(400, "provider (ollama|lmstudio) and model are required")
    return jsonify(installer.start(provider, model))


@app.get("/api/install/status")
def install_status():
    import installer
    return jsonify(installer.status_all())


@app.post("/api/install/cancel")
def install_cancel():
    import installer
    body = request.get_json(force=True) or {}
    return jsonify({"cancelled": installer.cancel(body.get("provider"),
                                                  body.get("model"))})


@app.get("/api/params")
def param_specs():
    return jsonify([
        {"key": k, "label": lbl, "min": lo, "max": hi, "step": step,
         "default": default, "hint": hint}
        for k, lbl, lo, hi, step, default, hint in providers.PARAM_SPECS
    ])


# ---------------- personas ----------------

def _validate_persona(data: dict) -> dict:
    if not isinstance(data, dict) or not (data.get("name") or "").strip():
        abort(400, "persona name is required")
    return {
        "name": data["name"].strip(), "icon": (data.get("icon") or "🧑")[:8],
        "role": data.get("role", ""), "description": data.get("description", ""),
        "system_prompt": data.get("system_prompt", ""),
        "provider": data.get("provider") if data.get("provider") in ("ollama", "lmstudio") else "ollama",
        "model": data.get("model", ""),
        "params": providers.clean_params(data.get("params")),
        "tools": [t for t in (data.get("tools") or []) if t in tools_mod.valid_tool_names()],
        "skills": [s for s in (data.get("skills") or [])
                   if s in {x["name"] for x in storage.list_skills()}],
    }


@app.get("/api/personas")
def personas_list():
    return jsonify(storage.list_personas())


@app.post("/api/personas")
def personas_create():
    return jsonify(storage.create_persona(_validate_persona(request.get_json(force=True))))


@app.put("/api/personas/<int:pid>")
def personas_update(pid):
    if not storage.get_persona(pid):
        abort(404)
    return jsonify(storage.update_persona(pid, _validate_persona(request.get_json(force=True))))


@app.delete("/api/personas/<int:pid>")
def personas_delete(pid):
    storage.delete_persona(pid)
    return jsonify({"ok": True})


@app.post("/api/personas/<int:pid>/sprite")
def personas_sprite(pid):
    """Generate the persona's creature sprite (SLOW: minutes on a weak GPU).

    Species/evolution come deterministically from the persona's model family
    and size (sprites.py); an optional 'flavor' adds accessories. Uses a local
    GBA/pokemon LoRA automatically when one is installed.
    """
    import imagegen
    import sprites
    persona = storage.get_persona(pid)
    if not persona:
        abort(404)
    if not persona.get("model"):
        abort(400, "persona has no model to derive a species from")
    body = request.get_json(force=True) or {}
    catalog_params = None
    try:
        import catalog as catalog_mod
        base = persona["model"].split(":")[0].lower()
        for m in (catalog_mod.load_cache() or {}).get("models", []):
            if m.get("name") == persona["model"] and m.get("params_b"):
                catalog_params = m["params_b"]
                break
    except Exception:  # noqa: BLE001
        pass
    spec = sprites.build_sprite_prompt(
        persona["model"], persona.get("role", ""), persona.get("tools"),
        catalog_params=catalog_params,
        flavor=body.get("flavor") or "")
    gen_loras = None
    try:
        import loras
        match = next((f["file_name"] for f in loras.list_local()
                      if re.search(r"pokemon|gba|sprite|pixel", f["file_name"], re.I)),
                     None)
        if match:
            gen_loras = [{"file_name": match, "weight": 0.8}]
    except Exception:  # noqa: BLE001 - lora subsystem optional
        pass
    result = imagegen.generate(spec["prompt"], negative=spec["negative"],
                               aspect="1024*1024",
                               performance=body.get("performance"),
                               loras=gen_loras, styles=[])
    if not result.get("ok") or not result.get("images"):
        abort(502, f"sprite generation failed: {result.get('error')}")
    meta = {"species": spec["species"], "family": spec["family"],
            "stage": spec["stage"], "params_b": spec["params_b"],
            "prompt": spec["prompt"],
            "lora": gen_loras[0]["file_name"] if gen_loras else None}
    return jsonify(storage.set_persona_sprite(pid, result["images"][0], meta))


# ---------------- teams ----------------

@app.get("/api/teams")
def teams_list():
    return jsonify(storage.list_teams())


@app.post("/api/teams")
def teams_create():
    return jsonify(storage.create_team(_validate_team(request.get_json(force=True))))


@app.get("/api/teams/<int:team_id>")
def teams_get(team_id):
    team = storage.get_team(team_id)
    if not team:
        abort(404)
    return jsonify(team)


@app.put("/api/teams/<int:team_id>")
def teams_update(team_id):
    if not storage.get_team(team_id):
        abort(404)
    return jsonify(storage.update_team(team_id, _validate_team(request.get_json(force=True))))


@app.delete("/api/teams/<int:team_id>")
def teams_delete(team_id):
    storage.delete_team(team_id)
    return jsonify({"ok": True})


# ---------------- runs ----------------

@app.post("/api/teams/<int:team_id>/runs")
def runs_create(team_id):
    team = storage.get_team(team_id)
    if not team:
        abort(404)
    body = request.get_json(force=True)
    task = (body.get("task") or "").strip()
    if not task:
        abort(400, "task is required")
    run_id = manager.start(team, task)
    return jsonify({"run_id": run_id})


@app.get("/api/runs")
def runs_list():
    team_id = request.args.get("team_id", type=int)
    return jsonify(storage.list_runs(team_id=team_id))


@app.get("/api/runs/<int:run_id>")
def runs_get(run_id):
    run = storage.get_run(run_id)
    if not run:
        abort(404)
    run["events"] = storage.get_events(run_id)
    return jsonify(run)


@app.post("/api/runs/<int:run_id>/stop")
def runs_stop(run_id):
    return jsonify({"stopped": manager.stop(run_id)})


@app.get("/api/runs/<int:run_id>/artifacts")
def run_artifacts(run_id):
    ws = os.path.join(WORKSPACES, str(run_id))
    files = []
    if os.path.isdir(ws):
        for base, _dirs, names in os.walk(ws):
            for n in names:
                p = os.path.join(base, n)
                files.append({"path": os.path.relpath(p, ws),
                              "size": os.path.getsize(p)})
    return jsonify(sorted(files, key=lambda f: f["path"]))


@app.get("/api/runs/<int:run_id>/artifacts.zip")
def run_artifacts_zip(run_id):
    import io
    import zipfile
    ws = os.path.join(WORKSPACES, str(run_id))
    if not os.path.isdir(ws):
        abort(404)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for base, _dirs, names in os.walk(ws):
            for n in names:
                p = os.path.join(base, n)
                zf.write(p, os.path.relpath(p, ws))
    buf.seek(0)
    return Response(buf.read(), mimetype="application/zip",
                    headers={"Content-Disposition":
                             f"attachment; filename=run-{run_id}.zip"})


@app.get("/api/runs/<int:run_id>/artifacts/<path:relpath>")
def run_artifact_file(run_id, relpath):
    ws = os.path.realpath(os.path.join(WORKSPACES, str(run_id)))
    return send_from_directory(ws, relpath, as_attachment=False,
                               mimetype="text/plain")


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


@app.get("/api/runs/<int:run_id>/events")
def run_events(run_id):
    run = storage.get_run(run_id)
    if not run:
        abort(404)

    def generate():
        active = manager.get(run_id)
        q = active.subscribe() if active else None
        # Replay persisted events first (covers reconnects and finished runs).
        last_seq = 0
        for e in storage.get_events(run_id):
            last_seq = max(last_seq, e["seq"])
            yield _sse({"seq": e["seq"], "type": e["type"], "agent": e["agent"],
                        "content": e["content"], "meta": e["meta"]})
        if q is None:
            cur = storage.get_run(run_id)
            yield _sse({"type": "run_end", "content": cur.get("final") or "",
                        "meta": {"status": cur["status"], "replay": True}})
            return
        try:
            while True:
                try:
                    item = q.get(timeout=25)
                except queue.Empty:
                    yield ": keepalive\n\n"
                    continue
                if not isinstance(item, dict):  # sentinel -> run finished
                    break
                if item.get("seq", 0) <= last_seq and item["type"] != "token":
                    continue  # already replayed from DB
                yield _sse(item)
                if item["type"] == "run_end":
                    break
        finally:
            if active:
                active.unsubscribe(q)

    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no",
                             "Connection": "keep-alive"})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5860))
    app.run(host="127.0.0.1", port=port, debug=False, threaded=True)
