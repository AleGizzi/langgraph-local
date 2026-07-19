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
    allow_destructive INTEGER NOT NULL DEFAULT 0,
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
    value REAL,
    log TEXT,
    run_id INTEGER,
    note_path TEXT
);
CREATE INDEX IF NOT EXISTS idx_sched_runs ON schedule_runs(schedule_id, ran_at);
CREATE TABLE IF NOT EXISTS resources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    url TEXT NOT NULL,
    summary TEXT,
    category TEXT NOT NULL DEFAULT 'news',
    source TEXT NOT NULL DEFAULT 'agent',
    added_at REAL NOT NULL,
    UNIQUE(url)
);
CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    body TEXT,
    level TEXT NOT NULL DEFAULT 'normal',
    source TEXT,
    link TEXT,
    read INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER,
    team_name TEXT,
    role TEXT,
    agent_name TEXT,
    model TEXT NOT NULL,
    provider TEXT,
    kind TEXT,
    mode TEXT,
    outcome TEXT NOT NULL,
    detail TEXT,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_decisions_model ON decisions(model, outcome);
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
    keys = r.keys()
    return {"id": r["id"], "name": r["name"], "prompt": r["prompt"],
            "agent": json.loads(r["agent"] or "{}"),
            "team_id": r["team_id"] if "team_id" in keys else None,
            "interval_seconds": r["interval_seconds"], "enabled": bool(r["enabled"]),
            "track_number": bool(r["track_number"]),
            "notify": bool(r["notify"]) if "notify" in keys else False,
            "allow_destructive": bool(r["allow_destructive"]) if "allow_destructive" in keys else False,
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
            "INSERT INTO schedules (name, prompt, agent, team_id, interval_seconds,"
            " enabled, track_number, notify, allow_destructive, knowledge_folder,"
            " next_run, created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (d.get("name", "Scheduled task"), d.get("prompt", ""),
             json.dumps(d.get("agent", {})), d.get("team_id"),
             int(d.get("interval_seconds", 86400)),
             int(bool(d.get("enabled", True))), int(bool(d.get("track_number", False))),
             int(bool(d.get("notify", False))), int(bool(d.get("allow_destructive", False))),
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
            "UPDATE schedules SET name=?, prompt=?, agent=?, team_id=?,"
            " interval_seconds=?, enabled=?, track_number=?, notify=?,"
            " allow_destructive=?, knowledge_folder=?, last_run=?, last_result=?,"
            " next_run=? WHERE id=?",
            (m["name"], m["prompt"], json.dumps(m["agent"]), m.get("team_id"),
             int(m["interval_seconds"]), int(bool(m["enabled"])),
             int(bool(m["track_number"])), int(bool(m.get("notify"))),
             int(bool(m.get("allow_destructive"))),
             m.get("knowledge_folder"), m.get("last_run"), m.get("last_result"),
             m.get("next_run"), sid))
    return get_schedule(sid)


def delete_schedule(sid: int):
    with _conn() as c:
        c.execute("DELETE FROM schedule_runs WHERE schedule_id=?", (sid,))
        c.execute("DELETE FROM schedules WHERE id=?", (sid,))


def add_schedule_run(sid: int, ok: bool, result: str, value=None,
                     log: str = None, run_id: int = None,
                     note_path: str = None) -> int:
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO schedule_runs (schedule_id, ran_at, ok, result, value, log, run_id, note_path)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (sid, time.time(), int(bool(ok)), (result or "")[:8000], value,
             (log or "")[:40000] or None, run_id, note_path))
        return cur.lastrowid


def list_schedule_runs(sid: int, limit: int = 200, with_log: bool = False) -> list:
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM schedule_runs WHERE schedule_id=? ORDER BY ran_at ASC"
            " LIMIT ?", (sid, limit)).fetchall()
    out = []
    for r in rows:
        keys = r.keys()
        d = {"id": r["id"], "ran_at": r["ran_at"], "ok": bool(r["ok"]),
             "result": r["result"], "value": r["value"],
             "run_id": r["run_id"] if "run_id" in keys else None,
             "note_path": r["note_path"] if "note_path" in keys else None}
        if with_log:
            d["log"] = r["log"] if "log" in keys else None
        out.append(d)
    return out


def get_schedule_run(rid: int):
    with _conn() as c:
        r = c.execute("SELECT * FROM schedule_runs WHERE id=?", (rid,)).fetchone()
    if not r:
        return None
    keys = r.keys()
    return {"id": r["id"], "schedule_id": r["schedule_id"], "ran_at": r["ran_at"],
            "ok": bool(r["ok"]), "result": r["result"], "value": r["value"],
            "log": r["log"], "run_id": r["run_id"],
            "note_path": r["note_path"] if "note_path" in keys else None}


# ---------------- resources (AI news / trainings) ----------------

def list_resources(category: str = None) -> list:
    with _conn() as c:
        if category:
            rows = c.execute("SELECT * FROM resources WHERE category=? ORDER BY added_at DESC",
                             (category,)).fetchall()
        else:
            rows = c.execute("SELECT * FROM resources ORDER BY added_at DESC").fetchall()
    return [dict(r) for r in rows]


