"""Trade targets (v2 trade finder, part 2).

Lens follows your team's lifecycle:
- contender: buy this-season production (win-now value) cheaply in dynasty value,
  ideally veterans on rebuilding teams, paying with picks and players outside your core
- rebuilder: buy dynasty value (young players), ideally surplus on contending teams

For each player on another roster:
  gain    = how much your best starting lineup improves with him (win-now value), or his
            dynasty value for a rebuilder
  motive  = how likely his manager is to sell (their lifecycle, his age, whether he starts for them)
  score   = gain x motive
Then an offer is built from players outside your core (your best lineup, plus whoever is
filling in for injured starters) and picks, at 100-120% of his
market value (+8% per extra piece), shaped to what the other manager needs: picks and young players for a
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
    """How likely his manager is to sell, from their lifecycle and his age only.
    Whether he's on their bench is deliberately ignored: a benched player is often hurt,
    on bye or in a tough matchup, not surplus."""
    age, pos = _age(market, pid), _pos(market, pid)
    vet = bool(age) and age >= VET_AGE.get(pos, 28) - 1
    if team.label == "rebuilder":
        if vet:
            return 1.0, f"{team.name} is rebuilding and he's {age:.0f}"
        return 0.6, f"{team.name} is rebuilding, but he's young, so expect to pay full price"
    if team.label == "middle":
        if vet:
            return 0.5, f"{team.name} is in the middle and he's {age:.0f}"
        return 0.35, f"{team.name} is in the middle; he's young enough that they'll want a premium"
    return 0.2, f"{team.name} is contending, so they'll want help now in return"


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


def core_players(me: Team, market: Market, slots: list[str], positions: dict[str, str],
                 protect: set[str] | None = None, unavailable: set[str] | None = None) -> set[str]:
    """Players you shouldn't trade away for help elsewhere:
    - your best lineup at full health (season-long win-now values)
    - the best lineup without your currently injured players, i.e. who's filling in for them
    - anyone in `protect` (this week's recommended lineup)"""
    healthy = [p for p in me.players if p not in (unavailable or set())]
    fill_ins = best_win_now(healthy, slots, market, positions) if slots else []
    return set(me.starters) | set(fill_ins) | set(protect or ())


def my_assets(me: Team, market: Market, positions: dict[str, str], protect: set[str] | None = None,
              core: set[str] | None = None) -> list[dict]:
    """What you can offer: players outside your core, and picks."""
    keep = set(me.starters) | set(protect or ()) | set(core or ())
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
    """Superflex guard: a trade may not leave you with fewer than MIN_QBS startable QBs,
    unless it doesn't reduce the number you already have (if you're already short, a trade
    that doesn't touch your QBs is still fine)."""
    startable = [p for p in me.players if _pos(market, p) == "QB" and market.redraft(p) >= QB_STARTABLE]
    gone = {a["id"] for a in giving if a["kind"] == "player"}
    after = len([p for p in startable if p not in gone]) + (1 if receiving_pos == "QB" else 0)
    return after >= MIN_QBS or after >= len(startable)


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


CONSOLIDATION = 0.08   # extra value needed per additional piece (the other manager gives up roster quality)


def build_offer(target_value: float, target_pos: str | None, partner: Team, me: Team, market: Market,
                assets: list[dict], max_pieces: int = 3) -> dict | None:
    """Cheapest sensible package. Rules:
    - total >= target x (1 + 8% per extra piece), and <= that + 20%
    - the best piece is worth at least half the target (no pile of depth pieces for a star)
    - prefer what the other manager wants (fit), then giving up the least win-now depth
      (a player on your bench still has value as injury and bye cover), then fewer pieces,
      then the smallest overpay"""
    pool = [a for a in assets if a["value"] >= 0.08 * target_value][:24]
    best = None
    for k in range(1, max_pieces + 1):
        need = target_value * (1 + CONSOLIDATION * (k - 1))
        for combo in combinations(pool, k):
            total = sum(a["value"] for a in combo)
            if not (need <= total <= need * 1.2):
                continue
            if max(a["value"] for a in combo) < 0.5 * target_value:
                continue
            if not qb_safe(me, market, list(combo), target_pos):
                continue
            f = sum(fit(a, partner) * a["value"] for a in combo) / total
            depth = sum(a["redraft"] for a in combo if a["kind"] == "player")   # win-now value you give up
            key = (round(f, 1), -round(depth / 500), -k, -abs(total / need - 1.0))
            if best is None or key > best[0]:
                best = (key, combo, total, f)
    if not best:
        return None
    _, combo, total, f = best
    return _offer_dict(combo, total, target_value, f)


def _offer_dict(combo, total: float, target_value: float, f: float) -> dict:
    return {"assets": [{"id": a["id"], "label": a["label"], "kind": a["kind"], "value": round(a["value"]),
                        "age": a["age"], "pos": a["pos"], "core": bool(a.get("core"))} for a in combo],
            "total": round(total), "ratio": round(total / target_value, 3), "fit": round(f, 2)}


def find_targets(teams: dict[int, Team], me: Team, market: Market, slots: list[str],
                 positions: dict[str, str], ppg: dict[str, float] | None = None,
                 protect: set[str] | None = None, unavailable: set[str] | None = None) -> dict:
    """{"targets": [...] with offers, "out_of_reach": [...] that would help but can't be matched from your surplus}"""
    core = core_players(me, market, slots, positions, protect, unavailable)
    assets = my_assets(me, market, positions, protect, core)
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
    targets = [x for x in out if x["offer"]][:MAX_TARGETS]
    flag_reuse(targets, teams, me, market, assets)
    unreachable = [x for x in out if not x["offer"]]
    swings = bigger_swings(teams, me, market, slots, positions, unreachable, assets, core, ppg)
    return {"targets": targets, "out_of_reach": unreachable[:5], "bigger_swings": swings, "assets": assets}


def flag_reuse(targets: list[dict], teams: dict[int, Team], me: Team, market: Market, assets: list[dict]) -> None:
    """Each offer is built on its own, so one pick can appear in several. Mark shared pieces and,
    where possible, add the next-best package without them (`alt_offer`)."""
    from collections import Counter
    uses = Counter(a["id"] for t in targets for a in t["offer"]["assets"])
    for t in targets:
        shared = [a for a in t["offer"]["assets"] if uses[a["id"]] > 1]
        t["shared"] = [{"label": a["label"], "offers": uses[a["id"]]} for a in shared]
        t["alt_offer"] = None
        if shared:
            drop = {a["id"] for a in shared}
            rest = [a for a in assets if a["id"] not in drop]
            t["alt_offer"] = build_offer(t["value"], t["pos"], teams[t["owner_roster_id"]], me, market, rest)


SWING_MIN_GAIN = 300      # net win-now gain needed for a starter-inclusive trade to be worth showing
MAX_SWINGS = 5


def _player_asset(pid: str, market: Market, core: bool) -> dict:
    mp = market.player(pid) or {}
    return {"kind": "player", "id": pid, "label": mp.get("name") or pid, "pos": mp.get("pos"), "age": mp.get("age"),
            "value": market.value(pid), "redraft": market.redraft(pid), "core": core}


def bigger_swings(teams: dict[int, Team], me: Team, market: Market, slots: list[str], positions: dict[str, str],
                  candidates: list[dict], assets: list[dict], core: set[str], ppg: dict[str, float] | None,
                  max_extra: int = 2) -> list[dict]:
    """Two-for-ones for players your surplus can't reach: one of your core players plus up to two other
    pieces. Kept only if your best lineup still improves after losing the core player."""
    core_assets = [_player_asset(pid, market, True) for pid in core if market.value(pid) > 0]
    out = []
    for x in candidates[:10]:
        T = x["value"]
        partner = teams[x["owner_roster_id"]]
        others = [a for a in assets if a["value"] >= 0.08 * T][:16]
        best = None
        for c in core_assets:
            for k_extra in range(0, max_extra + 1):
                for extra in combinations(others, k_extra):
                    combo = [c, *extra]
                    k = len(combo)
                    need = T * (1 + CONSOLIDATION * (k - 1))
                    total = sum(a["value"] for a in combo)
                    if not (need <= total <= need * 1.25):
                        continue
                    if max(a["value"] for a in combo) < 0.5 * T:
                        continue
                    if not qb_safe(me, market, combo, x["pos"]):
                        continue
                    gone = {a["id"] for a in combo if a["kind"] == "player"}
                    after = [p for p in me.players if p not in gone] + [x["player_id"]]
                    new = best_win_now(after, slots, market, positions)
                    net = sum(market.redraft(p) for p in new) - me.win_now
                    if net < SWING_MIN_GAIN:
                        continue
                    f = sum(fit(a, partner) * a["value"] for a in combo) / total
                    key = (round(net / 250), round(f, 1), -k, -total)
                    if best is None or key > best[0]:
                        best = (key, combo, total, f, net)
        if best:
            _, combo, total, f, net = best
            gives = [a for a in combo if a.get("core")]
            out.append({**{k: x[k] for k in ("player_id", "name", "pos", "age", "nfl_team", "owner", "owner_label",
                                              "owner_roster_id", "value", "fc_value", "ktc_value", "disagree",
                                              "motive", "why", "ppg")},
                        "injury_status": x.get("injury_status"),
                        "net_gain": round(net), "score": round(net * x["motive"]),
                        "gives_starter": [{"name": a["label"], "ppg": round(ppg[a["id"]], 1) if ppg and a["id"] in ppg else None}
                                          for a in gives],
                        "offer": _offer_dict(combo, total, T, f)})
    out.sort(key=lambda s: -s["score"])
    return out[:MAX_SWINGS]


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
    unavailable = {pid for pid in me.players
                   if (sleeper_players.get(pid) or {}).get("injury_status") in ("Out", "IR", "PUP", "Sus", "Doubtful")}
    found = find_targets(teams, me, market, slots, positions, ppg, protect, unavailable)
    for t in found["targets"] + found["out_of_reach"] + found["bigger_swings"]:
        t["injury_status"] = (sleeper_players.get(t["player_id"]) or {}).get("injury_status")
        for offer in (t.get("offer"), t.get("alt_offer")):
            for a in (offer or {}).get("assets", []):
                if a.get("kind") == "player":
                    a["injury_status"] = (sleeper_players.get(a["id"]) or {}).get("injury_status")

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
        "targets": found["targets"], "out_of_reach": found["out_of_reach"], "bigger_swings": found["bigger_swings"],
        "my_assets": [{k: a[k] for k in ("label", "kind", "value", "age", "pos")} for a in found["assets"][:12]],
        "teams": [team_row(t) for t in sorted(teams.values(), key=lambda t: t.record_rank)],
        "trades_this_season": len(trades),
        "value_sources": value_sources,
    }
