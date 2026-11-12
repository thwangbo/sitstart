"""Sleeper connector for the sit/start app (build plan step 1).

Pulls everything the scoring model needs about your league and team: league
detection (dynasty + Superflex), scoring settings, starting slots, your roster
split into lineup / bench / taxi / IR, this week's opponent, and for every
rostered player: league-scored projection, opponent, kickoff, bye and lock status.

Standard library only, so it runs on any Python 3.10+ with no installs.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .consensus import blend, expert_points
from .projections import fetch_projections, league_points
from .schedule import Schedule

BASE_URL = "https://api.sleeper.app/v1"

NON_STARTING_SLOTS = {"BN", "IR", "TAXI"}

SLOT_ELIGIBILITY: dict[str, set[str]] = {
    "QB": {"QB"},
    "RB": {"RB"},
    "WR": {"WR"},
    "TE": {"TE"},
    "K": {"K"},
    "DEF": {"DEF"},
    "FLEX": {"RB", "WR", "TE"},
    "WRRB_FLEX": {"RB", "WR"},
    "REC_FLEX": {"WR", "TE"},
    "SUPER_FLEX": {"QB", "RB", "WR", "TE"},
}

OUT_STATUSES = {"Out", "IR", "Doubtful", "Sus", "PUP"}
PLAYERS_CACHE_MAX_AGE_HOURS = 24


class SleeperError(RuntimeError):
    """Raised when Sleeper returns nothing usable."""


# --------------------------------------------------------------------------- #
# HTTP client
# --------------------------------------------------------------------------- #

class SleeperClient:
    """Thin read-only client. Sleeper's public API needs no auth key."""

    def __init__(self, base_url: str = BASE_URL, cache_dir: str | Path = ".cache",
                 timeout: int = 30, retries: int = 3):
        self.base_url = base_url.rstrip("/")
        self.cache_dir = Path(cache_dir)
        self.timeout = timeout
        self.retries = retries

    def get(self, path: str) -> Any:
        return self.get_url(f"{self.base_url}/{path.lstrip('/')}")

    def get_url(self, url: str) -> Any:
        last_err: Exception | None = None
        for attempt in range(self.retries):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "sitstart/0.2"})
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    body = resp.read().decode("utf-8")
                    return json.loads(body) if body else None
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    return None
                last_err = e
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
                last_err = e
            time.sleep(1.5 * (attempt + 1))
        raise SleeperError(f"Request failed after {self.retries} tries: {url} ({last_err})")

    def players(self) -> dict[str, dict]:
        """The ~5 MB player master list, cached for a day (Sleeper asks callers
        not to pull it more than once a day)."""
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        cache = self.cache_dir / "players_nfl.json"
        if cache.exists() and (time.time() - cache.stat().st_mtime) / 3600 < PLAYERS_CACHE_MAX_AGE_HOURS:
            return json.loads(cache.read_text(encoding="utf-8"))
        data = self.get("players/nfl") or {}
        cache.write_text(json.dumps(data), encoding="utf-8")
        return data


# --------------------------------------------------------------------------- #
# League detection and parsing
# --------------------------------------------------------------------------- #

def is_superflex(league: dict) -> bool:
    return "SUPER_FLEX" in (league.get("roster_positions") or [])


def is_dynasty(league: dict) -> bool:
    if (league.get("settings") or {}).get("type") == 2:
        return True
    name = (league.get("name") or "").lower()
    return "dynasty" in name or "keeper" in name


def pick_league(leagues: list[dict], league_id: str | None = None) -> dict:
    """Choose the dynasty Superflex league. If several qualify, list them rather than guess."""
    if not leagues:
        raise SleeperError("No NFL leagues found for this user and season.")
    if league_id:
        for lg in leagues:
            if str(lg.get("league_id")) == str(league_id):
                return lg
        raise SleeperError(f"League {league_id} is not among this user's leagues.")

    matches = [lg for lg in leagues if is_dynasty(lg) and is_superflex(lg)]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        matches = [lg for lg in leagues if is_dynasty(lg)] or [lg for lg in leagues if is_superflex(lg)]
        if len(matches) == 1:
            return matches[0]
    listing = "\n".join(f"  {lg.get('league_id')}  {lg.get('name')}" for lg in (matches or leagues))
    raise SleeperError("Couldn't pick one league automatically. Re-run with --league-id, one of:\n" + listing)


