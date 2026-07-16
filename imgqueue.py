"""Durable image job queue.

Images take minutes on a modest GPU, so the UI must not block on them. Jobs are
queued here and executed by ONE background worker — serial on purpose: the GPU
can only diffuse one image at a time, and running two would just thrash (the
same lesson the LLM concurrency cap taught us).

DURABILITY MATTERS HERE. Jobs are persisted to SQLite, because this app restarts
on every rebuild and a 6-minute job must not vanish with it. Better still: the
Fooocus job id is stored as soon as Fooocus accepts the work, so after a restart
we RESUME POLLING an in-flight job and still collect its image — Fooocus keeps
the result. (Without this, a restart silently threw away finished GPU work: the
image was generated but never saved.)

Every finished image is archived as a note in the knowledge vault so the prompt
assistant can learn from prompts that actually worked (see imgprompt.py).
"""
import threading
import time
import uuid

import imagegen
import storage

_lock = threading.Lock()
_wake = threading.Condition(_lock)
_worker = None
_started = False


def _public(j: dict) -> dict:
    p = j.get("params") or {}
    return {"id": j["id"], "kind": j["kind"], "status": j["status"],
            "images": j["images"], "error": j["error"],
            "created": j["created"], "started": j["started"],
            "finished": j["finished"],
            "prompt": (p.get("prompt") or "").strip(), "mode": p.get("mode")}


def _ensure_worker():
    global _worker
    if _worker and _worker.is_alive():
        return
    _worker = threading.Thread(target=_run_worker, daemon=True, name="image-queue")
    _worker.start()


def start():
    """Called once at app startup: recover jobs left behind by a restart."""
    global _started
    if _started:
        return
    _started = True
    for j in storage.list_image_jobs():
        if j["status"] != "running":
            continue
        if j["backend_job_id"]:
            # Fooocus may well have finished it while we were down — go collect.
            threading.Thread(target=_resume, args=(j,), daemon=True,
                             name=f"image-resume-{j['id']}").start()
        else:
            storage.update_image_job(
                j["id"], status="error", finished=time.time(),
                error="interrupted by an app restart before the image server "
                      "accepted the job — re-queue it")
    _ensure_worker()


def _resume(job: dict):
    """Re-attach to a Fooocus job that was in flight when the app restarted."""
    meta = _meta_for(job)
    res = imagegen.resume_job(job["backend_job_id"], meta)
    _finish(job["id"], job["kind"], job["params"], res)


def add(kind: str, params: dict, count: int = 1) -> dict:
    """Queue `count` copies of a job. kind: 'generate' | 'modify'."""
    if kind not in ("generate", "modify"):
        return {"ok": False, "error": "kind must be 'generate' or 'modify'", "ids": []}
    try:
        count = max(1, min(10, int(count)))
    except (TypeError, ValueError):
        count = 1

    ids = []
    for _ in range(count):
        jid = uuid.uuid4().hex[:10]
        storage.create_image_job(jid, kind, dict(params or {}))
        ids.append(jid)
    with _lock:
        _wake.notify()
    _ensure_worker()
    return {"ok": True, "ids": ids, "error": None}


def cancel(job_id: str) -> dict:
    """Cancel a job that hasn't started. A running job can't be interrupted —
    Fooocus has no cancel API and killing it would take the whole server down."""
    job = next((j for j in storage.list_image_jobs() if j["id"] == job_id), None)
    if not job:
        return {"ok": False, "error": "not found"}
    if job["status"] == "queued":
        storage.update_image_job(job_id, status="cancelled", finished=time.time())
        return {"ok": True, "error": None}
    if job["status"] == "running":
        return {"ok": False, "error": "already generating — it cannot be interrupted"}
    return {"ok": False, "error": f"job is {job['status']}"}


def clear_finished() -> dict:
    storage.delete_finished_image_jobs()
    return {"ok": True}


def status() -> dict:
    jobs = storage.list_image_jobs()
    return {
        "jobs": [_public(j) for j in jobs],
        "pending": sum(1 for j in jobs if j["status"] == "queued"),
        "running": any(j["status"] == "running" for j in jobs),
    }


