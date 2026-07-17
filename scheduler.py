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

import storage

_TICK = int(os.environ.get("SCHEDULER_TICK", "20"))   # seconds between wakeups
_lock = threading.Lock()
_started = False

_WORKSPACE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "workspaces", "scheduler")

# First standalone number in a string: "1.234,56", "$1234.5", "1,234.56", "42%".
_NUM_RE = re.compile(r"-?\d[\d.,]*\d|-?\d")


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


def run_schedule(sid: int) -> dict:
    """Run one schedule NOW (also used by the 'run now' button). Never raises."""
    import engine
    sch = storage.get_schedule(sid)
    if not sch:
        return {"ok": False, "error": "no such schedule"}
    os.makedirs(_WORKSPACE, exist_ok=True)
    agent = dict(sch["agent"] or {})
    agent.setdefault("provider", "ollama")
    # If the task appends to a knowledge folder, the agent needs the tool + a
    # nudge; we add it non-destructively.
    if sch.get("knowledge_folder"):
        tools = list(agent.get("tools") or [])
        if "knowledge" not in tools:
            tools.append("knowledge")
        agent["tools"] = tools

    try:
        skill_map = {s["name"]: s for s in storage.list_skills()}
    except Exception:  # noqa: BLE001
        skill_map = {}

    prompt = sch["prompt"]
    if sch.get("knowledge_folder"):
        prompt += (f"\n\nWhen done, save your finding as a knowledge note in the "
                   f"folder '{sch['knowledge_folder']}' using the knowledge tool, "
                   "with today's date, so it accumulates over time.")

    final, err = "", None
    try:
        for ev in engine.chat_stream(agent, [{"role": "user", "content": prompt}],
                                     _WORKSPACE, skill_map):
            if ev.get("type") == "done":
                final = ev.get("content") or final
            elif ev.get("type") == "error":
                err = ev.get("content")
    except Exception as e:  # noqa: BLE001 - a scheduled run must never crash the loop
        err = f"{type(e).__name__}: {e}"

    ok = not err and bool(final.strip())
    result = final if ok else (err or "no output")
    value = _extract_number(final) if (ok and sch.get("track_number")) else None
    storage.add_schedule_run(sid, ok, result, value)
    now = time.time()
    storage.update_schedule(sid, {
        "last_run": now, "last_result": result[:2000],
        "next_run": now + max(60, int(sch["interval_seconds"]))})
    return {"ok": ok, "error": err, "result": result, "value": value}


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
