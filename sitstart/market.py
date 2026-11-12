"""Dynasty market values and team profiles (v2 trade finder, part 1).

Values come from FantasyCalc (free; derived from real trades), Superflex, half-PPR, 12 teams:
- value:          dynasty value (long-term)
- redraftValue:   this-season value (win-now)
Draft picks are valued from FantasyCalc's pick entries; 2027 picks are split Early/Mid/Late
by the original team's current standing.

Each team gets a profile and a lifecycle label:
- win_now:   redraft value of its best legal starting lineup
- dynasty:   total dynasty value, players + picks
- age:       dynasty-value-weighted age of its players
- youth:     share of dynasty value in picks and players 24 or younger
- record:    standings rank (wins, then points for)
- trades:    this season's net flow of picks/youth vs veterans
Label: contender / middle / rebuilder, with the reasons shown.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .optimizer import best_lineup

FC_URL = ("https://api.fantasycalc.com/values/current?isDynasty=true&numQbs={qbs}&numTeams={teams}&ppr={ppr}")
POSITIONS = ("QB", "RB", "WR", "TE")
YOUTH_AGE = 24.0
VET_AGE = {"QB": 31.0, "RB": 26.0, "WR": 28.0, "TE": 29.0}   # past these ages dynasty value tends to fall fast
ROUND_WORD = {1: "1st", 2: "2nd", 3: "3rd", 4: "4th"}


# --------------------------------------------------------------------------- #
# Values
# --------------------------------------------------------------------------- #

@dataclass
class Market:
    players: dict[str, dict]            # sleeper_id -> {name, pos, age, team, value, redraft, trend}
    picks: dict[str, float]             # "2027 1st (Early)" / "2028 1st" -> value

    def player(self, pid: str) -> dict | None:
        return self.players.get(str(pid))

    def value(self, pid: str) -> float:
        return float((self.players.get(str(pid)) or {}).get("value") or 0)

    def redraft(self, pid: str) -> float:
        return float((self.players.get(str(pid)) or {}).get("redraft") or 0)

    def pick_value(self, season: str, rnd: int, tier: str | None = None) -> float:
        word = ROUND_WORD.get(rnd, f"{rnd}th")
        if tier:
            v = self.picks.get(f"{season} {word} ({tier})")
            if v is not None:
                return v
        v = self.picks.get(f"{season} {word}")
        if v is not None:
            return v
        # Seasons FantasyCalc doesn't list yet: use the latest season it does list for that round.
        same_round = sorted((k for k in self.picks if re.fullmatch(rf"\d{{4}} {word}", k)), reverse=True)
        return self.picks[same_round[0]] if same_round else 0.0


def parse_fantasycalc(rows: list[dict]) -> Market:
    players, picks = {}, {}
    for r in rows or []:
        p = r.get("player") or {}
        if p.get("position") == "PICK":
            picks[p.get("name", "")] = float(r.get("value") or 0)
            continue
        sid = p.get("sleeperId")
        if not sid or p.get("position") not in POSITIONS:
            continue
        players[str(sid)] = {
            "name": p.get("name"), "pos": p.get("position"), "age": p.get("maybeAge"), "team": p.get("maybeTeam"),
            "value": float(r.get("value") or 0), "redraft": float(r.get("redraftValue") or 0),
            "trend": r.get("trend30Day"), "tier": r.get("maybeTier"),
        }
    return Market(players, picks)


# --------------------------------------------------------------------------- #
# Draft pick ownership
# --------------------------------------------------------------------------- #

def pick_ownership(roster_ids: list[int], traded: list[dict], seasons: list[str], rounds: int) -> list[dict]:
    """Every future pick and its current owner. Default: each team owns its own picks."""
    owner = {(s, r, rid): rid for s in seasons for r in range(1, rounds + 1) for rid in roster_ids}
    for t in traded or []:
        key = (str(t.get("season")), int(t.get("round") or 0), t.get("roster_id"))
        if key in owner and t.get("owner_id") is not None:
            owner[key] = t["owner_id"]
    return [{"season": s, "round": r, "original": rid, "owner": o} for (s, r, rid), o in sorted(owner.items())]


def pick_tier(original_rank: int, teams: int) -> str:
    """Projected slot from the original team's standing: best teams pick late."""
    third = teams / 3
    return "Late" if original_rank <= third else "Mid" if original_rank <= 2 * third else "Early"


def pick_label(p: dict, tier: str | None) -> str:
    base = f"{p['season']} {ROUND_WORD.get(p['round'], str(p['round']))}"
    return f"{base} ({tier})" if tier else base


# --------------------------------------------------------------------------- #
# Team profiles
# --------------------------------------------------------------------------- #

@dataclass
class Team:
    roster_id: int
    name: str
    wins: int
    losses: int
    points_for: float
    players: list[str]
    picks: list[dict] = field(default_factory=list)       # {"label", "value", "season", "round", "original"}
    record_rank: int = 0
    win_now: float = 0.0
    win_now_rank: int = 0
    dynasty: float = 0.0
    dynasty_rank: int = 0
    age: float | None = None
    youth: float = 0.0
    trade_lean: float = 0.0                                # + bought youth/picks, - bought veterans
    starters: list[str] = field(default_factory=list)      # best win-now lineup
    label: str = "middle"
    reasons: list[str] = field(default_factory=list)