def _meta_for(job: dict) -> dict:
    p = job.get("params") or {}
    return {"prompt": p.get("prompt", ""), "negative": p.get("negative", ""),
            "performance": p.get("performance"), "aspect": p.get("aspect"),
            "mode": p.get("mode") if job["kind"] == "modify" else None,
            "loras": p.get("loras") or [], "created": time.time()}


def _archive(kind: str, params: dict, images: list):
    """Save a successful prompt to the knowledge vault. Best effort: a failure
    here must never lose the image."""
    try:
        import knowledge
        prompt = (params.get("prompt") or "").strip()
        if not prompt:
            return
        loras = ", ".join(f"{l.get('file_name')}@{l.get('weight')}"
                          for l in (params.get("loras") or []) if isinstance(l, dict))
        body = (
            f"**Prompt**\n\n```\n{prompt}\n```\n\n"
            + (f"**Negative**\n\n```\n{params.get('negative')}\n```\n\n"
               if params.get("negative") else "")
            + f"- Mode: {kind}"
            + (f" / {params.get('mode')}" if params.get("mode") else "") + "\n"
            + f"- Performance: {params.get('performance') or 'default'}\n"
            + (f"- Aspect: {params.get('aspect')}\n" if params.get("aspect") else "")
            + (f"- LoRAs: {loras}\n" if loras else "")
            + f"- Image: `{', '.join(images)}`\n"
        )
        knowledge.write_note(
            f"Image prompt: {prompt[:60]}", body, tags=["image-prompt"],
            meta_extra={"source": "image-generation", "images": ",".join(images)},
            subdir="image-prompts")
    except Exception:  # noqa: BLE001
        pass


def _finish(job_id: str, kind: str, params: dict, res: dict):
    if res.get("ok"):
        images = res.get("images") or []
        storage.update_image_job(job_id, status="done", images=images,
                                 error=None, finished=time.time())
        _archive(kind, params, images)
    else:
        storage.update_image_job(job_id, status="error", error=res.get("error"),
                                 finished=time.time())


def _next_queued():
    """The next job to run — but only when nothing is in flight.

    Serial by design (one GPU). This also covers resumed jobs: after a restart
    a recovered job is 'running' in its own thread, and the worker must not
    start another one alongside it.
    """
    jobs = storage.list_image_jobs()
    if any(j["status"] == "running" for j in jobs):
        return None
    queued = [j for j in jobs if j["status"] == "queued"]
    if not queued:
        return None
    queued.sort(key=lambda j: j["created"])   # FIFO
    return queued[0]


def _run_worker():
    while True:
        job = _next_queued()
        if not job:
            with _lock:
                _wake.wait(timeout=5)   # re-check (a running job may finish)
            continue

        jid, kind, params = job["id"], job["kind"], job["params"]
        storage.update_image_job(jid, status="running", started=time.time())
        on_job_id = lambda bid, _jid=jid: storage.update_image_job(_jid,
                                                                   backend_job_id=bid)
        try:
            if kind == "generate":
                res = imagegen.generate(
                    params.get("prompt", ""), negative=params.get("negative", ""),
                    aspect=params.get("aspect") or "1152*896",
                    performance=params.get("performance"),
                    loras=params.get("loras"), styles=params.get("styles"),
                    on_job_id=on_job_id)
            else:
                res = imagegen.modify(
                    params.get("image") or params.get("source") or "",
                    mode=params.get("mode") or "vary_strong",
                    prompt=params.get("prompt", ""),
                    negative=params.get("negative", ""),
                    performance=params.get("performance"),
                    loras=params.get("loras"),
                    weight=params.get("weight", 0.6),
                    stop=params.get("stop", 0.5),
                    outpaint=params.get("outpaint"),
                    mask=params.get("mask"),
                    aspect=params.get("aspect") or "1152*896",
                    on_job_id=on_job_id)
        except Exception as e:  # noqa: BLE001 - the worker must never die
            res = {"ok": False, "images": [], "error": f"{type(e).__name__}: {e}"}

        _finish(jid, kind, params, res)
