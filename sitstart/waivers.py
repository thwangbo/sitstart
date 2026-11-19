"""Waiver wire targets and FAAB bids, priced from your league's own claim history.

Targets (free agents: QB/RB/WR/TE on an NFL team and on nobody's roster):
- Season adds:  how much your best lineup improves for the rest of the season
                (win-now market value) plus stash value (dynasty market value, weighted
                by your team's direction). Includes injured-starter cover.
- Streamers:    how many points he adds to this week's best lineup (Score).

FAAB bid:
- Every waiver claim this season is rebuilt from Sleeper's transactions: the winning
  bid and the bids that lost to it ("claimed by another owner"; roster-full failures
  don't count as competition).
- For a target, find past claims on players with a similar projection that week
  (same position preferred). Price = what it took to beat the runner-up on those
  claims, +$1. If comparable claims usually went uncontested, $1 is enough (a $1 bid
  beats every $0 bid regardless of waiver order). Week 1 is left out (preseason).
- Guardrails: never more than your remaining budget, a per-claim cap that keeps money
  for the weeks left, and a count of teams that can still outbid you.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass

from .consensus import blend, expert_points
from .market import best_win_now
from .optimizer import best_lineup
from .projections import fetch_projections, league_points

POSITIONS = ("QB", "RB", "WR", "TE")
LOST_TO_BID = "claimed by another owner"
K_COMPS = 8
MIN_PROJ = 2.0
MAX_ADDS = 10
MAX_STREAMERS = 6


# --------------------------------------------------------------------------- #
# League claim history
# --------------------------------------------------------------------------- #

@dataclass
class Claim:
    leg: int
    player_id: str
    winner: int
    bid: int
    runner_up: int | None          # best losing bid, None if nobody else bid
    bidders: int


def parse_claims(transactions: list[dict]) -> list[Claim]:
    """One Claim per player won on waivers, with the bids it beat."""
    groups: dict[tuple, list[dict]] = {}
    for t in transactions or []:
        if t.get("type") != "waiver":
            continue
        for pid in (t.get("adds") or {}):
            groups.setdefault((int(t.get("leg") or 0), str(pid)), []).append(t)
    out = []
    for (leg, pid), ts in groups.items():
        win = next((t for t in ts if t.get("status") == "complete"), None)
        if not win:
            continue
        lost = [int((t.get("settings") or {}).get("waiver_bid") or 0) for t in ts
                if t.get("status") == "failed" and LOST_TO_BID in ((t.get("metadata") or {}).get("notes") or "")]
        out.append(Claim(leg, pid, (win.get("roster_ids") or [None])[0],
                         int((win.get("settings") or {}).get("waiver_bid") or 0),
                         max(lost) if lost else None, 1 + len(lost)))
    return sorted(out, key=lambda c: (c.leg, c.player_id))


def market_summary(claims: list[Claim]) -> dict:
    season = [c for c in claims if c.leg > 1]
    contested = [c for c in season if c.runner_up is not None]
    return {
        "claims": len(season),
        "won_at_zero": sum(1 for c in season if c.bid == 0),
        "contested": len(contested),
        "median_contested_bid": statistics.median([c.bid for c in contested]) if contested else None,
        "median_runner_up": statistics.median([c.runner_up for c in contested]) if contested else None,
        "max_bid": max((c.bid for c in season), default=0),
    }


# --------------------------------------------------------------------------- #
# Bids
# --------------------------------------------------------------------------- #

def comparables(proj: float, pos: str | None, history: list[dict], k: int = K_COMPS) -> list[dict]:
    """Past claims on players with a similar projection that week. history rows:
    {"claim": Claim, "proj": float, "pos": str, "name": str}"""
    def dist(h):
        return abs(h["proj"] - proj) + (0 if h["pos"] == pos else 2.5)
    return sorted(history, key=dist)[:k]


def recommend_bid(comps: list[dict], hot: bool, my_left: int, others_left: list[int], weeks_left: int) -> dict:
    """Recommended and aggressive bid, with the reasoning."""
    if not comps:
        bid, aggressive, reason = 1, 3, "No comparable claims yet; $1 beats every $0 bid."
        contested_share = None
    else:
        contested = [h["claim"] for h in comps if h["claim"].runner_up is not None]
        contested_share = len(contested) / len(comps)
        if contested and (contested_share >= 0.35 or hot):
            runner = sorted(c.runner_up for c in contested)
            wins = sorted(c.bid for c in contested)
            p75 = runner[min(len(runner) - 1, int(round(0.75 * (len(runner) - 1))))]
            bid = max(1, p75 + 1)
            aggressive = max(bid + 1, wins[len(wins) // 2])
            reason = (f"{len(contested)} of {len(comps)} similar claims drew competing bids; "
                      f"${p75} beat 3 in 4 of the runners-up.")
        else:
            bid, aggressive = 1, 2 if not contested else max(2, max(c.runner_up for c in contested) + 1)
            reason = (f"Only {len(contested)} of {len(comps)} similar claims drew a competing bid. "
                      f"$1 beats every $0 bid, whatever your waiver order.")
    cap = max(1, int(my_left * (0.5 if weeks_left <= 3 else 0.35)))
    capped = bid > cap
    bid, aggressive = min(bid, cap, my_left), min(aggressive, my_left)
    can_outbid = sum(1 for b in others_left if b > bid)
    return {"bid": bid, "aggressive": max(bid, aggressive), "reason": reason, "capped": capped, "cap": cap,
            "contested_share": round(contested_share, 2) if contested_share is not None else None,
            "teams_can_outbid": can_outbid,
            "examples": [{"name": h["name"], "week": h["claim"].leg, "bid": h["claim"].bid,
                          "runner_up": h["claim"].runner_up, "proj": round(h["proj"], 1)} for h in comps[:3]]}


# --------------------------------------------------------------------------- #
# Targets
# --------------------------------------------------------------------------- #

def _card(pid: str, sp: dict, score: float) -> dict:
    pos = sp.get("position")
    return {"player_id": pid, "name": sp.get("full_name") or pid, "position": pos,
            "fantasy_positions": sp.get("fantasy_positions") or [pos], "team": sp.get("team"),
            "injury_status": sp.get("injury_status"), "score": score, "proj_pts": score}


def _lineup_total(rows) -> float:
    return sum((r["player"] or {}).get("score") or (r["player"] or {}).get("proj_pts") or 0
               for r in rows if r["player"])


def week_gain(snap: dict, add: dict, base_total: float | None = None) -> float:
    """Points this week's best lineup gains from adding `add` (Score; locks respected)."""
    if base_total is None:
        base_total = _lineup_total(best_lineup(snap["lineup"], snap["bench"]))
    return round(_lineup_total(best_lineup(snap["lineup"], snap["bench"] + [add])) - base_total, 1)


