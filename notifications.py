"""Notifications: store every notification in the DB (so the in-app bell is
reliable) and ALSO try to raise a real desktop notification via notify-send on
the user's session (Pop!_OS / GNOME / COSMIC). Desktop delivery is best-effort —
it needs a graphical session (DISPLAY / DBUS), which exists when the app is run
from the desktop but may not under a headless service; the stored copy is the
fallback either way.

When a notification carries a `link` (a hash route like `#/knowledge/…`), the
desktop popup gets a clickable "Open" action that launches the app at that route
in the browser. That needs a notification daemon supporting actions
(notify-send -A); if it doesn't, the popup still shows without the button, and
the in-app bell entry stays clickable regardless.
"""
import os
import shlex
import shutil
import subprocess

import storage

_LEVELS = {"low": "low", "normal": "normal", "critical": "critical"}


def _app_url(link: str) -> str:
    """Turn a stored notification link into a full URL the browser can open.

    Links are hash routes (`#/knowledge/…`, `#/run/12`); some may already be
    absolute. Host/port match how the app is served (PORT env, default 5860)."""
    if not link:
        return ""
    if link.startswith("http://") or link.startswith("https://"):
        return link
    host = os.environ.get("AGENTS_PUBLIC_HOST", "127.0.0.1")
    port = os.environ.get("PORT", "5860")
    return f"http://{host}:{port}/{link.lstrip('/')}"


def _desktop_notify(title: str, body: str, level: str, link: str = None):
    exe = shutil.which("notify-send")
    if not exe:
        return
    env = {**os.environ, "DISPLAY": os.environ.get("DISPLAY", ":0")}
    urg = _LEVELS.get(level, "normal")
    body = (body or "")[:400]
    url = _app_url(link)
    opener = shutil.which("xdg-open") or shutil.which("gio")

    if not (url and opener):
        # Plain, non-clickable popup (no link, or no way to open a browser).
        try:
            subprocess.run(
                [exe, "-a", "Agent Studio", "-u", urg, "-i", "dialog-information",
                 title, body],
                timeout=5, check=False, env=env)
        except Exception:  # noqa: BLE001 - never let a notification failure matter
            pass
        return

    # Clickable popup: -A adds an action button and makes notify-send WAIT for
    # the user, printing the chosen action's name. Run it detached
    # (start_new_session) so that wait never blocks the caller (a scheduler
    # thread); when the action fires, open the note in the browser. `gio open`
    # and `xdg-open` both take the URL as the final argument.
    q = shlex.quote
    script = (
        f'act=$({q(exe)} -a "Agent Studio" -u {q(urg)} -i dialog-information '
        f'-A open="📄 Open note" {q(title)} {q(body)} 2>/dev/null); '
        f'if [ -n "$act" ]; then {q(opener)} {q(url)} >/dev/null 2>&1; fi'
    )
    try:
        subprocess.Popen(
            ["bash", "-c", script], env=env, start_new_session=True,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:  # noqa: BLE001
        pass


def send(title: str, body: str = "", level: str = "normal",
         source: str = None, link: str = None) -> int:
    """Record a notification and fire the desktop popup. Returns its id."""
    nid = storage.add_notification({"title": title, "body": body, "level": level,
                                    "source": source, "link": link})
    _desktop_notify(title, body, level, link)
    return nid
