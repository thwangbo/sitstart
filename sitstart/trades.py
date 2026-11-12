"""Trade targets (v2 trade finder, part 2).

Lens follows your team's lifecycle:
- contender: buy this-season production (win-now value) cheaply in dynasty value,
  ideally veterans on rebuilding teams, paying with bench players and picks
- rebuilder: buy dynasty value (young players), ideally surplus on contending teams

For each player on another roster:
  gain    = how much your best starting lineup improves with him (win-now value), or his
            dynasty value for a rebuilder
  motive  = how likely his manager is to sell (their lifecycle, his age, whether he starts for them)
  score   = gain x motive
Then an offer is built from your surplus (bench players and picks) at 100-120% of his
market value, shaped to what the other manager needs: picks and young players for a
rebuilder, producers for a contender. Superflex: never offers a QB if that would leave
you with fewer than 3 startable QBs.
"""

from __future__ import annotations

from itertools import combinations

from .market import VET_AGE, YOUTH_AGE, Market, Team, best_win_now

MAX_TARGETS = 12
QB_STARTABLE = 1500.0        # win-now value of a usable bye/injury fill-in QB in Superflex
MIN_QBS = 3


def _age(market: Market, pid: str):
    return (market.player(pid) or {}).get("age")


def _pos(market: Market, pid: str):
    return (market.player(pid) or {}).get("pos")


def seller_motive(team: Team, pid: str, market: Market) -> tuple[float, str]:
    age, pos = _age(market, pid), _pos(market, pid)
    starter = pid in team.starters
    vet = bool(age) and age >= VET_AGE.get(pos, 28) - 1
    if team.label == "rebuilder":
        if vet:
            return 1.0, f"{team.name} is rebuilding and he's {age:.0f}"
        return 0.6, f"{team.name} is rebuilding, but he's young, so expect to pay full price"
    if team.label == "middle":
        if not starter:
            return 0.6, f"{team.name} is in the middle and he's their depth"
        return 0.45 if vet else 0.35, f"{team.name} is in the middle; he starts for them"
    if not starter:
        return 0.5, f"{team.name} is contending but he's on their bench"
    return 0.15, f"{team.name} is contending and he starts for them"


def position_needs(teams: dict[int, Team], me: Team, market: Market) -> list[dict]:
    """Your starters' average win-now value by position vs the league's starters."""
    out = []
    for pos in ("QB", "RB", "WR", "TE"):
        avg = {}
        for rid, t in teams.items():
            vals = [market.redraft(p) for p in t.starters if _pos(market, p) == pos]
            avg[rid] = sum(vals) / len(vals) if vals else 0.0
        order = sorted(avg, key=lambda r: -avg[r])
        rank = order.index(me.roster_id) + 1
        league = sum(avg.values()) / len(avg)
        out.append({"pos": pos, "rank": rank, "mine": round(avg[me.roster_id]), "league_avg": round(league),
                    "need": avg[me.roster_id] < league})
    return out


def my_assets(me: Team, market: Market, positions: dict[str, str], protect: set[str] | None = None) -> list[dict]:
    """What you can offer without hurting your lineup: bench players and picks.
    `protect`: players to keep regardless (e.g. this week's recommended lineup, which covers injured starters)."""
    keep = set(me.starters) | set(protect or ())
    assets = []
    for pid in me.players:
        if pid in keep or market.value(pid) <= 0:
            continue
        assets.append({"kind": "player", "id": pid, "label": (market.player(pid) or {}).get("name") or pid,
                       "pos": _pos(market, pid), "age": _age(market, pid),
                       "value": market.value(pid), "redraft": market.redraft(pid)})
    for p in me.picks:
        if p["value"] > 0:
            label = p["label"] + (f" (from {p['from']})" if p.get("from") else "")
            assets.append({"kind": "pick", "id": f"{p['season']}-{p['round']}-{p['original']}", "label": label,
                           "pos": None, "age": None, "value": p["value"], "redraft": 0.0})
    return sorted(assets, key=lambda a: -a["value"])


def qb_safe(me: Team, market: Market, giving: list[dict], receiving_pos: str | None) -> bool:
    """Superflex guard: keep at least MIN_QBS startable QBs after the trade."""
    gone = {a["id"] for a in giving if a["kind"] == "player"}
    qbs = [p for p in me.players if p not in gone and _pos(market, p) == "QB" and market.redraft(p) >= QB_STARTABLE]
    return len(qbs) + (1 if receiving_pos == "QB" else 0) >= MIN_QBS


