"""Phone alerts through ntfy.sh, sent only when something actionable changes.

Install the free ntfy app, subscribe to your private topic name, and the
pipeline posts there. Anyone who knows the topic name can read it, so keep it
in a GitHub secret, never in the code.
"""

from __future__ import annotations

import urllib.request

NTFY_SERVER = "https://ntfy.sh"


def _key(snap: dict | None) -> tuple:
    if not snap:
        return ()
    sug = snap.get("suggestion") or {}
    start = tuple(sorted(c["player_id"] for c in sug.get("start", []))) if sug.get("actionable") else ()
    sit = tuple(sorted(c["player_id"] for c in sug.get("sit", []))) if sug.get("actionable") else ()
    flags = tuple(sorted((r["player"] or {}).get("player_id", r["slot"]) + ":" + r["flag"]
                         for r in snap.get("lineup", []) if r.get("flag")))
    return (snap.get("week"), start, sit, flags)


def build_alert(snap: dict, previous: dict | None) -> tuple[str, str] | None:
    """(title, message) if this run should alert, else None."""
    if previous is not None and _key(snap) == _key(previous):
        return None
    week = snap.get("week")
    lines = []
    for r in snap.get("lineup", []):
        if r.get("flag"):
            who = r["player"]["name"] if r.get("player") else f"{r['slot']} slot"
            what = r["flag"].replace("STARTER_", "").replace("_", " ").lower()
            lines.append(f"{who}: {what}")
    sug = snap.get("suggestion") or {}
    if sug.get("actionable"):
        starts = ", ".join(c["name"] for c in sug["start"])
        sits = ", ".join(c["name"] for c in sug["sit"])
        gain = f" (+{sug['gain']:.1f})" if sug.get("gain", 0) > 0.05 else ""
        lines.insert(0, f"Start {starts} over {sits}{gain}" if sits else f"Start {starts}{gain}")
        title = f"Week {week}: lineup change suggested"
    elif lines:
        title = f"Week {week}: lineup warning"
    else:
        title = f"Week {week}: lineup is set"
        lines.append("No changes beat your current lineup.")
    return title, "\n".join(lines)


def send(topic: str, title: str, message: str, click_url: str | None = None, server: str = NTFY_SERVER) -> None:
    headers = {"Title": title.encode("ascii", "ignore").decode(), "Tags": "football"}
    if click_url:
        headers["Click"] = click_url
    req = urllib.request.Request(f"{server.rstrip('/')}/{topic}", data=message.encode("utf-8"),
                                 headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=20):
        pass
