"""Expert consensus (FantasyPros ECR via DynastyProcess, free) mapped onto Sleeper players.

Expert-implied points E: take a player's consensus positional rank r and use the
r-th highest Sleeper projection at that position this week. A consensus WR12 gets
the 12th-best WR projection. That turns ranks into points on the same scale as
Sleeper's projections, so the two can be blended:

    score = P + w * (E - P)      (w = 0: Sleeper only, w = 1: experts only)

Note: the free weekly file ranks RB/WR/TE in full PPR. Within one position the
order differs little from half-PPR, and points still come from Sleeper in your
league's scoring.
"""

from __future__ import annotations

import csv
import io
import re
import unicodedata
import urllib.request

WEEKLY_URL = "https://raw.githubusercontent.com/dynastyprocess/data/master/files/fp_latest_weekly.csv"
IDS_URL = "https://raw.githubusercontent.com/dynastyprocess/data/master/files/db_playerids.csv"
POSITIONS = ("QB", "RB", "WR", "TE")
TEAM_FIX = {"JAC": "JAX", "LA": "LAR", "WSH": "WAS"}


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def norm_name(name: str) -> str:
    """'D.J. Moore Jr.' -> 'djmoore'; for fallback matching only."""
    s = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode().lower()
    s = re.sub(r"\b(jr|sr|ii|iii|iv|v)\b\.?", "", s)
    return re.sub(r"[^a-z]", "", s)


def parse_ecr(csv_text: str) -> list[dict]:
    """Rows for QB/RB/WR/TE with a positional rank."""
    out = []
    for r in csv.DictReader(io.StringIO(csv_text)):
        pos = r.get("page_pos") or r.get("pos")
        if pos not in POSITIONS:
            continue
        m = re.search(r"(\d+)$", r.get("pos_rank") or "")
        rank = int(m.group(1)) if m else int(_num(r.get("rank")) or 0)
        if rank <= 0:
            continue
        out.append({
            "fp_id": str(r.get("fantasypros_id") or "").strip(),
            "name": r.get("player_name") or "",
            "pos": pos,
            "team": TEAM_FIX.get(r.get("team") or "", r.get("team") or ""),
            "opponent": TEAM_FIX.get(r.get("player_opponent_id") or "", r.get("player_opponent_id") or ""),
            "rank": rank,
            "ecr": _num(r.get("ecr")),
            "sd": _num(r.get("sd")),
            "best": _num(r.get("best")),
            "worst": _num(r.get("worst")),
            "scrape_date": r.get("scrape_date"),
        })
    return out


def parse_id_map(csv_text: str) -> dict[str, str]:
    """fantasypros_id -> sleeper_id."""
    out = {}
    for r in csv.DictReader(io.StringIO(csv_text)):
        fp, sl = (r.get("fantasypros_id") or "").strip(), (r.get("sleeper_id") or "").strip()
        if fp and sl and fp != "NA" and sl != "NA":
            out[fp] = sl
    return out


def map_to_sleeper(ecr: list[dict], id_map: dict[str, str], players: dict[str, dict]) -> dict[str, dict]:
    """{sleeper_id: consensus row}. ID crosswalk first, then name + position."""
    by_name: dict[tuple, str] = {}
    for pid, p in players.items():
        if p.get("position") in POSITIONS:
            nm = norm_name(p.get("full_name") or f"{p.get('first_name', '')} {p.get('last_name', '')}")
            by_name.setdefault((nm, p["position"]), pid)
    out: dict[str, dict] = {}
    for row in ecr:
        pid = id_map.get(row["fp_id"]) or by_name.get((norm_name(row["name"]), row["pos"]))
        if pid and (pid not in out or row["rank"] < out[pid]["rank"]):
            out[pid] = row
    return out


def matches_week(ecr: list[dict], games: dict[str, dict], min_share: float = 0.8) -> bool:
    """True if the snapshot's opponents match this week's schedule (guards against a stale file)."""
    checked = ok = 0
    for r in ecr:
        g = games.get(r["team"])
        if not g or not r["opponent"] or r["opponent"] == "NA":
            continue
        checked += 1
        ok += g["opponent"] == r["opponent"]
    return checked >= 20 and ok / checked >= min_share


def expert_points(consensus: dict[str, dict], proj_pts: dict[str, float], positions: dict[str, str]) -> dict[str, float]:
    """{sleeper_id: E}. Players the experts don't rank get 0."""
    ladder: dict[str, list[float]] = {}
    for pid, pts in proj_pts.items():
        pos = positions.get(pid)
        if pos in POSITIONS and isinstance(pts, (int, float)):
            ladder.setdefault(pos, []).append(float(pts))
    for pos in ladder:
        ladder[pos].sort(reverse=True)
    out = {}
    for pid, row in consensus.items():
        lad = ladder.get(row["pos"], [])
        out[pid] = round(lad[row["rank"] - 1], 2) if 0 < row["rank"] <= len(lad) else 0.0
    return out


def blend(p: float | None, e: float | None, w: float) -> float:
    p = float(p) if isinstance(p, (int, float)) else 0.0
    if e is None:
        return p
    return round(p + w * (float(e) - p), 2)


def fetch(url: str, timeout: int = 60) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "sitstart/0.3"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8")