def starting_slots(roster_positions: list[str]) -> list[str]:
    return [s for s in roster_positions if s not in NON_STARTING_SLOTS]


def scoring_summary(scoring: dict) -> dict:
    rec = float(scoring.get("rec", 0) or 0)
    fmt = {0.0: "Standard", 0.5: "Half-PPR", 1.0: "PPR"}.get(rec, f"{rec} PPR")
    return {
        "format": fmt,
        "points_per_reception": rec,
        "te_premium": float(scoring.get("bonus_rec_te", 0) or 0),
        "pass_td": float(scoring.get("pass_td", 4) or 0),
        "pass_yd_per_point": round(1 / scoring["pass_yd"], 1) if scoring.get("pass_yd") else None,
        "interception": float(scoring.get("pass_int", -1) or 0),
        "fumble_lost": float(scoring.get("fum_lost", -2) or 0),
    }


def find_my_roster(rosters: list[dict], user_id: str) -> dict:
    for r in rosters:
        if str(r.get("owner_id")) == str(user_id):
            return r
    for r in rosters:
        if str(user_id) in [str(c) for c in (r.get("co_owners") or [])]:
            return r
    raise SleeperError("Couldn't find your roster in this league.")


# --------------------------------------------------------------------------- #
# Player cards
# --------------------------------------------------------------------------- #

@dataclass
class WeekContext:
    """Everything about this NFL week that a player card is enriched with."""
    schedule: Schedule | None = None
    points: dict[str, dict] = field(default_factory=dict)
    now: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    consensus: dict[str, dict] = field(default_factory=dict)   # sleeper_id -> consensus row
    expert: dict[str, float] = field(default_factory=dict)     # sleeper_id -> expert-implied points
    weight: float = 0.5                                        # blend weight on experts


def player_card(pid: str | None, players: dict[str, dict], ctx: WeekContext | None = None) -> dict | None:
    if not pid or pid == "0":
        return None
    p = players.get(str(pid)) or {}
    pos = p.get("position") or ("DEF" if not str(pid).isdigit() else None)
    name = p.get("full_name") or " ".join(x for x in (p.get("first_name"), p.get("last_name")) if x) or str(pid)
    team = p.get("team") or (str(pid) if pos == "DEF" else None)
    card = {
        "player_id": str(pid),
        "name": name,
        "position": pos,
        "fantasy_positions": p.get("fantasy_positions") or ([pos] if pos else []),
        "team": team,
        "age": p.get("age"),
        "years_exp": p.get("years_exp"),
        "injury_status": p.get("injury_status"),
        "status": p.get("status"),
    }
    if ctx is not None:
        pts = ctx.points.get(str(pid), {})
        card["proj_pts"] = pts.get("proj_pts")
        card["proj_pts_sleeper_half"] = pts.get("proj_pts_sleeper_half")
        cons = ctx.consensus.get(str(pid))
        card["consensus_rank"] = f"{cons['pos']}{cons['rank']}" if cons else None
        card["expert_pts"] = ctx.expert.get(str(pid))
        if card["proj_pts"] is not None or card["expert_pts"] is not None:
            card["score"] = blend(card["proj_pts"], card["expert_pts"], ctx.weight)
        if ctx.schedule is not None:
            g = ctx.schedule.game(team)
            card["bye"] = ctx.schedule.on_bye(team)
            card["opponent"] = (("vs " if g["home"] else "@ ") + g["opponent"]) if g else None
            card["kickoff_utc"] = g["kickoff_utc"] if g else None
            card["implied_total"] = g["implied_total"] if g else None
            card["locked"] = ctx.schedule.is_locked(team, ctx.now)
        if card.get("bye"):
            card["proj_pts"] = 0.0
            card["score"] = 0.0
    return card


def can_fill(slot: str, card: dict | None) -> bool:
    if card is None:
        return False
    eligible = SLOT_ELIGIBILITY.get(slot)
    if eligible is None:
        return True
    return bool(eligible & set(card.get("fantasy_positions") or [card.get("position")]))


def lineup_flag(slot: str, card: dict | None) -> str | None:
    """Most urgent problem with a starter, or None."""
    if card is None:
        return "EMPTY_SLOT"
    if card.get("bye"):
        return "STARTER_ON_BYE"
    if card.get("injury_status") in OUT_STATUSES:
        return f"STARTER_{card['injury_status'].upper()}"
    if not card.get("team"):
        return "NO_NFL_TEAM"
    if not can_fill(slot, card):
        return "INELIGIBLE_FOR_SLOT"
    return None


