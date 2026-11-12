"""NFL schedule from nflverse: byes, kickoff times (for lineup locks), Vegas lines.

Source: nflverse-data `schedules/games.csv` (free, CC-BY). Kickoff times there are
US Eastern local time; they are converted to UTC here without needing tzdata,
which Windows Python often lacks.
"""

from __future__ import annotations

import csv
import io
import time
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

GAMES_URL = "https://github.com/nflverse/nflverse-data/releases/download/schedules/games.csv"
CACHE_MAX_AGE_HOURS = 6

# nflverse team code -> Sleeper team code (only where they differ).
NFLVERSE_TO_SLEEPER = {"LA": "LAR"}


def _nth_sunday(year: int, month: int, n: int) -> date:
    d = date(year, month, 1)
    d += timedelta(days=(6 - d.weekday()) % 7)  # first Sunday
    return d + timedelta(weeks=n - 1)


def eastern_to_utc(day: str, hhmm: str) -> datetime:
    """'2026-11-15', '13:00' (US Eastern) -> aware UTC datetime.
    US DST: 2:00 AM on the 2nd Sunday of March to 2:00 AM on the 1st Sunday of November."""
    local = datetime.strptime(f"{day} {hhmm}", "%Y-%m-%d %H:%M")
    start = datetime.combine(_nth_sunday(local.year, 3, 2), datetime.min.time()).replace(hour=2)
    end = datetime.combine(_nth_sunday(local.year, 11, 1), datetime.min.time()).replace(hour=2)
    offset = 4 if start <= local < end else 5
    return (local + timedelta(hours=offset)).replace(tzinfo=timezone.utc)


def utc_to_pacific(dt: datetime) -> datetime:
    """Aware UTC datetime -> naive US Pacific local time (no tzdata needed).
    DST runs from 10:00 UTC on the 2nd Sunday of March to 09:00 UTC on the 1st Sunday of November."""
    dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    start = datetime.combine(_nth_sunday(dt.year, 3, 2), datetime.min.time()).replace(hour=10)
    end = datetime.combine(_nth_sunday(dt.year, 11, 1), datetime.min.time()).replace(hour=9)
    return dt - timedelta(hours=7 if start <= dt < end else 8)


def _to_float(v: str) -> float | None:
    try:
        return float(v) if v not in ("", "NA") else None
    except ValueError:
        return None


def parse_week(csv_text: str, season: int | str, week: int) -> dict:
    """Return {"games": {sleeper_team: game_info}, "teams": set(all teams that season)}."""
    season, week = str(season), str(week)
    games: dict[str, dict] = {}
    teams: set[str] = set()
    for r in csv.DictReader(io.StringIO(csv_text)):
        if r.get("season") != season:
            continue
        home = NFLVERSE_TO_SLEEPER.get(r["home_team"], r["home_team"])
        away = NFLVERSE_TO_SLEEPER.get(r["away_team"], r["away_team"])
        teams.update((home, away))
        if r.get("week") != week or r.get("game_type") != "REG":
            continue
        kickoff = eastern_to_utc(r["gameday"], r["gametime"] or "13:00")
        spread = _to_float(r.get("spread_line", ""))   # positive = home team favored
        total = _to_float(r.get("total_line", ""))
        for team, opp, is_home in ((home, away, True), (away, home, False)):
            implied = None
            if spread is not None and total is not None:
                margin = spread if is_home else -spread
                implied = round(total / 2 + margin / 2, 1)
            games[team] = {
                "game_id": r["game_id"],
                "opponent": opp,
                "home": is_home,
                "kickoff_utc": kickoff.isoformat(),
                "weekday": r.get("weekday"),
                "spread_line": spread,
                "total_line": total,
                "implied_total": implied,
            }
    return {"games": games, "teams": teams}


class Schedule:
    """One NFL week: who plays, when, and who is on bye."""

    def __init__(self, games: dict[str, dict], teams: set[str]):
        self.games = games
        self.teams = teams

    def game(self, team: str | None) -> dict | None:
        return self.games.get(team) if team else None

    def on_bye(self, team: str | None) -> bool:
        return bool(team) and team in self.teams and team not in self.games

    def bye_teams(self) -> list[str]:
        return sorted(self.teams - set(self.games))

    def is_locked(self, team: str | None, now: datetime) -> bool:
        g = self.game(team)
        return bool(g) and datetime.fromisoformat(g["kickoff_utc"]) <= now


def load_schedule(season: int | str, week: int, cache_dir: str | Path = ".cache",
                  url: str = GAMES_URL) -> Schedule:
    cache = Path(cache_dir) / "nflverse_games.csv"
    cache.parent.mkdir(parents=True, exist_ok=True)
    fresh = cache.exists() and (time.time() - cache.stat().st_mtime) / 3600 < CACHE_MAX_AGE_HOURS
    if not fresh:
        req = urllib.request.Request(url, headers={"User-Agent": "sitstart/0.2"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            cache.write_bytes(resp.read())
    parsed = parse_week(cache.read_text(encoding="utf-8"), season, week)
    return Schedule(parsed["games"], parsed["teams"])
