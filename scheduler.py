"""Scheduled agent tasks: run an agent on an interval, unattended.

A schedule pairs an agent config (model, prompt, tools, skills) with an
interval. A single background thread wakes periodically, runs every due
schedule once, records the result (and, when tracking a number, the value it
extracted), then reschedules. Runs are serialized on one thread so the little
local GPU is never hit by several scheduled agents at once.

This is honest about what it is: cron for local agents. It only works while the
app process is running — the user explicitly wants the machine on 24/7. Pair it
with the systemd user service (docs/operations.md) for real persistence.
"""
import os
import re
import threading
import time
from urllib.parse import quote

import storage

_TICK = int(os.environ.get("SCHEDULER_TICK", "20"))   # seconds between wakeups
_lock = threading.Lock()
_started = False

_WORKSPACE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "workspaces", "scheduler")

# First standalone number in a string: "1.234,56", "$1234.5", "1,234.56", "42%".
_NUM_RE = re.compile(r"-?\d[\d.,]*\d|-?\d")

# The knowledge_write tool returns "Saved as <folder>/<file>.md" — capture that
# path so the schedule can link the user straight to the note it just wrote.
_NOTE_RE = re.compile(r"Saved as (\S+\.md)")


def _extract_number(text: str):
    """Best-effort single numeric value from a result (for tracking series).
    Handles both 1,234.56 and 1.234,56 groupings."""
    m = _NUM_RE.search(text or "")
    if not m:
        return None
    raw = m.group(0)
    # Decide the decimal separator by which appears last.
    if "," in raw and "." in raw:
        if raw.rfind(",") > raw.rfind("."):   # 1.234,56 → , is decimal
            raw = raw.replace(".", "").replace(",", ".")
        else:                                  # 1,234.56 → , is thousands
            raw = raw.replace(",", "")
    elif "," in raw:
        # lone comma: decimal if it looks like ,dd at the end, else thousands
        raw = raw.replace(",", ".") if re.search(r",\d{1,2}$", raw) else raw.replace(",", "")
    try:
        return float(raw)
    except ValueError:
        return None


def _fmt_ts():
    return time.strftime("%H:%M:%S")


def _run_team(sch: dict, prompt: str):
    """Run a scheduled TEAM to completion. Returns (final, err, log, run_id).
    The team run also lands in the Runs page, so its full timeline is browsable
    there; here we capture a compact log for the schedule's own history."""
    import runmanager
    team = storage.get_team(sch["team_id"])
    if not team:
        return "", f"team {sch['team_id']} no longer exists", "", None
    run_id = runmanager.manager.start(
        team, prompt, unattended=True,
        allow_destructive=bool(sch.get("allow_destructive")))
    note_path = None
    log = [f"[{_fmt_ts()}] team run #{run_id} started ({team['name']})"]
    # Wait for the run thread to finish (bounded — a scheduled run shouldn't
    # hang the scheduler forever).
    deadline = time.time() + 3600
    while time.time() < deadline:
        active = runmanager.manager.get(run_id)
        if active is None or active.done:
            break
        time.sleep(3)
    row = storage.get_run(run_id) or {}
    final = row.get("final") or ""
    err = row.get("error")
    status = row.get("status", "unknown")
    # Summarize the run's events into the schedule log for quick debugging.
    try:
        for e in storage.get_events(run_id):
            t = e.get("type")
            content = e.get("content") or ""
            if t == "tool_result":
                m = _NOTE_RE.search(content)
                if m:
                    note_path = m.group(1)
            if t in ("agent_start", "tool_call", "tool_result", "decision", "run_end"):
                c = content.splitlines()[0][:120] if content else ""
                log.append(f"[{t}] {e.get('agent') or ''} {c}".rstrip())
    except Exception:  # noqa: BLE001
        pass
    log.append(f"[{_fmt_ts()}] run #{run_id} finished: {status}")
    return final, err, "\n".join(log), run_id, note_path