def lineup_from_starters(slots: list[str], starters: list[str], players: dict[str, dict],
                         ctx: WeekContext | None = None) -> list[dict]:
    """Sleeper's starters array is ordered to match the starting slots."""
    out = []
    for i, slot in enumerate(slots):
        pid = starters[i] if i < len(starters) else None
        card = player_card(pid, players, ctx)
        out.append({
            "slot": slot,
            "player": card,
            "empty": card is None,
            "locked": bool(card and card.get("locked")),
            "flag": lineup_flag(slot, card),
        })
    return out


# --------------------------------------------------------------------------- #
# Snapshot assembly
# --------------------------------------------------------------------------- #

@dataclass
class SleeperSnapshot:
    season: str
    week: int
    league: dict
    me: dict
    lineup: list[dict]
    bench: list[dict]
    taxi: list[dict]
    reserve: list[dict]
    opponent: dict | None
    league_rosters: list[dict] = field(default_factory=list)
    data_status: dict = field(default_factory=dict)
    suggestion: dict | None = None
    generated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))

    def to_dict(self) -> dict:
        return self.__dict__.copy()


def build_snapshot(client: SleeperClient, username: str, season: str | None = None,
                   week: int | None = None, league_id: str | None = None,
                   players: dict[str, dict] | None = None,
                   schedule: Schedule | None = None,
                   now: datetime | None = None,
                   fetch_proj: bool = True,
                   consensus: dict[str, dict] | None = None,
                   weight: float = 0.5) -> SleeperSnapshot:
    state = client.get("state/nfl") or {}
    season = str(season or state.get("league_season") or state.get("season"))
    week = int(week or state.get("display_week") or state.get("week") or 1)

    user = client.get(f"user/{username}")
    if not user:
        raise SleeperError(f"No Sleeper user named '{username}'.")
    user_id = str(user["user_id"])

    leagues = client.get(f"user/{user_id}/leagues/nfl/{season}") or []
    league = pick_league(leagues, league_id)
    lid = str(league["league_id"])

    rosters = client.get(f"league/{lid}/rosters") or []
    users = client.get(f"league/{lid}/users") or []
    matchups = client.get(f"league/{lid}/matchups/{week}") or []
    players = players if players is not None else client.players()
    scoring = league.get("scoring_settings") or {}

    # Projections, scored in this league's settings.
    proj_source = "skipped"
    points: dict[str, dict] = {}
    if fetch_proj:
        raw, proj_source = fetch_projections(client.get_url, season, week)
        positions = {pid: (players.get(pid) or {}).get("position") for pid in raw}
        points = league_points(raw, scoring, positions)

    consensus = consensus or {}
    expert = {}
    if consensus and points:
        positions_all = {pid: (p or {}).get("position") for pid, p in players.items()}
        expert = expert_points(consensus, {pid: v["proj_pts"] for pid, v in points.items()}, positions_all)
    ctx = WeekContext(schedule=schedule, points=points, now=now or datetime.now(timezone.utc),
                      consensus=consensus, expert=expert, weight=weight)
    users_by_id = {str(u["user_id"]): u for u in users}

    def team_label(roster: dict) -> dict:
        u = users_by_id.get(str(roster.get("owner_id")), {})
        meta = u.get("metadata") or {}
        return {
            "roster_id": roster.get("roster_id"),
            "owner_id": roster.get("owner_id"),
            "display_name": u.get("display_name"),
            "team_name": meta.get("team_name") or u.get("display_name"),
        }

    slots = starting_slots(league.get("roster_positions") or [])
    mine = find_my_roster(rosters, user_id)
    my_rid = mine.get("roster_id")

    my_match = next((m for m in matchups if m.get("roster_id") == my_rid), None)
    starters = (my_match or {}).get("starters") or mine.get("starters") or []

    lineup = lineup_from_starters(slots, starters, players, ctx)
    taxi_ids = list(mine.get("taxi") or [])
    reserve_ids = list(mine.get("reserve") or [])
    starter_ids = {s for s in starters if s and s != "0"}
    bench_ids = [p for p in (mine.get("players") or [])
                 if p not in starter_ids and p not in taxi_ids and p not in reserve_ids]

    def cards(ids) -> list[dict]:
        return [c for c in (player_card(p, players, ctx) for p in ids) if c]

    opponent = None
    if my_match and my_match.get("matchup_id") is not None:
        opp = next((m for m in matchups if m.get("matchup_id") == my_match["matchup_id"]
                    and m.get("roster_id") != my_rid), None)
        if opp:
            opp_roster = next((r for r in rosters if r.get("roster_id") == opp["roster_id"]), {})
            opp_lineup = lineup_from_starters(slots, opp.get("starters") or [], players, ctx)
            opponent = {**team_label(opp_roster), "lineup": opp_lineup,
                        "proj_total": _lineup_total(opp_lineup)}

    settings = league.get("settings") or {}
    league_info = {
        "league_id": lid,
        "name": league.get("name"),
        "season": season,
        "total_rosters": league.get("total_rosters"),
        "is_dynasty": is_dynasty(league),
        "is_superflex": is_superflex(league),
        "starting_slots": slots,
        "roster_positions": league.get("roster_positions"),
        "taxi_slots": settings.get("taxi_slots"),
        "reserve_slots": settings.get("reserve_slots"),
        "playoff_week_start": settings.get("playoff_week_start"),
        "scoring_summary": scoring_summary(scoring),
        "scoring_settings": scoring,
    }

    league_rosters = [{**team_label(r), "player_ids": r.get("players") or [],
                       "taxi": r.get("taxi") or [], "reserve": r.get("reserve") or [],
                       "wins": (r.get("settings") or {}).get("wins"),
                       "losses": (r.get("settings") or {}).get("losses")}
                      for r in rosters]

    data_status = {
        "projections_source": proj_source,
        "projections_count": len(points),
        "schedule_loaded": schedule is not None,
        "bye_teams": schedule.bye_teams() if schedule else None,
        "consensus_players": len(consensus),
        "consensus_scrape_date": next((r.get("scrape_date") for r in consensus.values()), None),
        "blend_weight": weight if consensus else 0.0,
    }

    bench = cards(bench_ids)
    suggestion = None
    if points:
        from .optimizer import best_lineup, suggested_changes  # local import avoids a cycle
        suggestion = suggested_changes(lineup, best_lineup(lineup, bench))

    return SleeperSnapshot(
        season=season, week=week, league=league_info,
        me={**team_label(mine), "user_id": user_id},
        lineup=lineup, bench=bench, taxi=cards(taxi_ids), reserve=cards(reserve_ids),
        opponent=opponent, league_rosters=league_rosters, data_status=data_status,
        suggestion=suggestion,
    )