def drop_candidate(snap: dict, market, core: set[str]) -> dict | None:
    """Lowest-value bench player outside your core (not taxi or IR)."""
    bench = [c for c in snap["bench"] if c["player_id"] not in core]
    if not bench:
        return None
    worst = min(bench, key=lambda c: market.value(c["player_id"]) + 0.5 * market.redraft(c["player_id"]))
    return {"player_id": worst["player_id"], "name": worst["name"], "value": round(market.value(worst["player_id"]))}


def build_waiver_report(client, snap: dict, ctx: dict, consensus: dict | None, weight: float = 0.5) -> dict:
    """ctx from trades.build_report(..., return_context=True): market, teams, me, positions, players, slots, core."""
    from datetime import datetime, timezone
    lg = snap["league"]
    lid, season, week = lg["league_id"], snap["season"], int(snap["week"])
    league = client.get(f"league/{lid}") or {}
    st = league.get("settings") or {}
    budget = int(st.get("waiver_budget") or 100)
    rosters = client.get(f"league/{lid}/rosters") or []
    left = {r["roster_id"]: budget - int((r.get("settings") or {}).get("waiver_budget_used") or 0) for r in rosters}
    my_rid = snap["me"]["roster_id"]
    last_week = int(st.get("playoff_week_start") or 15) + 2
    weeks_left = max(1, last_week - week + 1)

    sleeper_players, market, positions = ctx["players"], ctx["market"], ctx["positions"]
    scoring = lg["scoring_settings"]

    # League history: claims + the projection each claimed player had that week
    transactions = []
    for wk in range(1, week + 1):
        transactions += client.get(f"league/{lid}/transactions/{wk}") or []
    claims = parse_claims(transactions)
    history = []
    for wk in sorted({c.leg for c in claims if c.leg > 1}):
        raw, _ = fetch_projections(client.get_url, season, wk)
        P = {pid: v["proj_pts"] for pid, v in league_points(raw, scoring, positions).items()}
        for c in claims:
            if c.leg == wk and (sleeper_players.get(c.player_id) or {}).get("position") in POSITIONS:
                history.append({"claim": c, "proj": float(P.get(c.player_id) or 0.0),
                                "pos": sleeper_players[c.player_id].get("position"),
                                "name": sleeper_players[c.player_id].get("full_name") or c.player_id})

    # This week's free agents
    rostered = {p for r in rosters for p in (r.get("players") or []) + (r.get("taxi") or []) + (r.get("reserve") or [])}
    raw, _ = fetch_projections(client.get_url, season, week)
    P = {pid: v["proj_pts"] for pid, v in league_points(raw, scoring, positions).items()}
    E = expert_points(consensus, P, positions) if consensus else {}
    try:
        trending = client.get_url("https://api.sleeper.app/v1/players/nfl/trending/add?lookback_hours=48&limit=50") or []
    except Exception:
        trending = []
    hot_rank = {str(t["player_id"]): i + 1 for i, t in enumerate(trending)}

    me = ctx["me"]
    free = []
    for pid, sp in sleeper_players.items():
        if pid in rostered or sp.get("position") not in POSITIONS or not sp.get("team"):
            continue
        if sp.get("injury_status") in ("IR", "Out", "PUP", "Sus"):
            continue
        proj = P.get(pid) or 0.0
        if proj < MIN_PROJ and market.value(pid) <= 0 and pid not in hot_rank:
            continue
        free.append(pid)

    lens_stash = 0.25 if me.label != "rebuilder" else 1.0
    others_left = [v for rid, v in left.items() if rid != my_rid]
    base_total = _lineup_total(best_lineup(snap["lineup"], snap["bench"]))
    rows = []
    for pid in free:
        sp = sleeper_players[pid]
        score = blend(P.get(pid), E.get(pid), weight) if E else (P.get(pid) or 0.0)
        if (P.get(pid) or 0) == 0:
            score = 0.0  # bye week or not expected to play
        gain_wk = week_gain(snap, _card(pid, sp, score), base_total)
        new = best_win_now(me.players + [pid], ctx["slots"], market, positions)
        ros_gain = max(0.0, sum(market.redraft(p) for p in new) - me.win_now)
        value = ros_gain + lens_stash * market.value(pid)
        if value <= 0 and gain_wk <= 0.2:
            continue
        comps = comparables(P.get(pid) or 0.0, sp.get("position"), history)
        bid = recommend_bid(comps, hot=pid in hot_rank and hot_rank[pid] <= 15, my_left=left.get(my_rid, 0),
                            others_left=others_left, weeks_left=weeks_left)
        rows.append({"player_id": pid, "name": sp.get("full_name") or pid, "pos": sp.get("position"),
                     "nfl_team": sp.get("team"), "age": sp.get("age"), "injury_status": sp.get("injury_status"),
                     "proj": round(P.get(pid) or 0.0, 1), "score": round(score, 1), "week_gain": gain_wk,
                     "ros_gain": round(ros_gain), "dynasty": round(market.value(pid)),
                     "consensus_rank": None, "hot": hot_rank.get(pid), "value": round(value), "bid": bid})
    for r in rows:
        c = (consensus or {}).get(r["player_id"])
        r["consensus_rank"] = f"{c['pos']}{c['rank']}" if c else None

    adds = sorted([r for r in rows if r["value"] > 0], key=lambda r: -r["value"])[:MAX_ADDS]
    shown = {r["player_id"] for r in adds}
    streamers = sorted([r for r in rows if r["week_gain"] >= 0.5 and r["player_id"] not in shown],
                       key=lambda r: -r["week_gain"])[:MAX_STREAMERS]
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "season": season, "week": week, "league_name": lg["name"],
        "budget": budget, "my_left": left.get(my_rid, 0), "weeks_left": weeks_left,
        "others_left": sorted(others_left, reverse=True), "teams_out_of_faab": sum(1 for v in others_left if v <= 0),
        "daily_waivers": bool(st.get("daily_waivers")), "min_bid": int(st.get("waiver_bid_min") or 0),
        "market": market_summary(claims),
        "drop": drop_candidate(snap, market, ctx.get("core") or set()),
        "adds": adds, "streamers": streamers, "free_agents_checked": len(free),
    }