def add_resource(d: dict) -> bool:
    """Insert a resource; returns True if new, False if the URL already exists."""
    url = (d.get("url") or "").strip()
    if not url:
        return False
    with _conn() as c:
        cur = c.execute(
            "INSERT OR IGNORE INTO resources (title, url, summary, category, source, added_at)"
            " VALUES (?,?,?,?,?,?)",
            (d.get("title", url)[:300], url, (d.get("summary") or "")[:600],
             d.get("category", "news"), d.get("source", "agent"), time.time()))
        return cur.rowcount > 0


def delete_resource(rid: int):
    with _conn() as c:
        c.execute("DELETE FROM resources WHERE id=?", (rid,))


# ---------------- notifications ----------------

def add_notification(d: dict) -> int:
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO notifications (title, body, level, source, link, created_at)"
            " VALUES (?,?,?,?,?,?)",
            (d.get("title", "")[:200], (d.get("body") or "")[:2000],
             d.get("level", "normal"), d.get("source"), d.get("link"), time.time()))
        return cur.lastrowid


def list_notifications(limit: int = 50) -> list:
    with _conn() as c:
        rows = c.execute("SELECT * FROM notifications ORDER BY id DESC LIMIT ?",
                         (limit,)).fetchall()
    return [dict(r) | {"read": bool(r["read"])} for r in rows]


def unread_notification_count() -> int:
    with _conn() as c:
        return c.execute("SELECT COUNT(*) n FROM notifications WHERE read=0").fetchone()["n"]


def mark_notifications_read(ids=None):
    with _conn() as c:
        if ids:
            q = ",".join("?" * len(ids))
            c.execute(f"UPDATE notifications SET read=1 WHERE id IN ({q})", tuple(ids))
        else:
            c.execute("UPDATE notifications SET read=1")


def clear_notifications():
    with _conn() as c:
        c.execute("DELETE FROM notifications")


# ---------------- decision log ----------------
# Records what model did what task and how it turned out, so the model-routing
# tables can be tuned on evidence (see engine._record_decision). Outcome is one
# of: accepted | rebriefed | escalated | failed.

def add_decision(d: dict) -> int:
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO decisions (run_id, team_name, role, agent_name, model,"
            " provider, kind, mode, outcome, detail, created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (d.get("run_id"), d.get("team_name"), d.get("role"), d.get("agent_name"),
             d.get("model", "?"), d.get("provider"), d.get("kind"), d.get("mode"),
             d.get("outcome", "accepted"), (d.get("detail") or "")[:500], time.time()))
        return cur.lastrowid


def list_decisions(limit: int = 200) -> list:
    with _conn() as c:
        rows = c.execute("SELECT * FROM decisions ORDER BY id DESC LIMIT ?",
                         (limit,)).fetchall()
    return [dict(r) for r in rows]


def decision_stats() -> list:
    """Accept-rate per (model, role), newest-weighted only by recency of rows.

    'accepted' and 'rebriefed' both count as the model ultimately delivering;
    'escalated' and 'failed' are misses. The distinction the caller cares about
    is the escalate rate — that is what justifies bumping a model tier."""
    with _conn() as c:
        rows = c.execute(
            "SELECT model, role, outcome, COUNT(*) n FROM decisions"
            " GROUP BY model, role, outcome").fetchall()
    agg = {}
    for r in rows:
        key = (r["model"], r["role"] or "")
        a = agg.setdefault(key, {"model": r["model"], "role": r["role"] or "",
                                 "total": 0, "accepted": 0, "rebriefed": 0,
                                 "escalated": 0, "failed": 0})
        a["total"] += r["n"]
        if r["outcome"] in a:
            a[r["outcome"]] += r["n"]
    out = []
    for a in agg.values():
        t = a["total"] or 1
        a["accept_rate"] = round((a["accepted"] + a["rebriefed"]) / t, 3)
        a["escalate_rate"] = round((a["escalated"] + a["failed"]) / t, 3)
        out.append(a)
    out.sort(key=lambda x: (-x["total"], x["model"]))
    return out


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
        # Schedules gained team scheduling + per-run debug logs after first ship.
        scols = {r["name"] for r in c.execute("PRAGMA table_info(schedules)")}
        if scols and "team_id" not in scols:
            c.execute("ALTER TABLE schedules ADD COLUMN team_id INTEGER")
        if scols and "notify" not in scols:
            c.execute("ALTER TABLE schedules ADD COLUMN notify INTEGER NOT NULL DEFAULT 0")
        if scols and "allow_destructive" not in scols:
            c.execute("ALTER TABLE schedules ADD COLUMN allow_destructive INTEGER NOT NULL DEFAULT 0")
        srcols = {r["name"] for r in c.execute("PRAGMA table_info(schedule_runs)")}
        if srcols and "log" not in srcols:
            c.execute("ALTER TABLE schedule_runs ADD COLUMN log TEXT")
        if srcols and "run_id" not in srcols:
            c.execute("ALTER TABLE schedule_runs ADD COLUMN run_id INTEGER")
        if srcols and "note_path" not in srcols:
            c.execute("ALTER TABLE schedule_runs ADD COLUMN note_path TEXT")


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
