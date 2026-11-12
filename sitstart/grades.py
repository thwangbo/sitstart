"""Weekly report card: after each week, how would each approach have done for your team?

Uses the last snapshot saved before games (Sunday 8:40 AM PT run), so every approach
sees the same roster, injuries and locks the app saw. Scored with actual points.

    you          the lineup you actually started
    app          the app's pick (Score: 50/50 Sleeper + experts)
    sleeper      Sleeper projections only
    stats        Score x (1 + stats adjustment), the shadow-mode view
    best         best possible lineup in hindsight

Weeks 1-9 are seeded from the backtest (no injury info then), marked source "backtest".
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path

from .optimizer import best_lineup

GRADES_FILE = "grades.json"


def _with_value(card: dict | None, value, keep_injury: bool = True) -> dict | None:
    if card is None:
        return None
    c = copy.deepcopy(card)
    c["score"] = float(value) if isinstance(value, (int, float)) else 0.0
    if not keep_injury:
        c["injury_status"] = None
    return c


def _pick(snap: dict, key, keep_injury: bool = True) -> list[str]:
    """Player ids the optimizer starts when ranking on `key` (a field name or a function of the card)."""
    get = key if callable(key) else (lambda c: c.get(key))
    lineup = [{"slot": r["slot"], "locked": r.get("locked", False),
               "player": _with_value(r["player"], get(r["player"]) if r["player"] else 0, keep_injury)}
              for r in snap["lineup"]]
    bench = [_with_value(c, get(c), keep_injury) for c in snap["bench"]]
    return [r["player"]["player_id"] for r in best_lineup(lineup, bench) if r["player"]]


def grade_week(snap: dict, my_matchup: dict) -> dict:
    pts = {k: float(v or 0) for k, v in (my_matchup.get("players_points") or {}).items()}
    total = lambda ids: round(sum(pts.get(i, 0.0) for i in ids), 2)
    started = [s for s in (my_matchup.get("starters") or []) if s and s != "0"]

    def score_or_proj(c):
        return c.get("score") if isinstance(c.get("score"), (int, float)) else c.get("proj_pts")

    def with_stats(c):
        base = score_or_proj(c)
        return c.get("score_with_stats") if isinstance(c.get("score_with_stats"), (int, float)) else base

    has_stats = any(isinstance(c.get("stat_adj"), (int, float))
                    for c in [r["player"] for r in snap["lineup"] if r["player"]] + snap["bench"])
    g = {
        "week": snap["week"],
        "source": "live",
        "you": total(started),
        "app": total(_pick(snap, score_or_proj)),
        "sleeper": total(_pick(snap, "proj_pts")),
        "stats": total(_pick(snap, with_stats)) if has_stats else None,
        "best": total(_pick(snap, lambda c: pts.get(c["player_id"], 0.0), keep_injury=False)),
    }
    return g


def load(out_dir: str | Path) -> list[dict]:
    p = Path(out_dir) / GRADES_FILE
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return []
    return []


def save(out_dir: str | Path, grades: list[dict]) -> None:
    p = Path(out_dir) / GRADES_FILE
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(sorted(grades, key=lambda g: g["week"]), indent=2), encoding="utf-8")


def seed_from_backtest(results_path: str | Path, roster_id) -> list[dict]:
    p = Path(results_path)
    if not p.exists():
        return []
    data = json.loads(p.read_text(encoding="utf-8"))
    out = []
    for r in data.get("rows", []):
        if r.get("roster_id") != roster_id:
            continue
        out.append({"week": r["week"], "source": "backtest", "you": r["actual"], "app": r.get("w0.5"),
                    "sleeper": r.get("w0.0"), "stats": r.get("stats0.5"), "best": r["hindsight"]})
    return sorted(out, key=lambda g: g["week"])


def update(out_dir: str | Path, season: str, current_week: int, league_id: str, roster_id, get,
           backtest_results: str | Path = "backtest/results.json") -> list[dict]:
    """Grade every finished week that has a saved pre-game snapshot. `get` fetches a Sleeper API path."""
    grades = load(out_dir)
    if not grades:
        grades = seed_from_backtest(backtest_results, roster_id)
    done = {g["week"]: g for g in grades}
    for f in sorted(Path(out_dir).glob(f"sleeper_{season}_wk*.json")):
        m = re.search(r"wk(\d+)\.json$", f.name)
        wk = int(m.group(1)) if m else 0
        if wk >= current_week or (wk in done and done[wk].get("source") == "live"):
            continue
        matchups = get(f"league/{league_id}/matchups/{wk}") or []
        mine = next((x for x in matchups if x.get("roster_id") == roster_id), None)
        if not mine or not any(float(v or 0) for v in (mine.get("players_points") or {}).values()):
            continue  # not played yet
        snap = json.loads(f.read_text(encoding="utf-8"))
        done[wk] = grade_week(snap, mine)
    grades = sorted(done.values(), key=lambda g: g["week"])
    save(out_dir, grades)
    return grades


def stats_streak(grades: list[dict], n: int = 3) -> bool:
    """True if the stats view beat the app in each of the last n graded weeks (live or backtest)."""
    recent = [g for g in grades if isinstance(g.get("stats"), (int, float)) and isinstance(g.get("app"), (int, float))][-n:]
    return len(recent) == n and all(g["stats"] > g["app"] + 0.005 for g in recent)
