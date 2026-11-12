"""Sleeper weekly projections, scored with your league's exact settings.

Sleeper's projected stat lines use the same keys as a league's `scoring_settings`
(pass_yd, pass_td, rec, rec_yd, rush_td, fum_lost, ...), so league points are a
key-by-key multiply. Sleeper's own pts_half_ppr is kept as a cross-check.

The projections endpoints are undocumented. In Sept 2026 the old
api.sleeper.app/v1 path started returning empty entries, so the api.sleeper.com
path (what Sleeper's own app uses) is tried first, with v1 as the fallback.
"""

from __future__ import annotations

from typing import Any, Callable

APP_URL = ("https://api.sleeper.com/projections/nfl/{season}/{week}?season_type=regular"
           "&position[]=QB&position[]=RB&position[]=WR&position[]=TE")
V1_URL = "https://api.sleeper.app/v1/projections/nfl/regular/{season}/{week}"

# Position-specific reception bonuses Sleeper leagues can set (TE premium etc.).
POSITION_REC_BONUS = {"TE": "bonus_rec_te", "RB": "bonus_rec_rb", "WR": "bonus_rec_wr"}


def normalize(raw: Any) -> dict[str, dict]:
    """Accept either shape Sleeper has served and return {player_id: stats}.
    App shape: [{"player_id": "4046", "stats": {...}, ...}, ...]
    v1 shape:  {"4046": {...stats...}, ...}"""
    out: dict[str, dict] = {}
    if isinstance(raw, list):
        for e in raw:
            if isinstance(e, dict) and e.get("player_id") and isinstance(e.get("stats"), dict):
                out[str(e["player_id"])] = e["stats"]
    elif isinstance(raw, dict):
        for pid, stats in raw.items():
            if isinstance(stats, dict):
                out[str(pid)] = stats.get("stats", stats) if isinstance(stats.get("stats"), dict) else stats
    return {pid: s for pid, s in out.items() if s}  # drop the empty entries v1 now returns


def score_stats(stats: dict, scoring: dict, position: str | None = None) -> float:
    pts = 0.0
    for key, weight in scoring.items():
        val = stats.get(key)
        if isinstance(val, (int, float)) and isinstance(weight, (int, float)):
            pts += val * weight
    bonus_key = POSITION_REC_BONUS.get(position or "")
    if bonus_key and bonus_key in scoring and bonus_key not in stats:
        pts += float(stats.get("rec", 0) or 0) * float(scoring[bonus_key] or 0)
    return round(pts, 2)


def fetch_projections(get_url: Callable[[str], Any], season: str | int, week: int) -> tuple[dict[str, dict], str]:
    """Returns ({player_id: stats}, source). Empty dict if both endpoints fail."""
    for name, url in (("app", APP_URL), ("v1", V1_URL)):
        try:
            data = normalize(get_url(url.format(season=season, week=week)))
        except Exception:
            data = {}
        if data:
            return data, name
    return {}, "none"


def league_points(projections: dict[str, dict], scoring: dict, positions: dict[str, str]) -> dict[str, dict]:
    """{player_id: {"proj_pts": league-scored, "proj_pts_sleeper_half": Sleeper's own half-PPR}}"""
    out = {}
    for pid, stats in projections.items():
        out[pid] = {
            "proj_pts": score_stats(stats, scoring, positions.get(pid)),
            "proj_pts_sleeper_half": stats.get("pts_half_ppr"),
        }
    return out
