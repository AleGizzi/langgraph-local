"""Notifications: store every notification in the DB (so the in-app bell is
reliable) and ALSO try to raise a real desktop notification via notify-send on
the user's session (Pop!_OS / GNOME). Desktop delivery is best-effort — it
needs a graphical session (DISPLAY / DBUS), which exists when the app is run
from the desktop but may not under a headless service; the stored copy is the
fallback either way.
"""
import os
import shutil
import subprocess

import storage

_LEVELS = {"low": "low", "normal": "normal", "critical": "critical"}


def _desktop_notify(title: str, body: str, level: str):
    exe = shutil.which("notify-send")
    if not exe:
        return
    try:
        subprocess.run(
            [exe, "-a", "Agent Studio", "-u", _LEVELS.get(level, "normal"),
             "-i", "dialog-information", title, body[:400]],
            timeout=5, check=False,
            env={**os.environ, "DISPLAY": os.environ.get("DISPLAY", ":0")})
    except Exception:  # noqa: BLE001 - never let a notification failure matter
        pass


def send(title: str, body: str = "", level: str = "normal",
         source: str = None, link: str = None) -> int:
    """Record a notification and fire the desktop popup. Returns its id."""
    nid = storage.add_notification({"title": title, "body": body, "level": level,
                                    "source": source, "link": link})
    _desktop_notify(title, body, level)
    return nid
