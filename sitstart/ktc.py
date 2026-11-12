"""KeepTradeCut dynasty values (unofficial: read from the public rankings page).

KTC has no API. Its rankings page embeds every player and pick as JSON in
<script type="application/json" id="ktc-players">. We read the plain (no TE premium)
Superflex or 1QB value. KTC values are crowdsourced "keep / trade / cut" votes, while
FantasyCalc's come from real trades, so the two are complementary.

Fetched once per run, for personal use. If the page changes, the app falls back to
FantasyCalc alone and says so.
"""

from __future__ import annotations

import json
import re
import urllib.request

KTC_URL = "https://keeptradecut.com/dynasty-rankings?page=0&filters=QB|WR|RB|TE|RDP&format={fmt}"
POSITIONS = ("QB", "RB", "WR", "TE")
_PICK = re.compile(r"^(\d{4})\s+(Early|Mid|Late)\s+(1st|2nd|3rd|4th)$")


def fetch_html(superflex: bool, timeout: int = 60) -> str:
    url = KTC_URL.format(fmt=2 if superflex else 1)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (sitstart; personal dynasty helper)"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def parse(html: str, superflex: bool = True) -> list[dict]:
    """[{"name", "pos", "team", "age", "mflid", "value", "pick_label"}] (pick_label in FantasyCalc style)."""
    m = re.search(r'<script[^>]*id="ktc-players"[^>]*>(.*?)</script>', html, re.S)
    if not m:
        raise ValueError("KTC page layout changed: player data block not found")
    rows = json.loads(m.group(1))
    key = "superflexValues" if superflex else "oneQBValues"
    out = []
    for r in rows:
        vals = r.get(key) or {}
        value = vals.get("value")
        if not isinstance(value, (int, float)) or value <= 0:
            continue
        pos = r.get("position")
        if pos == "RDP":
            pm = _PICK.match((r.get("playerName") or "").strip())
            if not pm:
                continue
            season, tier, rnd = pm.groups()
            out.append({"name": r["playerName"], "pos": "PICK", "value": float(value),
                        "pick_label": f"{season} {rnd} ({tier})", "season": season, "round_word": rnd, "tier": tier})
            continue
        if pos not in POSITIONS:
            continue
        out.append({"name": r.get("playerName"), "pos": pos, "team": r.get("team"), "age": r.get("age"),
                    "mflid": str(r.get("mflid") or "") or None, "value": float(value), "pick_label": None})
    return out
