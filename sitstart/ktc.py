"""KeepTradeCut dynasty values (unofficial: read from the public rankings page).

KTC has no API. Until Nov 2026 its rankings page embedded every player and pick as JSON in
<script id="ktc-players">; now the page loads them from /dynasty-rankings/player-pool
(versioned by the page's `playersVersion`, needs the page's affinity cookie). We read
whichever is there. We use the plain (no TE premium) Superflex or 1QB value. KTC values are crowdsourced "keep / trade / cut" votes, while
FantasyCalc's come from real trades, so the two are complementary.

Fetched once per run, for personal use. If the page changes, the app falls back to
FantasyCalc alone and says so.
"""

from __future__ import annotations

import http.cookiejar
import json
import re
import urllib.request

KTC_BASE = "https://keeptradecut.com"
KTC_URL = KTC_BASE + "/dynasty-rankings?page=0&filters=QB|WR|RB|TE|RDP&format={fmt}"
POOL_PATH = "/dynasty-rankings/player-pool?v={version}&sr={rev}"
UA = {"User-Agent": "Mozilla/5.0 (sitstart; personal dynasty helper)"}
POSITIONS = ("QB", "RB", "WR", "TE")
_PICK = re.compile(r"^(\d{4})\s+(Early|Mid|Late)\s+(1st|2nd|3rd|4th)$")


def fetch_html(superflex: bool, timeout: int = 60) -> str:
    url = KTC_URL.format(fmt=2 if superflex else 1)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (sitstart; personal dynasty helper)"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def pool_url(html: str, loader_js: str = "") -> str:
    """The player-pool URL the rankings page would fetch."""
    m = re.search(r"playersVersion\s*=\s*'([^']+)'", html)
    if not m:
        raise ValueError("KTC page layout changed: no player data block or playersVersion")
    rev = re.search(r"KTC_DATA_CACHE_SCHEMA_REV\s*=\s*['\"]?([^'\";\s]+)", loader_js)
    return KTC_BASE + POOL_PATH.format(version=urllib.request.quote(m.group(1)), rev=rev.group(1) if rev else "2")


def fetch_rows(superflex: bool, timeout: int = 60) -> list[dict]:
    """Fetch and parse KTC values, from the embedded block or the player-pool endpoint."""
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def get(url):
        req = urllib.request.Request(url, headers={**UA, "Referer": KTC_BASE + "/dynasty-rankings"})
        with opener.open(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")

    html = get(KTC_URL.format(fmt=2 if superflex else 1))
    try:
        return parse(html, superflex)
    except ValueError:
        pass
    src = re.search(r'src="(/early/dataCache\.js[^"]*)"', html)
    loader = get(KTC_BASE + src.group(1)) if src else ""
    return parse_rows(json.loads(get(pool_url(html, loader))), superflex)


def parse(html: str, superflex: bool = True) -> list[dict]:
    """Old layout: values embedded in <script id="ktc-players">."""
    m = re.search(r'<script[^>]*id="ktc-players"[^>]*>(.*?)</script>', html, re.S)
    if not m:
        raise ValueError("KTC page layout changed: player data block not found")
    return parse_rows(json.loads(m.group(1)), superflex)


def parse_rows(rows: list[dict], superflex: bool = True) -> list[dict]:
    """[{"name", "pos", "team", "age", "mflid", "value", "pick_label"}] (pick_label in FantasyCalc style)."""
    if not isinstance(rows, list) or not rows:
        raise ValueError("KTC player pool was empty")
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
