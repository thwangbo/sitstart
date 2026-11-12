"""Backtest: how many points would each approach have scored, Weeks 1-N, for every team in the league?

For each team-week, the roster is what Sleeper's matchup record shows that week. Each
approach ranks those players, the lock-free optimizer picks a legal lineup, and the
lineup is scored with the points the players actually earned (Sleeper's players_points,
already in league scoring).

Approaches
- actual:      the lineup the manager really started
- hindsight:   the best possible lineup, knowing the results (the ceiling)
- blend w:     P + w(E - P) for w = 0.0, 0.1, ... 1.0
               w = 0 is Sleeper projections alone, w = 1 is expert consensus alone

Run on GitHub (Sleeper isn't reachable from everywhere):
    python -m sitstart.backtest --username thwangbo --weeks 1-9
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

from .consensus import blend, expert_points, map_to_sleeper, parse_ecr, parse_id_map
from .optimizer import best_lineup
from .projections import fetch_projections, league_points
from .sleeper import SleeperClient, pick_league, starting_slots

WEIGHTS = [round(i / 10, 1) for i in range(11)]


def _card(pid: str, players: dict, value: float) -> dict:
    p = players.get(pid) or {}
    pos = p.get("position")
    return {"player_id": pid, "name": p.get("full_name") or pid, "position": pos,
            "fantasy_positions": p.get("fantasy_positions") or ([pos] if pos else []),
            "team": "X", "proj_pts": value}


def choose(slots: list[str], starters: list[str], pool: list[str], players: dict, value: dict[str, float]) -> list[str]:
    """Player ids of the best legal lineup by `value`."""
    lineup = []
    for i, slot in enumerate(slots):
        pid = starters[i] if i < len(starters) and starters[i] not in ("0", None) else None
        lineup.append({"slot": slot, "player": _card(pid, players, value.get(pid, 0.0)) if pid else None,
                       "locked": False})
    on = {r["player"]["player_id"] for r in lineup if r["player"]}
    bench = [_card(pid, players, value.get(pid, 0.0)) for pid in pool if pid not in on]
    return [r["player"]["player_id"] for r in best_lineup(lineup, bench) if r["player"]]


def score(pids: list[str], actual: dict[str, float]) -> float:
    return round(sum(float(actual.get(p) or 0) for p in pids), 2)


def run_week(week: int, slots: list[str], matchups: list[dict], players: dict, P: dict[str, float],
             E: dict[str, float], excluded: set[str]) -> list[dict]:
    rows = []
    for m in matchups:
        actual = {k: float(v or 0) for k, v in (m.get("players_points") or {}).items()}
        starters = m.get("starters") or []
        pool = [p for p in (m.get("players") or []) if p not in excluded or p in starters]
        if not pool:
            continue
        res = {"week": week, "roster_id": m.get("roster_id"),
               "actual": score([s for s in starters if s and s != "0"], actual),
               "hindsight": score(choose(slots, starters, pool, players, actual), actual)}
        for w in WEIGHTS:
            val = {pid: blend(P.get(pid), E.get(pid), w) for pid in pool}
            res[f"w{w:.1f}"] = score(choose(slots, starters, pool, players, val), actual)
        rows.append(res)
    return rows


def _corr(xs: list[float], ys: list[float]):
    n = len(xs)
    if n < 3:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    sy = math.sqrt(sum((y - my) ** 2 for y in ys))
    return round(sxy / (sx * sy), 3) if sx and sy else None


def diagnostics(P: dict, E: dict, matchups: list[dict], raw: dict, players: dict) -> dict:
    """Sanity checks that the projections really belong to this week.
    corr(P, actual) should be clearly positive (~0.5+) across rostered players who played."""
    actual = {}
    for m in matchups:
        actual.update({k: float(v or 0) for k, v in (m.get("players_points") or {}).items()})
    both = [pid for pid in actual if pid in P and (P[pid] > 0.5 or actual[pid] > 0)]
    cE = [pid for pid in both if pid in E]
    weeks_seen = sorted({str(s.get("_week")) for s in raw.values() if isinstance(s, dict) and s.get("_week")})[:3]
    qbs = sorted(((v, pid) for pid, v in P.items() if (players.get(pid) or {}).get("position") == "QB"), reverse=True)[:3]
    return {
        "corr_P": _corr([P[p] for p in both], [actual[p] for p in both]),
        "corr_E": _corr([E[p] for p in cE], [actual[p] for p in cE]),
        "n_players": len(both),
        "proj_week_field": ",".join(weeks_seen) or "n/a",
        "top_qbs": [f"{(players.get(pid) or {}).get('full_name', pid)} {v:.1f}" for v, pid in qbs],
    }


def summarize(rows: list[dict], my_roster_id) -> dict:
    keys = ["actual", "hindsight"] + [f"w{w:.1f}" for w in WEIGHTS]
    n = len(rows)
    tot = {k: round(sum(r[k] for r in rows), 1) for k in keys}
    mine = [r for r in rows if r["roster_id"] == my_roster_id]
    my_tot = {k: round(sum(r[k] for r in mine), 1) for k in keys}

    def paired(k, base="w0.0"):
        d = [r[k] - r[base] for r in rows]
        mean = sum(d) / n
        sd = math.sqrt(sum((x - mean) ** 2 for x in d) / (n - 1)) if n > 1 else 0.0
        return {"mean_per_team_week": round(mean, 2), "se": round(sd / math.sqrt(n), 2) if n else None,
                "wins": sum(x > 0.005 for x in d), "losses": sum(x < -0.005 for x in d)}

    best_w = max(WEIGHTS, key=lambda w: (tot[f"w{w:.1f}"], -abs(w - 0.5)))
    return {
        "team_weeks": n,
        "totals": tot,
        "per_team_week": {k: round(v / n, 2) for k, v in tot.items()} if n else {},
        "share_of_hindsight": {k: round(tot[k] / tot["hindsight"], 4) for k in keys} if tot["hindsight"] else {},
        "vs_projections_only": {f"w{w:.1f}": paired(f"w{w:.1f}") for w in WEIGHTS},
        "best_weight": best_w,
        "my_team": {"roster_id": my_roster_id, "team_weeks": len(mine), "totals": my_tot,
                    "by_week": [{k: r[k] for k in ["week", "actual", "hindsight", "w0.0", f"w{best_w:.1f}", "w1.0"]}
                                for r in sorted(mine, key=lambda r: r["week"])]},
    }


def report(s: dict, weeks: list[int]) -> str:
    t, ph = s["totals"], s["per_team_week"]
    bw = s["best_weight"]
    lines = [f"# Backtest, 2026 Weeks {weeks[0]}-{weeks[-1]}", "",
             f"All {s['team_weeks']} team-weeks in the league. Lineups chosen from each week's roster, scored with actual points.", "",
             "| Approach | Total pts | Per team-week | Share of hindsight best | vs Sleeper-only, per team-week |",
             "| --- | --- | --- | --- | --- |"]
    sh = s["share_of_hindsight"]
    lines.append(f"| Hindsight best (ceiling) | {t['hindsight']:.1f} | {ph['hindsight']:.1f} | 100% | |")
    lines.append(f"| Managers' actual lineups | {t['actual']:.1f} | {ph['actual']:.1f} | {sh['actual']:.1%} | |")
    for w in WEIGHTS:
        k = f"w{w:.1f}"
        label = {0.0: "Sleeper projections only", 1.0: "Expert consensus only"}.get(w, f"Blend, w = {w:.1f}")
        if w == bw:
            label = f"**{label} (best)**"
        v = s["vs_projections_only"][k]
        lines.append(f"| {label} | {t[k]:.1f} | {ph[k]:.1f} | {sh[k]:.1%} | "
                     f"{v['mean_per_team_week']:+.2f} (SE {v['se']:.2f}; {v['wins']}W-{v['losses']}L) |")
    m = s["my_team"]
    lines += ["", f"## Your team ({m['team_weeks']} weeks)", "",
              "| Week | Actual | Sleeper only | Best blend | Experts only | Hindsight |", "| --- | --- | --- | --- | --- | --- |"]
    for r in m["by_week"]:
        lines.append(f"| {r['week']} | {r['actual']:.1f} | {r['w0.0']:.1f} | {r[f'w{bw:.1f}']:.1f} | {r['w1.0']:.1f} | {r['hindsight']:.1f} |")
    mt = m["totals"]
    lines.append(f"| **Total** | **{mt['actual']:.1f}** | **{mt['w0.0']:.1f}** | **{mt[f'w{bw:.1f}']:.1f}** | **{mt['w1.0']:.1f}** | **{mt['hindsight']:.1f}** |")
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Backtest projection/consensus blends on past weeks.")
    ap.add_argument("--username", required=True)
    ap.add_argument("--league-id")
    ap.add_argument("--season", default="2026")
    ap.add_argument("--weeks", default="1-9", help="e.g. 1-9")
    ap.add_argument("--ecr-dir", default="backtest/ecr", help="Folder with wk{N}.csv consensus snapshots and ids.csv")
    ap.add_argument("--out", default="backtest")
    args = ap.parse_args(argv)

    a, b = (int(x) for x in args.weeks.split("-"))
    weeks = list(range(a, b + 1))
    client = SleeperClient()
    user = client.get(f"user/{args.username}") or {}
    league = pick_league(client.get(f"user/{user['user_id']}/leagues/nfl/{args.season}") or [], args.league_id)
    lid = league["league_id"]
    slots = starting_slots(league.get("roster_positions") or [])
    scoring = league.get("scoring_settings") or {}
    rosters = client.get(f"league/{lid}/rosters") or []
    my_rid = next((r["roster_id"] for r in rosters if str(r.get("owner_id")) == str(user["user_id"])), None)
    excluded = {p for r in rosters for p in (r.get("taxi") or [])}  # taxi players can't start
    players = client.players()
    positions = {pid: p.get("position") for pid, p in players.items()}
    ecr_dir = Path(args.ecr_dir)
    id_map = parse_id_map((ecr_dir / "ids.csv").read_text(encoding="utf-8"))

    rows, notes = [], {}
    for wk in weeks:
        raw, src = fetch_projections(client.get_url, args.season, wk)
        P = {pid: v["proj_pts"] for pid, v in league_points(raw, scoring, positions).items()}
        ecr_file = ecr_dir / f"wk{wk}.csv"
        E = {}
        if ecr_file.exists():
            cons = map_to_sleeper(parse_ecr(ecr_file.read_text(encoding="utf-8")), id_map, players)
            E = expert_points(cons, P, positions)
        matchups = client.get(f"league/{lid}/matchups/{wk}") or []
        notes[wk] = {"projections": src, "projected_players": len(P), "consensus_players": len(E),
                     "team_weeks": len(matchups), **diagnostics(P, E, matchups, raw, players)}
        d = notes[wk]
        print(f"Week {wk}: projections {src} ({len(P)}), consensus mapped {len(E)}, teams {len(matchups)} | "
              f"proj week field {d['proj_week_field']} | corr(P, actual) {d['corr_P']} | corr(E, actual) {d['corr_E']} | "
              f"top QBs {d['top_qbs']}")
        rows += run_week(wk, slots, matchups, players, P, E, excluded)

    s = summarize(rows, my_rid)
    s["weeks"] = weeks
    s["data_notes"] = notes
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "results.json").write_text(json.dumps({"summary": s, "rows": rows}, indent=2), encoding="utf-8")
    (out / "REPORT.md").write_text(report(s, weeks), encoding="utf-8")
    print(report(s, weeks))
    return 0


if __name__ == "__main__":
    sys.exit(main())
