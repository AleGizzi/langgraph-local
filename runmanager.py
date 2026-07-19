"""Run manager: executes team runs in background threads and fans out
events to any number of SSE subscribers, while persisting the durable
events (everything except raw tokens) to SQLite.
"""
import os
import queue
import threading
import traceback

import storage
from engine import RunCancelled, TeamRunner

WORKSPACES = os.environ.get(
    "AGENTS_WORKSPACES",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "workspaces"),
)

# Event types that are persisted for history/replay. Tokens are live-only.
PERSISTED = {"run_start", "agent_start", "agent_end", "tool_call", "tool_result",
             "decision", "artifact", "run_end", "error"}

_SENTINEL = object()


class ActiveRun:
    def __init__(self, run_id: int):
        self.run_id = run_id
        self.subscribers = []
        self.lock = threading.Lock()
        self.cancel_event = threading.Event()
        self.seq = 0
        self.done = False

    def subscribe(self) -> queue.Queue:
        q = queue.Queue(maxsize=10000)
        with self.lock:
            if self.done:
                return None
            self.subscribers.append(q)
        return q

    def unsubscribe(self, q):
        with self.lock:
            if q in self.subscribers:
                self.subscribers.remove(q)

    def publish(self, event: dict):
        with self.lock:
            subs = list(self.subscribers)
        for q in subs:
            try:
                q.put_nowait(event)
            except queue.Full:
                pass

    def close(self):
        with self.lock:
            self.done = True
            subs = list(self.subscribers)
            self.subscribers = []
        for q in subs:
            try:
                q.put_nowait(_SENTINEL)
            except queue.Full:
                pass


class RunManager:
    def __init__(self):
        self._runs = {}
        self._lock = threading.Lock()

    def get(self, run_id: int) -> ActiveRun:
        with self._lock:
            return self._runs.get(run_id)

    def start(self, team: dict, task: str, mode: str = "balanced",
              unattended: bool = False, allow_destructive: bool = False) -> int:
        run_id = storage.create_run(team["id"], team["name"], task)
        active = ActiveRun(run_id)
        with self._lock:
            self._runs[run_id] = active
        t = threading.Thread(
            target=self._execute,
            args=(active, team, task, mode, unattended, allow_destructive),
            daemon=True, name=f"run-{run_id}")
        t.start()
        return run_id

    def stop(self, run_id: int) -> bool:
        active = self.get(run_id)
        if active and not active.done:
            active.cancel_event.set()
            return True
        return False

    def _execute(self, active: ActiveRun, team: dict, task: str,
                 mode: str = "balanced", unattended: bool = False,
                 allow_destructive: bool = False):
        run_id = active.run_id
        workspace = os.path.join(WORKSPACES, str(run_id))
        os.makedirs(workspace, exist_ok=True)

        def emit(etype: str, agent: str = None, content: str = None, meta: dict = None):
            active.seq += 1
            event = {"seq": active.seq, "type": etype, "agent": agent,
                     "content": content, "meta": meta}
            if etype in PERSISTED:
                storage.add_event(run_id, active.seq, etype, agent, content, meta)
            active.publish(event)

        try:
            concurrency = 1
            if team.get("settings", {}).get("parallel"):
                try:
                    import sysinfo
                    concurrency = sysinfo.assess()["parallel"]["capacity"]
                except Exception:  # noqa: BLE001 - fall back to serial
                    concurrency = 1
            # Run mode shifts each agent's model along its family size ladder.
            # Apply to a copy so the stored team is never mutated.
            if mode and mode != "balanced":
                try:
                    import modes
                    import providers
                    team = modes.apply_mode(team, mode, providers.list_models())
                except Exception:  # noqa: BLE001 - fall back to as-authored
                    pass
            emit("run_start", content=task,
                 meta={"team": team["name"], "topology": team.get("topology"),
                       "concurrency": concurrency, "mode": mode})
            runner = TeamRunner(team, task, workspace, emit, active.cancel_event,
                                max_concurrency=concurrency, run_id=run_id, mode=mode,
                                unattended=unattended, allow_destructive=allow_destructive)
            final = runner.run()
            # Save the deliverable as an artifact automatically.
            try:
                with open(os.path.join(workspace, "final_output.md"), "w",
                          encoding="utf-8") as f:
                    f.write(final or "")
            except OSError:
                pass
            # Archive the deliverable into the shared knowledge vault so future
            # runs (and Obsidian/Logseq) can reference it.
            note_path = None
            try:
                import knowledge
                note_path = knowledge.export_run(run_id, team["name"], task, final) or None
            except Exception:  # noqa: BLE001 - knowledge export is best-effort
                pass
            storage.finish_run(run_id, "done", final=final)
            emit("run_end", content=final,
                 meta={"status": "done", "knowledge_note": note_path})
        except RunCancelled:
            storage.finish_run(run_id, "cancelled", error="Stopped by user")
            emit("run_end", content="", meta={"status": "cancelled"})
        except Exception as e:  # noqa: BLE001
            err = f"{type(e).__name__}: {e}"
            traceback.print_exc()
            storage.finish_run(run_id, "error", error=err)
            emit("error", content=err)
            emit("run_end", content="", meta={"status": "error"})
        finally:
            active.close()
            with self._lock:
                self._runs.pop(run_id, None)


manager = RunManager()
