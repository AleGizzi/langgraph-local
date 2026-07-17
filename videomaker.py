"""Video Maker: idea → LLM shot list → Fooocus stills → ffmpeg assembly.

Honest scope for this hardware: real video diffusion needs 8-24GB VRAM and this
machine has 4 — so this is NOT frame-by-frame generated video. It is the
feasible local pipeline: an LLM plans the shots, Fooocus renders one still per
shot, and ffmpeg (static binary from imageio-ffmpeg, no root needed) assembles
them with Ken Burns pan/zoom and crossfades into a real mp4.

A project is a JSON sidecar in data/videos/ plus the finished mp4. Stills ride
the existing image queue, so they get the same durability and GPU serialization
as every other image job.
"""
import json
import os
import re
import subprocess
import threading
import time

VIDEOS_DIR = os.environ.get(
    "AGENTS_VIDEOS",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "videos"))

FPS = 30
XFADE = 0.6          # crossfade seconds between shots
SIZE = "1280x720"

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _ensure():
    os.makedirs(VIDEOS_DIR, exist_ok=True)


def _slug(text: str) -> str:
    return _SLUG_RE.sub("-", (text or "video").lower()).strip("-")[:50] or "video"


def _ffmpeg() -> str:
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


# ---------------- shot planning (LLM) ----------------

_PLAN_PROMPT = """You are a storyboard director for a short slideshow-style video.

The user wants a video about:
{idea}

Write {n} shots. Each shot is ONE still image plus how long it stays on screen.
Image prompts must be rich, visual, self-contained descriptions for an image
generator (subject, setting, lighting, mood, style) — NOT instructions or
camera directions. Keep a consistent visual style across all shots.

Respond with ONLY this JSON, nothing else:
{{"shots": [{{"prompt": "<image generation prompt>", "seconds": <2-8>}}, …]}}"""


def plan_shots(idea: str, n: int = 5, provider: str = None, model: str = None) -> dict:
    """Ask a local model for a shot list. Defensive parse; never raises."""
    from providers import make_llm, list_models
    from help import pick_model
    n = max(2, min(12, int(n or 5)))
    if not model:
        provider, model = pick_model(list_models())
    if not model:
        return {"ok": False, "error": "no local model available", "shots": []}
    try:
        llm = make_llm(provider or "ollama", model,
                       {"temperature": 0.7, "num_predict": 1200})
        out = llm.invoke(_PLAN_PROMPT.format(idea=idea.strip()[:1500], n=n))
        text = out.content if isinstance(out.content, str) else str(out.content)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {e}", "shots": []}
    m = re.search(r"\{.*\}", text, re.DOTALL)
    shots = []
    if m:
        try:
            data = json.loads(re.sub(r",\s*([}\]])", r"\1", m.group(0)))
            for s in (data.get("shots") or [])[:12]:
                p = str(s.get("prompt", "")).strip()
                if not p:
                    continue
                try:
                    secs = max(2.0, min(8.0, float(s.get("seconds", 4))))
                except (TypeError, ValueError):
                    secs = 4.0
                shots.append({"prompt": p, "seconds": secs})
        except ValueError:
            pass
    if not shots:
        return {"ok": False, "error": "the model returned no usable shot list — "
                                      "try again or write shots by hand",
                "shots": []}
    return {"ok": True, "error": None, "shots": shots, "planner": model}


# ---------------- projects ----------------

def _path(pid: str) -> str:
    if not re.fullmatch(r"[a-z0-9-]+", pid or ""):
        raise ValueError("bad project id")
    return os.path.join(VIDEOS_DIR, f"{pid}.json")


def _load(pid: str) -> dict:
    with open(_path(pid), encoding="utf-8") as f:
        return json.load(f)


def _save(project: dict):
    _ensure()
    with open(_path(project["id"]), "w", encoding="utf-8") as f:
        json.dump(project, f, indent=2, ensure_ascii=False)


def create(title: str, shots: list, performance: str = None) -> dict:
    """Create a project and queue one still per shot on the image queue."""
    import imgqueue
    _ensure()
    clean = []
    for s in (shots or [])[:12]:
        p = str(s.get("prompt", "")).strip()
        if not p:
            continue
        try:
            secs = max(2.0, min(8.0, float(s.get("seconds", 4))))
        except (TypeError, ValueError):
            secs = 4.0
        clean.append({"prompt": p, "seconds": secs, "job_id": None, "image": None})
    if len(clean) < 2:
        return {"ok": False, "error": "a video needs at least 2 shots", "id": None}

    pid = _slug(title) or f"video-{int(time.time())}"
    if os.path.exists(_path(pid)):
        pid = f"{pid}-{int(time.time()) % 10000}"
    for s in clean:
        r = imgqueue.add("generate", {
            "prompt": s["prompt"],
            "negative": "text, watermark, low quality, deformed",
            "aspect": "1280*768",  # closest SDXL bucket to 16:9
            "performance": performance or "Extreme Speed",
        })
        s["job_id"] = (r.get("ids") or [None])[0]
    project = {"id": pid, "title": title.strip()[:120] or pid,
               "created": time.time(), "shots": clean,
               "status": "generating", "video": None, "error": None}
    _save(project)
    return {"ok": True, "error": None, "id": pid}


