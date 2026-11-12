"""Advanced-stats view (shadow mode): usage-based expected points x Vegas matchup.

Expected fantasy points (xFP) come from ffverse's ffopportunity model, which values
every target, carry and pass attempt by down, distance, field position and air yards.
xFP measures a player's role, which predicts next week better than his actual points:
it ignores touchdown luck. It's scored here with your league's settings.

    stat_pts  = recency-weighted xFP over his last 4 games  x  matchup factor
    matchup   = 1 + 0.5 x (team implied total / average implied total this week - 1)
    stat_adj  = stat_pts / score - 1, capped at +/-15%

Shadow mode: stat_adj is shown and logged but doesn't change recommendations until
the weekly report card shows it beats the main score.
"""

from __future__ import annotations

import csv
import io

EP_URL = "https://github.com/ffverse/ffopportunity/releases/download/latest-data/ep_weekly_{season}.csv"
POSITIONS = ("QB", "RB", "WR", "TE")
RECENCY_WEIGHTS = (0.4, 0.3, 0.2, 0.1)  # most recent game first
CAP = 0.15
MIN_GAMES = 2

# ffopportunity expected columns -> Sleeper scoring keys
EXP_TO_SCORING = {
    "pass_yards_gained_exp": "pass_yd",
    "pass_touchdown_exp": "pass_td",
    "pass_interception_exp": "pass_int",
    "pass_two_point_conv_exp": "pass_2pt",
    "rush_yards_gained_exp": "rush_yd",
    "rush_touchdown_exp": "rush_td",
    "rush_two_point_conv_exp": "rush_2pt",
    "receptions_exp": "rec",
    "rec_yards_gained_exp": "rec_yd",
    "rec_touchdown_exp": "rec_td",
    "rec_two_point_conv_exp": "rec_2pt",
}
REC_BONUS = {"TE": "bonus_rec_te", "RB": "bonus_rec_rb", "WR": "bonus_rec_wr"}


def _f(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def expected_points(row: dict, scoring: dict) -> float:
    pts = sum(_f(row.get(col)) * float(scoring.get(key, 0) or 0) for col, key in EXP_TO_SCORING.items())
    bonus = REC_BONUS.get(row.get("position") or "")
    if bonus and scoring.get(bonus):
        pts += _f(row.get("receptions_exp")) * float(scoring[bonus])
    return pts


def parse_ep(csv_text: str, scoring: dict) -> dict[str, list[tuple[int, float]]]:
    """{nfl_gsis_id: [(week, xFP in league scoring), ...]} for QB/RB/WR/TE, sorted by week."""
    out: dict[str, list[tuple[int, float]]] = {}
    for r in csv.DictReader(io.StringIO(csv_text)):
        if r.get("position") not in POSITIONS or not r.get("player_id"):
            continue
        try:
            wk = int(r["week"])
        except (KeyError, ValueError):
            continue
        out.setdefault(r["player_id"], []).append((wk, expected_points(r, scoring)))
    for v in out.values():
        v.sort()
    return out


def parse_gsis_map(ids_csv_text: str) -> dict[str, str]:
    """nfl gsis_id -> sleeper_id (from DynastyProcess db_playerids.csv)."""
    out = {}
    for r in csv.DictReader(io.StringIO(ids_csv_text)):
        g, s = (r.get("gsis_id") or "").strip(), (r.get("sleeper_id") or "").strip()
        if g and s and g != "NA" and s != "NA":
            out[g] = s
    return out


def recent_xfp(history: list[tuple[int, float]], before_week: int) -> tuple[float | None, int, float | None]:
    """(weighted xFP, games used, trend). Trend = last 2 games' avg minus the 2 before, in points."""
    games = [x for wk, x in history if wk < before_week][-len(RECENCY_WEIGHTS):][::-1]  # newest first
    if not games:
        return None, 0, None
    w = RECENCY_WEIGHTS[:len(games)]
    val = sum(g * wt for g, wt in zip(games, w)) / sum(w)
    trend = None
    if len(games) >= 4:
        trend = round((games[0] + games[1]) / 2 - (games[2] + games[3]) / 2, 1)
    return round(val, 2), len(games), trend


def matchup_factor(team: str | None, games: dict[str, dict]) -> float:
    totals = [g["implied_total"] for g in games.values() if isinstance(g.get("implied_total"), (int, float))]
    g = games.get(team or "")
    if not totals or not g or not isinstance(g.get("implied_total"), (int, float)):
        return 1.0
    avg = sum(totals) / len(totals)
    return round(1 + 0.5 * (g["implied_total"] / avg - 1), 3)


def stat_estimates(ep: dict[str, list[tuple[int, float]]], gsis_to_sleeper: dict[str, str], before_week: int,
                   games: dict[str, dict], players: dict[str, dict]) -> dict[str, dict]:
    """{sleeper_id: {"stat_pts", "xfp", "games", "trend", "matchup"}} for players with history."""
    out = {}
    for gsis, hist in ep.items():
        sid = gsis_to_sleeper.get(gsis)
        if not sid:
            continue
        xfp, n, trend = recent_xfp(hist, before_week)
        if xfp is None:
            continue
        team = (players.get(sid) or {}).get("team")
        m = matchup_factor(team, games)
        out[sid] = {"stat_pts": round(xfp * m, 2), "xfp": xfp, "games": n, "trend": trend, "matchup": m}
    return out


def stat_adjustment(score: float | None, est: dict | None) -> float | None:
    """Capped fractional adjustment the stats view would apply to `score`, or None if not enough data."""
    if not est or est.get("games", 0) < MIN_GAMES or not isinstance(score, (int, float)) or score < 1.0:
        return None
    adj = est["stat_pts"] / score - 1
    return round(max(-CAP, min(CAP, adj)), 3)
