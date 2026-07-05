"""Local Agents Studio — a Dify-style UI for LangGraph agent teams running on
local models (Ollama / LM Studio). Single-user, fully local.
"""
import json
import os
import queue

from flask import Flask, Response, abort, jsonify, request, send_from_directory

import providers
import seeds
import storage
from runmanager import WORKSPACES, manager
from tools import TOOL_CATALOG

app = Flask(__name__, static_folder="static", static_url_path="/static")
app.config["JSON_AS_ASCII"] = False

storage.init_db()
storage.mark_stale_runs()
seeds.seed_if_empty()

VALID_TOPOLOGIES = {"single", "pipeline", "supervisor"}


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
        a["tools"] = [t for t in (a.get("tools") or []) if t in TOOL_CATALOG]
    settings = data.get("settings") or {}
    clean = {}
    if settings.get("quality_loop"):
        clean["quality_loop"] = True
    try:
        clean["max_revisions"] = min(5, max(0, int(settings.get("max_revisions", 2))))
    except (TypeError, ValueError):
        clean["max_revisions"] = 2
    try:
        clean["max_steps"] = min(20, max(1, int(settings.get("max_steps", 8))))
    except (TypeError, ValueError):
        clean["max_steps"] = 8
    return {"name": name, "icon": (data.get("icon") or "🤖")[:8],
            "description": data.get("description", ""), "topology": topology,
            "agents": agents, "settings": clean}


@app.get("/")
def index():
    return send_from_directory("static", "index.html")


@app.get("/api/health")
def health():
    return jsonify({"ok": True, "providers": providers.provider_status()})


@app.get("/api/models")
def models():
    return jsonify(providers.list_models())


@app.get("/api/tools")
def tools_catalog():
    return jsonify(TOOL_CATALOG)


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