def _run_agent(sch: dict, prompt: str):
    """Run a scheduled single agent, capturing a full event log."""
    import engine
    agent = dict(sch["agent"] or {})
    agent.setdefault("provider", "ollama")
    if sch.get("knowledge_folder"):
        tools = list(agent.get("tools") or [])
        if "knowledge" not in tools:
            tools.append("knowledge")
        agent["tools"] = tools
    try:
        skill_map = {s["name"]: s for s in storage.list_skills()}
    except Exception:  # noqa: BLE001
        skill_map = {}

    log = [f"[{_fmt_ts()}] agent {agent.get('model', '?')} started",
           f"prompt: {prompt[:300]}"]
    final, err, note_path = "", None, None
    try:
        for ev in engine.chat_stream(agent, [{"role": "user", "content": prompt}],
                                     _WORKSPACE, skill_map, unattended=True,
                                     allow_destructive=bool(sch.get("allow_destructive"))):
            t = ev.get("type")
            if t == "tool_call":
                log.append(f"[tool_call] {ev.get('content', '')[:160]}")
            elif t == "tool_result":
                content = ev.get("content") or ""
                m = _NOTE_RE.search(content)
                if m:
                    note_path = m.group(1)
                log.append(f"[tool_result] {content.splitlines()[0][:160] if content else ''}")
            elif t == "done":
                final = ev.get("content") or final
            elif t == "error":
                err = ev.get("content")
                log.append(f"[error] {err}")
    except Exception as e:  # noqa: BLE001 - a scheduled run must never crash the loop
        err = f"{type(e).__name__}: {e}"
        log.append(f"[exception] {err}")
    log.append(f"[{_fmt_ts()}] finished ({'ok' if (not err and final.strip()) else 'failed'})")
    return final, err, "\n".join(log), None, note_path


def run_schedule(sid: int) -> dict:
    """Run one schedule NOW (also used by the 'run now' button). Never raises."""
    sch = storage.get_schedule(sid)
    if not sch:
        return {"ok": False, "error": "no such schedule"}
    os.makedirs(_WORKSPACE, exist_ok=True)

    prompt = sch["prompt"]
    if sch.get("knowledge_folder"):
        prompt += (f"\n\nWhen done, save your finding as a knowledge note in the "
                   f"folder '{sch['knowledge_folder']}' using the knowledge tool, "
                   "with today's date, so it accumulates over time.")

    if sch.get("team_id"):
        final, err, log, run_id, note_path = _run_team(sch, prompt)
    else:
        final, err, log, run_id, note_path = _run_agent(sch, prompt)

    ok = not err and bool((final or "").strip())
    result = final if ok else (err or "no output")
    value = _extract_number(final) if (ok and sch.get("track_number")) else None
    storage.add_schedule_run(sid, ok, result, value, log=log, run_id=run_id,
                             note_path=note_path)
    now = time.time()
    storage.update_schedule(sid, {
        "last_run": now, "last_result": result[:2000],
        "next_run": now + max(60, int(sch["interval_seconds"]))})

    # Notify on finish if the schedule opted in (agents can also notify
    # mid-task with the notify tool). Failures never break the run.
    if sch.get("notify"):
        try:
            import notifications
            head = f"⏰ {sch['name']}" if ok else f"⚠️ {sch['name']} failed"
            # Prefer linking straight to the saved knowledge note when there is
            # one — that's the thing the user most wants to read.
            if note_path:
                link = f"#/knowledge/{quote(note_path, safe='')}"
            elif run_id:
                link = f"#/run/{run_id}"
            else:
                link = "#/schedules"
            notifications.send(head, result[:400], level="normal" if ok else "critical",
                               source="schedule", link=link)
        except Exception:  # noqa: BLE001
            pass
    return {"ok": ok, "error": err, "result": result, "value": value,
            "run_id": run_id, "note_path": note_path}


def _due():
    now = time.time()
    return [s for s in storage.list_schedules()
            if s["enabled"] and (s["next_run"] is None or s["next_run"] <= now)]


def _loop():
    # Small startup delay so model providers finish coming up first.
    time.sleep(8)
    while True:
        try:
            for s in _due():
                run_schedule(s["id"])   # serial by design
        except Exception:  # noqa: BLE001 - the scheduler thread must never die
            pass
        time.sleep(_TICK)


def start():
    """Start the single scheduler thread (idempotent)."""
    global _started
    with _lock:
        if _started:
            return
        _started = True
    threading.Thread(target=_loop, daemon=True, name="scheduler").start()