def best_win_now(player_ids: list[str], slots: list[str], market: Market, positions: dict[str, str]) -> list[str]:
    def card(pid):
        pos = positions.get(pid) or (market.player(pid) or {}).get("pos")
        return {"player_id": pid, "name": pid, "position": pos, "fantasy_positions": [pos] if pos else [],
                "team": "X", "proj_pts": market.redraft(pid)}
    lineup = [{"slot": s, "player": None, "locked": False} for s in slots]
    return [r["player"]["player_id"] for r in best_lineup(lineup, [card(p) for p in player_ids]) if r["player"]]


def _rank(values: dict[int, float], reverse: bool = True) -> dict[int, int]:
    order = sorted(values, key=lambda k: values[k], reverse=reverse)
    return {k: i + 1 for i, k in enumerate(order)}


def trade_lean(trades: list[dict], market: Market) -> dict[int, float]:
    """Per roster: dynasty value of picks + young players received minus veterans received (net, this season)."""
    lean: dict[int, float] = {}
    for t in trades or []:
        for pid, rid in (t.get("adds") or {}).items():
            p = market.player(pid) or {}
            v = market.value(pid)
            age = p.get("age") or 0
            if age and age <= YOUTH_AGE:
                lean[rid] = lean.get(rid, 0) + v
            elif age and age >= VET_AGE.get(p.get("pos"), 28):
                lean[rid] = lean.get(rid, 0) - v
        for dp in t.get("draft_picks") or []:
            v = market.pick_value(str(dp.get("season")), int(dp.get("round") or 0))
            lean[dp.get("owner_id")] = lean.get(dp.get("owner_id"), 0) + v
            lean[dp.get("previous_owner_id")] = lean.get(dp.get("previous_owner_id"), 0) - v
    return lean


def build_profiles(rosters: list[dict], users: list[dict], market: Market, slots: list[str],
                   positions: dict[str, str], traded_picks: list[dict], trades: list[dict],
                   season: int, rounds: int) -> dict[int, Team]:
    names = {u["user_id"]: ((u.get("metadata") or {}).get("team_name") or u.get("display_name") or "?") for u in users}
    teams: dict[int, Team] = {}
    for r in rosters:
        st = r.get("settings") or {}
        pf = float(st.get("fpts") or 0) + float(st.get("fpts_decimal") or 0) / 100
        teams[r["roster_id"]] = Team(r["roster_id"], names.get(r.get("owner_id"), f"Team {r['roster_id']}"),
                                     int(st.get("wins") or 0), int(st.get("losses") or 0), pf,
                                     [p for p in (r.get("players") or []) if p])
    n = len(teams)
    rec = _rank({rid: t.wins * 10000 + t.points_for for rid, t in teams.items()})
    for rid, t in teams.items():
        t.record_rank = rec[rid]

    seasons = [str(season + i) for i in (1, 2, 3)]
    for p in pick_ownership(list(teams), traded_picks, seasons, rounds):
        tier = pick_tier(teams[p["original"]].record_rank, n) if p["season"] == seasons[0] else None
        val = market.pick_value(p["season"], p["round"], tier)
        teams[p["owner"]].picks.append({**p, "label": pick_label(p, tier), "value": val,
                                        "from": None if p["original"] == p["owner"] else teams[p["original"]].name})

    lean = trade_lean(trades, market)
    for t in teams.values():
        t.starters = best_win_now(t.players, slots, market, positions)
        t.win_now = sum(market.redraft(p) for p in t.starters)
        pv = [(market.value(p), (market.player(p) or {}).get("age")) for p in t.players]
        pick_total = sum(p["value"] for p in t.picks)
        t.dynasty = sum(v for v, _ in pv) + pick_total
        aged = [(v, a) for v, a in pv if a and v > 0]
        t.age = round(sum(v * a for v, a in aged) / sum(v for v, _ in aged), 1) if aged else None
        young = sum(v for v, a in pv if a and a <= YOUTH_AGE) + pick_total
        t.youth = round(young / t.dynasty, 3) if t.dynasty else 0.0
        t.trade_lean = round(lean.get(t.roster_id, 0.0))

    wn = _rank({rid: t.win_now for rid, t in teams.items()})
    dy = _rank({rid: t.dynasty for rid, t in teams.items()})
    youth_median = sorted(t.youth for t in teams.values())[n // 2]
    for rid, t in teams.items():
        t.win_now_rank, t.dynasty_rank = wn[rid], dy[rid]
        classify(t, n, youth_median)
    return teams


def classify(t: Team, n: int, youth_median: float) -> None:
    top, bottom = n / 3, n - n / 3
    reasons = [f"{t.wins}-{t.losses}, {ordinal(t.record_rank)} in standings",
               f"{ordinal(t.win_now_rank)} in win-now value"]
    contend = (t.record_rank <= top or t.win_now_rank <= top) and t.win_now_rank <= n / 2
    rebuild = (t.record_rank > bottom and (t.youth >= youth_median or t.win_now_rank > n / 2)) or t.win_now_rank > bottom + 1
    if t.trade_lean > 3000:
        reasons.append("has been trading for picks and young players")
        rebuild = rebuild or t.record_rank > n / 2
        contend = contend and not rebuild
    elif t.trade_lean < -3000:
        reasons.append("has been trading for veterans")
        contend = contend or t.record_rank <= n / 2
        rebuild = rebuild and not contend
    if t.age:
        reasons.append(f"value-weighted age {t.age:.1f}")
    reasons.append(f"{t.youth:.0%} of value in picks and players 24 or under")
    t.label = "contender" if contend and not rebuild else "rebuilder" if rebuild else "middle"
    t.reasons = reasons


def ordinal(n: int) -> str:
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"