def card_value(card: dict | None):
    """The number the app ranks on: the blended score when experts are in, else Sleeper's projection."""
    if not card:
        return None
    return card["score"] if isinstance(card.get("score"), (int, float)) else card.get("proj_pts")


def _lineup_total(lineup: list[dict]) -> float | None:
    vals = [card_value(r["player"]) for r in lineup if r["player"]]
    vals = [v for v in vals if isinstance(v, (int, float))]
    return round(sum(vals), 1) if vals else None


# --------------------------------------------------------------------------- #
# Console summary
# --------------------------------------------------------------------------- #

def _fmt_pts(card: dict | None) -> str:
    v = card_value(card)
    return f"{v:5.1f}" if isinstance(v, (int, float)) else "   --"


def format_summary(snap: SleeperSnapshot) -> str:
    lg = snap.league
    sc = lg["scoring_summary"]
    ds = snap.data_status
    lines = [
        f"{lg['name']}  |  {snap.season} Week {snap.week}  |  {lg['total_rosters']} teams",
        f"Format: {sc['format']}, {'Superflex' if lg['is_superflex'] else '1QB'}, "
        f"{'dynasty' if lg['is_dynasty'] else 'redraft'}, pass TD = {sc['pass_td']:g}"
        + (f", TE premium +{sc['te_premium']:g}" if sc["te_premium"] else ""),
        f"Your team: {snap.me['team_name']}",
        f"Projections: {ds.get('projections_source')} ({ds.get('projections_count')} players)"
        + (f"  |  Byes: {', '.join(ds['bye_teams'])}" if ds.get("bye_teams") else ""),
        "",
        _blend_note(ds),
        "",
        "Current lineup                              score",
    ]
    for row in snap.lineup:
        p = row["player"]
        who = f"{p['name']} ({p['position']}, {p['team'] or 'FA'})" if p else "-- empty --"
        extra = ""
        if p and p.get("opponent"):
            extra += f" {p['opponent']}"
        if p and p.get("injury_status"):
            extra += f" [{p['injury_status']}]"
        if row["locked"]:
            extra += " [locked]"
        flag = f"   <-- {row['flag']}" if row["flag"] else ""
        lines.append(f"  {row['slot']:<11}{(who + extra)[:33]:<33}{_fmt_pts(p)}{flag}")
    total = _lineup_total(snap.lineup)
    if total is not None:
        lines.append(f"  {'TOTAL':<44}{total:5.1f}")
    lines.append("")
    flags = [r for r in snap.lineup if r["flag"]]
    lines.append(f"Lineup warnings: {len(flags)}" if flags else "Lineup warnings: none")

    sug = snap.suggestion
    if sug:
        lines.append("")
        if sug.get("actionable"):
            gain = f": +{sug['gain']:.1f} pts" if sug["gain"] > 0.05 else ""
            lines.append(f"Suggested changes{gain}")
            for verb, group in (("START", sug["start"]), ("SIT  ", sug["sit"])):
                for c in group:
                    note = ""
                    if c.get("injury_status") == "Questionable":
                        note = f"  [Questionable: counted as {c['value']:.1f}]"
                    elif c.get("injury_status"):
                        note = f"  [{c['injury_status']}]"
                    lines.append(f"  {verb}  {c['name']:<28}{c['proj_pts']:5.1f}{note}")
            if sug["slot_moves"]:
                lines.append("  Then set slots as: " + ", ".join(
                    f"{r['slot']} {r['name']}" for r in sug["lineup"] if r["name"]))
        else:
            lines.append("Suggested changes: none. Your lineup is already the best on Score.")

    lines.append("")
    bench = sorted(snap.bench, key=lambda c: -(card_value(c) or 0))
    lines.append(f"Bench ({len(bench)}): " + ", ".join(_bench_label(c) for c in bench))
    if snap.taxi:
        lines.append(f"Taxi ({len(snap.taxi)}): " + ", ".join(c["name"] for c in snap.taxi))
    if snap.reserve:
        lines.append(f"IR ({len(snap.reserve)}): " + ", ".join(c["name"] for c in snap.reserve))
    if snap.opponent:
        lines.append("")
        opp_total = snap.opponent.get("proj_total")
        lines.append(f"Opponent: {snap.opponent['team_name']}"
                     + (f"  (projected {opp_total:.1f} vs your {total:.1f})" if opp_total is not None and total is not None else ""))
        opp_flags = [r for r in snap.opponent["lineup"] if r["flag"]]
        quest = [r["player"]["name"] for r in snap.opponent["lineup"]
                 if r["player"] and r["player"].get("injury_status") == "Questionable"]
        notes = [f"{r['player']['name']} {_FLAG_WORDS.get(r['flag'], r['flag'])}" if r["player"]
                 else f"{r['slot']} empty" for r in opp_flags]
        if quest:
            notes.append("Questionable: " + ", ".join(quest))
        if notes:
            lines.append("  " + "; ".join(notes))
    return "\n".join(lines)