def fit(asset: dict, partner: Team) -> float:
    """How much the other manager should want this asset, 0.4-1.0."""
    if partner.label == "rebuilder":
        if asset["kind"] == "pick" or (asset["age"] and asset["age"] <= YOUTH_AGE):
            return 1.0
        return 0.4 if asset["age"] and asset["age"] >= VET_AGE.get(asset["pos"], 28) - 1 else 0.7
    if partner.label == "contender":
        if asset["kind"] == "pick":
            return 0.55
        return 0.6 + 0.4 * min(1.0, asset["redraft"] / max(asset["value"], 1))
    return 0.8


def build_offer(target_value: float, target_pos: str | None, partner: Team, me: Team, market: Market,
                assets: list[dict], max_pieces: int = 3) -> dict | None:
    pool = [a for a in assets if a["value"] >= 0.08 * target_value][:24]
    best = None
    for k in range(1, max_pieces + 1):
        for combo in combinations(pool, k):
            total = sum(a["value"] for a in combo)
            if not (target_value <= total <= 1.2 * target_value):
                continue
            if max(a["value"] for a in combo) < 0.45 * target_value:
                continue  # no pile of small pieces for a star
            if not qb_safe(me, market, list(combo), target_pos):
                continue
            f = sum(fit(a, partner) * a["value"] for a in combo) / total
            key = (round(f, 2), -k, -(total / target_value))
            if best is None or key > best[0]:
                best = (key, combo, total, f)
    if not best:
        return None
    _, combo, total, f = best
    return {"assets": [{"label": a["label"], "kind": a["kind"], "value": round(a["value"]),
                        "age": a["age"], "pos": a["pos"]} for a in combo],
            "total": round(total), "ratio": round(total / target_value, 3), "fit": round(f, 2)}


def find_targets(teams: dict[int, Team], me: Team, market: Market, slots: list[str],
                 positions: dict[str, str], ppg: dict[str, float] | None = None,
                 protect: set[str] | None = None) -> dict:
    """{"targets": [...] with offers, "out_of_reach": [...] that would help but can't be matched from your surplus}"""
    assets = my_assets(me, market, positions, protect)
    contender = me.label != "rebuilder"
    my_floor = min((market.redraft(p) for p in me.starters), default=0.0)
    out = []
    for rid, t in teams.items():
        if rid == me.roster_id:
            continue
        for pid in t.players:
            mp = market.player(pid)
            if not mp or mp["value"] <= 0:
                continue
            if contender:
                if mp["redraft"] <= my_floor:
                    continue
                new = best_win_now(me.players + [pid], slots, market, positions)
                gain = sum(market.redraft(p) for p in new) - me.win_now
                if gain < 300:
                    continue
                replaced = [p for p in me.starters if p not in new]
            else:
                if not mp.get("age") or mp["age"] > 25:
                    continue
                gain, replaced = mp["value"], []
            motive, why = seller_motive(t, pid, market)
            offer = build_offer(mp["value"], mp["pos"], t, me, market, assets)
            out.append({
                "player_id": pid, "name": mp["name"], "pos": mp["pos"], "age": mp["age"], "nfl_team": mp["team"],
                "owner": t.name, "owner_label": t.label, "owner_roster_id": rid,
                "value": round(mp["value"]), "redraft": round(mp["redraft"]), "trend": mp.get("trend"),
                "fc_value": round(mp["fc_value"]) if isinstance(mp.get("fc_value"), (int, float)) else None,
                "ktc_value": round(mp["ktc_value"]) if isinstance(mp.get("ktc_value"), (int, float)) else None,
                "disagree": bool(mp.get("disagree")),
                "gain": round(gain), "motive": motive, "why": why,
                "replaces": [(market.player(p) or {}).get("name") or p for p in replaced],
                "ppg": round(ppg[pid], 1) if ppg and pid in ppg else None,
                "replaces_ppg": [round(ppg[p], 1) if ppg and p in ppg else None for p in replaced],
                "score": round(gain * motive),
                "offer": offer,
            })
    out.sort(key=lambda x: -x["score"])
    return {"targets": [x for x in out if x["offer"]][:MAX_TARGETS],
            "out_of_reach": [x for x in out if not x["offer"]][:5],
            "assets": assets}


# --------------------------------------------------------------------------- #
# Weekly run: gather data, build the report
# --------------------------------------------------------------------------- #

STATS_APP_URL = ("https://api.sleeper.com/stats/nfl/{season}?season_type=regular"
                 "&position[]=QB&position[]=RB&position[]=WR&position[]=TE")