def _refresh_stills(project: dict) -> dict:
    """Pull finished job images into the project; update status."""
    import storage
    jobs = {j["id"]: j for j in storage.list_image_jobs()}
    waiting = 0
    for s in project["shots"]:
        if s["image"]:
            continue
        j = jobs.get(s["job_id"])
        if j and j["status"] == "done" and j.get("images"):
            s["image"] = j["images"][0]
        elif j and j["status"] in ("queued", "running"):
            waiting += 1
        elif j is None or j["status"] == "error":
            s["error"] = (j or {}).get("error") or "image job vanished"
    if project["status"] == "generating":
        if all(s.get("image") for s in project["shots"]):
            project["status"] = "ready"      # ready to assemble
        elif not waiting and not all(s.get("image") for s in project["shots"]):
            project["status"] = "error"
            project["error"] = "some stills failed — requeue or edit the shots"
    _save(project)
    return project


def list_projects() -> list:
    _ensure()
    out = []
    for fn in sorted(os.listdir(VIDEOS_DIR)):
        if not fn.endswith(".json"):
            continue
        try:
            p = _refresh_stills(_load(fn[:-5]))
            out.append(p)
        except (OSError, ValueError):
            continue
    out.sort(key=lambda p: -p["created"])
    return out


def delete(pid: str) -> dict:
    try:
        p = _load(pid)
    except (OSError, ValueError):
        return {"ok": False, "error": "no such project"}
    for target in (p.get("video"), f"{pid}.json"):
        if not target:
            continue
        full = os.path.join(VIDEOS_DIR, os.path.basename(target))
        try:
            os.remove(full)
        except OSError:
            pass
    return {"ok": True, "error": None}


# ---------------- assembly (ffmpeg) ----------------

def _build_command(project: dict, out_path: str) -> list:
    """One zoompan clip per still, chained xfade crossfades, H.264 mp4.

    Ken Burns alternates zoom-in / zoom-out per shot so the motion doesn't
    feel mechanical. All filter math uses frames (FPS constant).
    """
    from imagegen import IMAGES_DIR
    cmd = [_ffmpeg(), "-y"]
    shots = project["shots"]
    # Each still enters as ONE frame — zoompan's d=<frames> then generates the
    # whole clip from it. Feeding a looped stream instead multiplies frames
    # (d per input frame): the first cut of this code produced an 18-MINUTE
    # video from two 5s shots that way.
    for s in shots:
        cmd += ["-i", os.path.join(IMAGES_DIR, os.path.basename(s["image"]))]
    filters = []
    for i, s in enumerate(shots):
        frames = int(round((s["seconds"] + XFADE) * FPS))
        if i % 2 == 0:  # zoom in
            zoom = "min(zoom+0.0009,1.12)"
        else:           # start zoomed, drift out
            zoom = "max(1.12-0.0009*on,1.0)"
        # 2560px supersample hides zoompan's pixel jitter at 720p; the classic
        # 8000px trick took 10+ CPU-minutes for an 11s video on this machine.
        filters.append(
            f"[{i}:v]scale=2560:-1,zoompan=z='{zoom}':x='iw/2-(iw/zoom/2)':"
            f"y='ih/2-(ih/zoom/2)':d={frames}:s={SIZE}:fps={FPS},"
            f"setsar=1[v{i}]")
    # chain crossfades: v0 xfade v1 -> x1; x1 xfade v2 -> x2; ...
    prev = "v0"
    offset = shots[0]["seconds"]
    for i in range(1, len(shots)):
        filters.append(
            f"[{prev}][v{i}]xfade=transition=fade:duration={XFADE}:"
            f"offset={offset:.3f}[x{i}]")
        prev = f"x{i}"
        offset += shots[i]["seconds"]
    # players (and Chrome) want 4:2:0 — without this the xfade chain output
    # encodes as yuv444p High 4:4:4, which many decoders refuse.
    filters.append(f"[{prev}]format=yuv420p[vout]")
    cmd += ["-filter_complex", ";".join(filters), "-map", "[vout]",
            "-r", str(FPS),
            "-c:v", "libx264", "-preset", "medium", "-crf", "20",
            "-movflags", "+faststart", out_path]
    return cmd


def assemble(pid: str) -> dict:
    """Assemble in a background thread; project.status tracks progress."""
    try:
        project = _refresh_stills(_load(pid))
    except (OSError, ValueError):
        return {"ok": False, "error": "no such project"}
    if project["status"] == "assembling":
        return {"ok": True, "error": None}
    if not all(s.get("image") for s in project["shots"]):
        return {"ok": False, "error": "stills are not finished yet"}
    project["status"] = "assembling"
    project["error"] = None
    _save(project)

    def work():
        out_path = os.path.join(VIDEOS_DIR, f"{pid}.mp4")
        try:
            cmd = _build_command(project, out_path)
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
            fresh = _load(pid)
            if p.returncode == 0 and os.path.getsize(out_path) > 10000:
                fresh["status"] = "done"
                fresh["video"] = f"{pid}.mp4"
            else:
                fresh["status"] = "error"
                fresh["error"] = "ffmpeg failed: " + (p.stderr or "")[-400:]
            _save(fresh)
        except Exception as e:  # noqa: BLE001 - worker must not die silently
            try:
                fresh = _load(pid)
                fresh["status"] = "error"
                fresh["error"] = f"{type(e).__name__}: {e}"
                _save(fresh)
            except (OSError, ValueError):
                pass

    threading.Thread(target=work, daemon=True, name=f"video-{pid}").start()
    return {"ok": True, "error": None}
