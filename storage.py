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
"""


def _conn():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    c = sqlite3.connect(DB_PATH, timeout=15)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    return c


def init_db():
    with _conn() as c:
        c.executescript(_SCHEMA)
        cols = {r["name"] for r in c.execute("PRAGMA table_info(teams)")}
        if "graph" not in cols:
            c.execute("ALTER TABLE teams ADD COLUMN graph TEXT")


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
            " provider, model, params, tools, builtin, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (d["name"], d.get("icon", "🧑"), d.get("role", ""), d.get("description", ""),
             d.get("system_prompt", ""), d.get("provider", "ollama"), d.get("model", ""),
             json.dumps(d.get("params", {})), json.dumps(d.get("tools", [])),
             int(builtin), now, now))
        return get_persona(cur.lastrowid)


def update_persona(pid: int, d: dict):
    with _conn() as c:
        c.execute(
            "UPDATE personas SET name=?, icon=?, role=?, description=?, system_prompt=?,"
            " provider=?, model=?, params=?, tools=?, updated_at=? WHERE id=?",
            (d["name"], d.get("icon", "🧑"), d.get("role", ""), d.get("description", ""),
             d.get("system_prompt", ""), d.get("provider", "ollama"), d.get("model", ""),
             json.dumps(d.get("params", {})), json.dumps(d.get("tools", [])),
             time.time(), pid))
    return get_persona(pid)


def delete_persona(pid: int):
    with _conn() as c:
        c.execute("DELETE FROM personas WHERE id=?", (pid,))


def count_personas() -> int:
    with _conn() as c:
        return c.execute("SELECT COUNT(*) FROM personas").fetchone()[0]


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