STATS_V1_URL = "https://api.sleeper.app/v1/stats/nfl/regular/{season}"


def season_ppg(get_url, season, scoring: dict, positions: dict[str, str]) -> dict[str, float]:
    """Points per game this season in your league's scoring (Sleeper season stats)."""
    from .projections import normalize, score_stats
    for url in (STATS_APP_URL, STATS_V1_URL):
        try:
            data = normalize(get_url(url.format(season=season)))
        except Exception:
            data = {}
        if data:
            out = {}
            for pid, st in data.items():
                gp = st.get("gp") or st.get("gms_active") or 0
                if isinstance(gp, (int, float)) and gp > 0:
                    out[pid] = score_stats(st, scoring, positions.get(pid)) / gp
            return out
    return {}


def build_report(client, snap: dict, fc_rows: list[dict], ktc_rows: list[dict] | None = None,
                 ids_text: str | None = None) -> dict:
    """Everything the trades page shows. `snap` is this week's lineup snapshot (dict).
    ktc_rows: parsed KeepTradeCut values; when present, dynasty values are FantasyCalc and KTC averaged."""
    from datetime import datetime, timezone
    from .consensus import norm_name
    from .market import blend_ktc, build_profiles, parse_fantasycalc, parse_mfl_map
    lg = snap["league"]
    lid, season, week = lg["league_id"], int(snap["season"]), int(snap["week"])
    league = client.get(f"league/{lid}") or {}
    settings = league.get("settings") or {}
    rosters = client.get(f"league/{lid}/rosters") or []
    users = client.get(f"league/{lid}/users") or []
    traded = client.get(f"league/{lid}/traded_picks") or []
    trades = []
    for wk in range(1, week + 1):
        trades += [t for t in (client.get(f"league/{lid}/transactions/{wk}") or [])
                   if t.get("type") == "trade" and t.get("status") == "complete"]
    market = parse_fantasycalc(fc_rows)
    sleeper_players = client.players()
    value_sources = {"fantasycalc_players": len(market.players), "ktc": "unavailable"}
    if ktc_rows:
        names = {(norm_name(p.get("full_name") or ""), p.get("position")): pid for pid, p in sleeper_players.items()
                 if p.get("position") in ("QB", "RB", "WR", "TE")}
        market, value_sources = blend_ktc(market, fc_rows, ktc_rows, parse_mfl_map(ids_text or ""), names)
        value_sources["ktc"] = "blended"
    positions = {pid: p.get("position") for pid, p in sleeper_players.items() if p.get("position") in ("QB", "RB", "WR", "TE")}
    positions.update({pid: p["pos"] for pid, p in market.players.items() if pid not in positions})
    slots = lg["starting_slots"]
    teams = build_profiles(rosters, users, market, slots, positions, traded, trades, season,
                           int(settings.get("draft_rounds") or 4))
    me = teams[snap["me"]["roster_id"]]
    protect = {r["player"]["player_id"] for r in snap["lineup"] if r["player"]}
    for r in (snap.get("suggestion") or {}).get("lineup") or []:
        if r.get("player_id"):
            protect.add(r["player_id"])
    ppg = season_ppg(client.get_url, season, lg["scoring_settings"], positions)
    found = find_targets(teams, me, market, slots, positions, ppg, protect)
    for t in found["targets"] + found["out_of_reach"]:
        t["injury_status"] = (sleeper_players.get(t["player_id"]) or {}).get("injury_status")

    def team_row(t):
        return {"roster_id": t.roster_id, "name": t.name, "wins": t.wins, "losses": t.losses,
                "record_rank": t.record_rank, "win_now_rank": t.win_now_rank, "dynasty_rank": t.dynasty_rank,
                "age": t.age, "youth": t.youth, "label": t.label, "reasons": t.reasons,
                "picks": [p["label"] + (f" (from {p['from']})" if p.get("from") else "") for p in t.picks
                          if p["round"] <= 2]}
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "season": season, "week": week, "deadline_week": settings.get("trade_deadline"),
        "league_name": lg["name"], "me": team_row(me),
        "needs": position_needs(teams, me, market),
        "targets": found["targets"], "out_of_reach": found["out_of_reach"],
        "my_assets": [{k: a[k] for k in ("label", "kind", "value", "age", "pos")} for a in found["assets"][:12]],
        "teams": [team_row(t) for t in sorted(teams.values(), key=lambda t: t.record_rank)],
        "trades_this_season": len(trades),
        "value_sources": value_sources,
    }