_FLAG_WORDS = {"STARTER_ON_BYE": "on bye", "STARTER_OUT": "Out", "STARTER_IR": "on IR",
               "STARTER_DOUBTFUL": "Doubtful", "NO_NFL_TEAM": "has no NFL team"}


def _blend_note(ds: dict) -> str:
    if ds.get("consensus_players"):
        w = ds.get("blend_weight", 0.5)
        return (f"Score = {1 - w:.0%} Sleeper projection + {w:.0%} expert consensus "
                f"(FantasyPros via DynastyProcess, {ds.get('consensus_scrape_date')}; {ds['consensus_players']} players)")
    return "Score = Sleeper projection (expert consensus unavailable this run)"


def _bench_label(c: dict) -> str:
    s = f"{c['name']} {c['position']}"
    v = card_value(c)
    if isinstance(v, (int, float)):
        s += f" {v:.1f}"
    if c.get("bye"):
        s += " [bye]"
    elif c.get("injury_status"):
        s += f" [{c['injury_status']}]"
    elif not c.get("team"):
        s += " [no team]"
    if c.get("locked"):
        s += " [locked]"
    return s


def save_snapshot(snap: SleeperSnapshot, out_dir: str | Path = "data") -> Path:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"sleeper_{snap.season}_wk{snap.week:02d}.json"
    text = json.dumps(snap.to_dict(), indent=2)
    path.write_text(text, encoding="utf-8")
    (out / "sleeper_latest.json").write_text(text, encoding="utf-8")
    return path
