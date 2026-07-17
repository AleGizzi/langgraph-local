"""SQLite persistence for teams, runs and run events.

Uses a new connection per operation so it is safe from any thread.
JSON columns keep the schema flexible (agent lists, settings).
"""
import json
import os
import sqlite3
import time

DB_PATH = os.environ.get(
    "AGENTS_DB", os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "agents.db")
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS teams (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    icon TEXT NOT NULL DEFAULT '🤖',
    description TEXT NOT NULL DEFAULT '',
    topology TEXT NOT NULL DEFAULT 'pipeline',
    agents TEXT NOT NULL DEFAULT '[]',
    settings TEXT NOT NULL DEFAULT '{}',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    team_id INTEGER NOT NULL,
    team_name TEXT NOT NULL DEFAULT '',
    task TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'running',
    final TEXT,
    error TEXT,
    created_at REAL NOT NULL,
    finished_at REAL
);
CREATE TABLE IF NOT EXISTS personas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    icon TEXT NOT NULL DEFAULT '🧑',
    role TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    system_prompt TEXT NOT NULL DEFAULT '',
    provider TEXT NOT NULL DEFAULT 'ollama',
    model TEXT NOT NULL DEFAULT '',
    params TEXT NOT NULL DEFAULT '{}',
    tools TEXT NOT NULL DEFAULT '[]',
    builtin INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS skills (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    icon TEXT NOT NULL DEFAULT '✨',
    description TEXT NOT NULL DEFAULT '',
    instructions TEXT NOT NULL DEFAULT '',
    builtin INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS chats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL DEFAULT '',
    agent TEXT NOT NULL DEFAULT '{}',
    messages TEXT NOT NULL DEFAULT '[]',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS image_jobs (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    params TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'queued',
    images TEXT NOT NULL DEFAULT '[]',
    error TEXT,
    backend_job_id TEXT,
    created REAL NOT NULL,
    started REAL,
    finished REAL
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    seq INTEGER NOT NULL,
    type TEXT NOT NULL,
    agent TEXT,
    content TEXT,
    meta TEXT,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_run ON events(run_id, seq);
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS schedules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    prompt TEXT NOT NULL,
    agent TEXT NOT NULL DEFAULT '{}',
    interval_seconds INTEGER NOT NULL DEFAULT 86400,
    enabled INTEGER NOT NULL DEFAULT 1,
    track_number INTEGER NOT NULL DEFAULT 0,
    knowledge_folder TEXT,
    last_run REAL,
    last_result TEXT,
    next_run REAL,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS schedule_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    schedule_id INTEGER NOT NULL,
    ran_at REAL NOT NULL,
    ok INTEGER NOT NULL,
    result TEXT,
    value REAL
);
CREATE INDEX IF NOT EXISTS idx_sched_runs ON schedule_runs(schedule_id, ran_at);
"""


def _conn():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    c = sqlite3.connect(DB_PATH, timeout=15)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    return c


def get_meta(key: str, default=None):
    with _conn() as c:
        r = c.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return json.loads(r["value"]) if r else default


def set_meta(key: str, value):
    with _conn() as c:
        c.execute("INSERT INTO meta (key, value) VALUES (?,?) "
                  "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                  (key, json.dumps(value)))


# ---------------- schedules ----------------

def _schedule_row(r) -> dict:
    return {"id": r["id"], "name": r["name"], "prompt": r["prompt"],
            "agent": json.loads(r["agent"] or "{}"),
            "interval_seconds": r["interval_seconds"], "enabled": bool(r["enabled"]),
            "track_number": bool(r["track_number"]),
            "knowledge_folder": r["knowledge_folder"],
            "last_run": r["last_run"], "last_result": r["last_result"],
            "next_run": r["next_run"], "created_at": r["created_at"]}


def list_schedules() -> list:
    with _conn() as c:
        rows = c.execute("SELECT * FROM schedules ORDER BY id DESC").fetchall()
    return [_schedule_row(r) for r in rows]


def get_schedule(sid: int):
    with _conn() as c:
        r = c.execute("SELECT * FROM schedules WHERE id=?", (sid,)).fetchone()
    return _schedule_row(r) if r else None


def create_schedule(d: dict) -> dict:
    now = time.time()
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO schedules (name, prompt, agent, interval_seconds, enabled,"
            " track_number, knowledge_folder, next_run, created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (d.get("name", "Scheduled task"), d.get("prompt", ""),
             json.dumps(d.get("agent", {})), int(d.get("interval_seconds", 86400)),
             int(bool(d.get("enabled", True))), int(bool(d.get("track_number", False))),
             d.get("knowledge_folder"), now, now))
        sid = cur.lastrowid
    return get_schedule(sid)


def update_schedule(sid: int, d: dict):
    cur = get_schedule(sid)
    if not cur:
        return None
    m = {**cur, **d}
    with _conn() as c:
        c.execute(
            "UPDATE schedules SET name=?, prompt=?, agent=?, interval_seconds=?,"
            " enabled=?, track_number=?, knowledge_folder=?, last_run=?,"
            " last_result=?, next_run=? WHERE id=?",
            (m["name"], m["prompt"], json.dumps(m["agent"]), int(m["interval_seconds"]),
             int(bool(m["enabled"])), int(bool(m["track_number"])),
             m.get("knowledge_folder"), m.get("last_run"), m.get("last_result"),
             m.get("next_run"), sid))
    return get_schedule(sid)


def delete_schedule(sid: int):
    with _conn() as c:
        c.execute("DELETE FROM schedule_runs WHERE schedule_id=?", (sid,))
        c.execute("DELETE FROM schedules WHERE id=?", (sid,))


def add_schedule_run(sid: int, ok: bool, result: str, value=None) -> int:
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO schedule_runs (schedule_id, ran_at, ok, result, value)"
            " VALUES (?,?,?,?,?)",
            (sid, time.time(), int(bool(ok)), (result or "")[:8000], value))
        return cur.lastrowid


def list_schedule_runs(sid: int, limit: int = 200) -> list:
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM schedule_runs WHERE schedule_id=? ORDER BY ran_at ASC"
            " LIMIT ?", (sid, limit)).fetchall()
    return [{"id": r["id"], "ran_at": r["ran_at"], "ok": bool(r["ok"]),
             "result": r["result"], "value": r["value"]} for r in rows]


def init_db():
    with _conn() as c:
        c.executescript(_SCHEMA)
        cols = {r["name"] for r in c.execute("PRAGMA table_info(teams)")}
        if "graph" not in cols:
            c.execute("ALTER TABLE teams ADD COLUMN graph TEXT")
        pcols = {r["name"] for r in c.execute("PRAGMA table_info(personas)")}
        if "skills" not in pcols:
            c.execute("ALTER TABLE personas ADD COLUMN skills TEXT NOT NULL DEFAULT '[]'")
        if "sprite" not in pcols:
            c.execute("ALTER TABLE personas ADD COLUMN sprite TEXT")
            c.execute("ALTER TABLE personas ADD COLUMN sprite_meta TEXT")


def _team_row_to_dict(r) -> dict:
    return {
        "id": r["id"], "name": r["name"], "icon": r["icon"],
        "description": r["description"], "topology": r["topology"],
        "agents": json.loads(r["agents"]), "settings": json.loads(r["settings"]),
        "graph": json.loads(r["graph"]) if r["graph"] else None,
        "created_at": r["created_at"], "updated_at": r["updated_at"],
    }


# ---------------- teams ----------------

def list_teams() -> list:
    with _conn() as c:
        rows = c.execute("SELECT * FROM teams ORDER BY updated_at DESC").fetchall()
    return [_team_row_to_dict(r) for r in rows]


def get_team(team_id: int):
    with _conn() as c:
        r = c.execute("SELECT * FROM teams WHERE id=?", (team_id,)).fetchone()
    return _team_row_to_dict(r) if r else None


def create_team(data: dict) -> dict:
    now = time.time()
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO teams (name, icon, description, topology, agents, settings,"
            " graph, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (data["name"], data.get("icon", "🤖"), data.get("description", ""),
             data.get("topology", "pipeline"), json.dumps(data.get("agents", [])),
             json.dumps(data.get("settings", {})),
             json.dumps(data["graph"]) if data.get("graph") else None, now, now),
        )
        team_id = cur.lastrowid
    return get_team(team_id)


def update_team(team_id: int, data: dict):
    now = time.time()
    with _conn() as c:
        c.execute(
            "UPDATE teams SET name=?, icon=?, description=?, topology=?, agents=?,"
            " settings=?, graph=?, updated_at=? WHERE id=?",
            (data["name"], data.get("icon", "🤖"), data.get("description", ""),
             data.get("topology", "pipeline"), json.dumps(data.get("agents", [])),
             json.dumps(data.get("settings", {})),
             json.dumps(data["graph"]) if data.get("graph") else None, now, team_id),
        )
    return get_team(team_id)


def delete_team(team_id: int):
    with _conn() as c:
        c.execute("DELETE FROM teams WHERE id=?", (team_id,))


def count_teams() -> int:
    with _conn() as c:
        return c.execute("SELECT COUNT(*) FROM teams").fetchone()[0]


# ---------------- personas ----------------

def _persona_row_to_dict(r) -> dict:
    return {
        "id": r["id"], "name": r["name"], "icon": r["icon"], "role": r["role"],
        "description": r["description"], "system_prompt": r["system_prompt"],
        "provider": r["provider"], "model": r["model"],
        "params": json.loads(r["params"]), "tools": json.loads(r["tools"]),
        "skills": json.loads(r["skills"]) if "skills" in r.keys() and r["skills"] else [],
        "sprite": r["sprite"] if "sprite" in r.keys() else None,
        "sprite_meta": (json.loads(r["sprite_meta"])
                        if "sprite_meta" in r.keys() and r["sprite_meta"] else None),
        "builtin": bool(r["builtin"]),
    }


def list_personas() -> list:
    with _conn() as c:
        rows = c.execute("SELECT * FROM personas ORDER BY builtin DESC, name").fetchall()
    return [_persona_row_to_dict(r) for r in rows]


def get_persona(pid: int):
    with _conn() as c:
        r = c.execute("SELECT * FROM personas WHERE id=?", (pid,)).fetchone()
    return _persona_row_to_dict(r) if r else None


def create_persona(d: dict, builtin: bool = False) -> dict:
    now = time.time()
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO personas (name, icon, role, description, system_prompt,"
            " provider, model, params, tools, skills, builtin, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (d["name"], d.get("icon", "🧑"), d.get("role", ""), d.get("description", ""),
             d.get("system_prompt", ""), d.get("provider", "ollama"), d.get("model", ""),
             json.dumps(d.get("params", {})), json.dumps(d.get("tools", [])),
             json.dumps(d.get("skills", [])), int(builtin), now, now))
        pid = cur.lastrowid
    return get_persona(pid)


def update_persona(pid: int, d: dict):
    with _conn() as c:
        c.execute(
            "UPDATE personas SET name=?, icon=?, role=?, description=?, system_prompt=?,"
            " provider=?, model=?, params=?, tools=?, skills=?, updated_at=? WHERE id=?",
            (d["name"], d.get("icon", "🧑"), d.get("role", ""), d.get("description", ""),
             d.get("system_prompt", ""), d.get("provider", "ollama"), d.get("model", ""),
             json.dumps(d.get("params", {})), json.dumps(d.get("tools", [])),
             json.dumps(d.get("skills", [])), time.time(), pid))
    return get_persona(pid)


def set_persona_sprite(pid: int, sprite: str, meta: dict):
    with _conn() as c:
        c.execute("UPDATE personas SET sprite=?, sprite_meta=?, updated_at=? WHERE id=?",
                  (sprite, json.dumps(meta) if meta else None, time.time(), pid))
    return get_persona(pid)


def delete_persona(pid: int):
    with _conn() as c:
        c.execute("DELETE FROM personas WHERE id=?", (pid,))


def count_personas() -> int:
    with _conn() as c:
        return c.execute("SELECT COUNT(*) FROM personas").fetchone()[0]


# ---------------- chats ----------------

def _chat_row(r, with_messages=True) -> dict:
    d = {"id": r["id"], "title": r["title"], "agent": json.loads(r["agent"]),
         "created_at": r["created_at"], "updated_at": r["updated_at"]}
    if with_messages:
        d["messages"] = json.loads(r["messages"])
    else:
        msgs = json.loads(r["messages"])
        d["message_count"] = len(msgs)
    return d


def list_chats(limit: int = 100) -> list:
    with _conn() as c:
        rows = c.execute("SELECT * FROM chats ORDER BY updated_at DESC LIMIT ?",
                         (limit,)).fetchall()
    return [_chat_row(r, with_messages=False) for r in rows]


def get_chat(cid: int):
    with _conn() as c:
        r = c.execute("SELECT * FROM chats WHERE id=?", (cid,)).fetchone()
    return _chat_row(r) if r else None


def create_chat(d: dict) -> dict:
    now = time.time()
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO chats (title, agent, messages, created_at, updated_at)"
            " VALUES (?,?,?,?,?)",
            (d.get("title", ""), json.dumps(d.get("agent", {})),
             json.dumps(d.get("messages", [])), now, now))
        cid = cur.lastrowid
    return get_chat(cid)


def update_chat(cid: int, d: dict):
    with _conn() as c:
        c.execute(
            "UPDATE chats SET title=?, agent=?, messages=?, updated_at=? WHERE id=?",
            (d.get("title", ""), json.dumps(d.get("agent", {})),
             json.dumps(d.get("messages", [])), time.time(), cid))
    return get_chat(cid)


def delete_chat(cid: int):
    with _conn() as c:
        c.execute("DELETE FROM chats WHERE id=?", (cid,))


# ---------------- image jobs (durable queue) ----------------

def _image_job_row(r) -> dict:
    return {"id": r["id"], "kind": r["kind"], "params": json.loads(r["params"]),
            "status": r["status"], "images": json.loads(r["images"]),
            "error": r["error"], "backend_job_id": r["backend_job_id"],
            "created": r["created"], "started": r["started"],
            "finished": r["finished"]}


def list_image_jobs(limit: int = 80) -> list:
    with _conn() as c:
        rows = c.execute("SELECT * FROM image_jobs ORDER BY created DESC LIMIT ?",
                         (limit,)).fetchall()
    return [_image_job_row(r) for r in rows]


def create_image_job(job_id: str, kind: str, params: dict):
    with _conn() as c:
        c.execute("INSERT INTO image_jobs (id, kind, params, status, created)"
                  " VALUES (?,?,?, 'queued', ?)",
                  (job_id, kind, json.dumps(params), time.time()))


def update_image_job(job_id: str, **fields):
    if not fields:
        return
    cols, vals = [], []
    for k, v in fields.items():
        if k in ("params", "images"):
            v = json.dumps(v)
        cols.append(f"{k}=?")
        vals.append(v)
    vals.append(job_id)
    with _conn() as c:
        c.execute(f"UPDATE image_jobs SET {', '.join(cols)} WHERE id=?", vals)


def delete_finished_image_jobs():
    with _conn() as c:
        c.execute("DELETE FROM image_jobs WHERE status IN "
                  "('done','error','cancelled')")


# ---------------- skills ----------------

def _skill_row_to_dict(r) -> dict:
    return {"id": r["id"], "name": r["name"], "icon": r["icon"],
            "description": r["description"], "instructions": r["instructions"],
            "builtin": bool(r["builtin"])}


def list_skills() -> list:
    with _conn() as c:
        rows = c.execute("SELECT * FROM skills ORDER BY builtin DESC, name").fetchall()
    return [_skill_row_to_dict(r) for r in rows]


def get_skill(sid: int):
    with _conn() as c:
        r = c.execute("SELECT * FROM skills WHERE id=?", (sid,)).fetchone()
    return _skill_row_to_dict(r) if r else None


def create_skill(d: dict, builtin: bool = False) -> dict:
    now = time.time()
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO skills (name, icon, description, instructions, builtin,"
            " created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
            (d["name"], d.get("icon", "✨"), d.get("description", ""),
             d.get("instructions", ""), int(builtin), now, now))
        sid = cur.lastrowid
    return get_skill(sid)


def update_skill(sid: int, d: dict):
    with _conn() as c:
        c.execute(
            "UPDATE skills SET name=?, icon=?, description=?, instructions=?,"
            " updated_at=? WHERE id=?",
            (d["name"], d.get("icon", "✨"), d.get("description", ""),
             d.get("instructions", ""), time.time(), sid))
    return get_skill(sid)


def delete_skill(sid: int):
    with _conn() as c:
        c.execute("DELETE FROM skills WHERE id=?", (sid,))


def count_skills() -> int:
    with _conn() as c:
        return c.execute("SELECT COUNT(*) FROM skills").fetchone()[0]


# ---------------- runs ----------------

def create_run(team_id: int, team_name: str, task: str) -> int:
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO runs (team_id, team_name, task, status, created_at)"
            " VALUES (?,?,?,'running',?)",
            (team_id, team_name, task, time.time()),
        )
        return cur.lastrowid


def finish_run(run_id: int, status: str, final: str = None, error: str = None):
    with _conn() as c:
        c.execute(
            "UPDATE runs SET status=?, final=?, error=?, finished_at=? WHERE id=?",
            (status, final, error, time.time(), run_id),
        )


def get_run(run_id: int):
    with _conn() as c:
        r = c.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
    return dict(r) if r else None


def list_runs(team_id: int = None, limit: int = 100) -> list:
    with _conn() as c:
        if team_id:
            rows = c.execute(
                "SELECT * FROM runs WHERE team_id=? ORDER BY id DESC LIMIT ?",
                (team_id, limit)).fetchall()
        else:
            rows = c.execute(
                "SELECT * FROM runs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]


def mark_stale_runs():
    """On startup, any run still 'running' was orphaned by a restart."""
    with _conn() as c:
        c.execute(
            "UPDATE runs SET status='error', error='Interrupted by server restart',"
            " finished_at=? WHERE status='running'", (time.time(),))


# ---------------- events ----------------

def add_event(run_id: int, seq: int, etype: str, agent: str = None,
              content: str = None, meta: dict = None):
    with _conn() as c:
        c.execute(
            "INSERT INTO events (run_id, seq, type, agent, content, meta, created_at)"
            " VALUES (?,?,?,?,?,?,?)",
            (run_id, seq, etype, agent, content,
             json.dumps(meta) if meta else None, time.time()),
        )


def get_events(run_id: int) -> list:
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM events WHERE run_id=? ORDER BY seq", (run_id,)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["meta"] = json.loads(d["meta"]) if d["meta"] else None
        out.append(d)
    return out
