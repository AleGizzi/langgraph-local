"""Local dictation: transcribe a short audio clip with faster-whisper.

Fully local — the browser records the clip (getUserMedia/MediaRecorder, no cloud)
and posts it here; we transcribe it on-device. This project's venv doesn't ship
faster-whisper, but the sibling whisper-flow-local project already has it plus a
cached model, so we shell out to that interpreter rather than adding a heavy
dependency here. Override with WHISPER_PYTHON / WHISPER_MODEL if you want.
"""
import os
import subprocess
import sys

_MODEL = os.environ.get("WHISPER_MODEL", "base")
_CANDIDATES = [
    os.environ.get("WHISPER_PYTHON") or "",
    sys.executable,  # this venv, if faster-whisper ever gets installed here
    os.path.expanduser("~/whisper-flow-local/.venv/bin/python"),
]

_SCRIPT = r"""
import sys
from faster_whisper import WhisperModel
model = WhisperModel(sys.argv[2], device="cpu", compute_type="int8")
segments, _ = model.transcribe(sys.argv[1], vad_filter=True)
print("".join(s.text for s in segments).strip())
"""


def _interpreter() -> str | None:
    """First interpreter that can import faster_whisper."""
    for py in _CANDIDATES:
        if not py or not os.path.isfile(py):
            continue
        try:
            r = subprocess.run([py, "-c", "import faster_whisper"],
                               capture_output=True, timeout=20)
            if r.returncode == 0:
                return py
        except Exception:  # noqa: BLE001 - try the next candidate
            continue
    return None


def available() -> bool:
    return _interpreter() is not None


def transcribe(audio_path: str) -> dict:
    """Return {ok, text, error}. Never raises."""
    py = _interpreter()
    if not py:
        return {"ok": False, "text": "",
                "error": "Local dictation needs faster-whisper. Install it in this "
                         "venv, or set WHISPER_PYTHON to an interpreter that has it "
                         "(the whisper-flow-local venv works)."}
    try:
        r = subprocess.run([py, "-c", _SCRIPT, audio_path, _MODEL],
                           capture_output=True, text=True, timeout=180)
    except subprocess.TimeoutExpired:
        return {"ok": False, "text": "", "error": "Transcription timed out."}
    if r.returncode != 0:
        return {"ok": False, "text": "",
                "error": (r.stderr or "transcription failed").strip()[-300:]}
    return {"ok": True, "text": (r.stdout or "").strip(), "error": None}
