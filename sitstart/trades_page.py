"""Render the trade-target report as a standalone page (trades.html)."""

from __future__ import annotations

from datetime import datetime
from html import escape

from .schedule import utc_to_pacific

CSS = """
:root{--bg:#f7f6f3;--card:#fff;--ink:#1d1d1b;--sub:#6b6a66;--line:#e6e4de;--accent:#2f5bd3;--good:#1f7a4d;--warn:#a86400;--bad:#b3261e}
@media (prefers-color-scheme:dark){:root{--bg:#151514;--card:#1f1f1d;--ink:#ecebe7;--sub:#a3a29d;--line:#33322f;--accent:#7f9cf5;--good:#5cc28f;--warn:#e0a84a;--bad:#f08a80}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.45 -apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif}
main{max-width:1120px;margin:0 auto;padding:28px 16px 48px}a{color:var(--accent)}
header h1{margin:0;font-size:24px}header p{margin:4px 0 0;color:var(--sub)}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px 18px;margin-top:16px;overflow-x:auto}
.card.accent{border-color:var(--accent);border-width:2px}
h2{font-size:16px;margin:0 0 10px}table{width:100%;border-collapse:collapse}
td{padding:8px;border-top:1px solid var(--line);vertical-align:top}tr:first-child td{border-top:none}
.head td{color:var(--sub);font-size:12px;border-top:none;padding-top:0}
.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}.sub{color:var(--sub);font-size:13px}
.pname{font-weight:600}tr.me td{font-weight:600}.small{font-size:12px}
.tag{display:inline-block;font-size:12px;padding:1px 7px;border-radius:999px;border:1px solid currentColor;white-space:nowrap}
.tag.contender{color:var(--accent)}.tag.middle{color:var(--sub)}.tag.rebuilder{color:var(--warn)}
.tag.below.avg,.tag[class~='below']{color:var(--bad)}.need-item{margin-right:18px}.tag.ok{color:var(--good)}.tag.inj{color:var(--bad)}
.offer div{white-space:nowrap}.gain{color:var(--good);font-weight:600}
.chips span{display:inline-block;margin:2px 6px 2px 0}
@media (max-width:700px){.hide-sm{display:none}td{padding:7px 5px}}
"""


def _fmt(v) -> str:
    return f"{v:,.0f}" if isinstance(v, (int, float)) else "&ndash;"


def _age(a) -> str:
    return f"{a:.0f}" if isinstance(a, (int, float)) else "?"


def _tag(label: str) -> str:
    return f'<span class="tag {escape(label)}">{escape(label)}</span>'


def _deadline(rep: dict) -> str:
    dl, wk = rep.get("deadline_week"), rep.get("week")
    if not dl:
        return ""
    left = int(dl) - int(wk)
    if left > 1:
        return f"Trade deadline: Week {dl} ({left} weeks left)"
    if left == 1:
        return f"Trade deadline: Week {dl} (next week)"
    if left == 0:
        return f"Trade deadline: this week (Week {dl})"
    return f"Trade deadline passed (Week {dl}). Targets are for the offseason."


def _target_rows(targets: list[dict]) -> str:
    rows = []
    for i, t in enumerate(targets, 1):
        o = t["offer"]
        offer = "".join(f'<div>{escape(a["label"])} <span class="sub">{_fmt(a["value"])}</span></div>' for a in o["assets"])
        ppg = ""
        if isinstance(t.get("ppg"), (int, float)):
            rep_ppg = [p for p in t.get("replaces_ppg") or [] if isinstance(p, (int, float))]
            ppg = f'<div class="sub small">{t["ppg"]:.1f} pts/game' + (
                f' vs {rep_ppg[0]:.1f} for {escape(t["replaces"][0])}' if rep_ppg and t.get("replaces") else "") + '</div>'
        replaces = f'<div class="sub small">replaces {escape(", ".join(t["replaces"]))}</div>' if t.get("replaces") else ""
        trend = t.get("trend")
        trend_s = f' <span class="sub small">{trend:+,} 30d</span>' if isinstance(trend, (int, float)) and abs(trend) >= 100 else ""
        rows.append(
            f'<tr><td class="num sub">{i}</td>'
            f'<td><span class="pname">{escape(t["name"])}</span>'
            + (f' <span class="tag inj">{escape(t["injury_status"])}</span>' if t.get("injury_status") else "")
            + f'<div class="sub small">{escape(t["pos"] or "")}, '
            f'{_age(t["age"])}, {escape(t.get("nfl_team") or "FA")}</div></td>'
            f'<td>{escape(t["owner"])} {_tag(t["owner_label"])}<div class="sub small">{escape(t["why"])}</div></td>'
            f'<td><span class="gain">+{_fmt(t["gain"])}</span>{replaces}{ppg}</td>'
            f'<td class="num">{_fmt(t["value"])}{trend_s}</td>'
            f'<td class="offer">{offer}<div class="sub small">{o["ratio"]:.0%} of his value</div></td></tr>')
    return "".join(rows)


def render(rep: dict) -> str:
    me = rep["me"]
    updated = ""
    if rep.get("generated_at"):
        local = utc_to_pacific(datetime.fromisoformat(rep["generated_at"]))
        updated = local.strftime("%a %b %d, %I:%M %p PT").replace(" 0", " ")
    needs = "".join(
        f'<span class="need-item"><b>{n["pos"]}</b> {n["rank"]}{_suffix(n["rank"])} of {len(rep["teams"])} '
        f'{_tag("below avg") if n["need"] else _tag("ok")}</span>' for n in rep["needs"])
    lens = ("You're contending, so targets are ranked on how much they improve your starting lineup this season, "
            "weighted by how likely their manager is to sell. Offers use only your bench players and picks; "
            "this week's lineup is never offered.") if me["label"] != "rebuilder" else (
            "You're rebuilding, so targets are young players ranked on dynasty value, "
            "weighted by how likely their manager is to sell.")
    targets = rep.get("targets") or []
    target_html = (f'<table><tr class="head"><td></td><td>Player</td><td>Their team</td>'
                   f'<td>Your lineup gain</td><td class="num">Market value</td><td>Suggested offer</td></tr>'
                   f'{_target_rows(targets)}</table>') if targets else '<p class="sub">No upgrades found that your surplus can pay for.</p>'
    oor = rep.get("out_of_reach") or []
    oor_html = ('<p class="sub">Would help but cost more than your bench and picks can cover: '
                + ", ".join(f'{escape(t["name"])} ({escape(t["owner"])}, value {_fmt(t["value"])})' for t in oor)
                + ". Offering a starter changes that math.</p>") if oor else ""
    chips = "".join(f'<span>{escape(a["label"])} <span class="sub">{_fmt(a["value"])}</span></span>'
                    for a in rep.get("my_assets") or [])
    team_rows = "".join(
        f'<tr class="{"me" if t["roster_id"] == me["roster_id"] else ""}">'
        f'<td>{escape(t["name"])}</td><td class="num">{t["wins"]}-{t["losses"]}</td><td>{_tag(t["label"])}</td>'
        f'<td class="num">{t["win_now_rank"]}</td><td class="num">{t["dynasty_rank"]}</td>'
        f'<td class="num hide-sm">{t["age"] if t["age"] else "&ndash;"}</td><td class="num hide-sm">{t["youth"]:.0%}</td>'
        f'<td class="sub small hide-sm">{escape(", ".join(t["picks"][:6]))}</td></tr>'
        for t in rep["teams"])
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Trade targets &middot; Week {rep["week"]}</title><style>{CSS}</style></head><body><main>
<header><p><a href="./">&larr; Lineup</a></p><h1>Trade targets &middot; Week {rep["week"]}</h1>
<p>{escape(_deadline(rep))} &middot; Updated {updated}</p></header>
<section class="card accent"><h2>Your team: {_tag(me["label"])}</h2>
<p class="sub">{escape("; ".join(me["reasons"]))}.</p>
<p class="chips">{needs}</p>
<p class="sub">{lens}</p></section>
<section class="card"><h2>Top targets</h2>{target_html}{oor_html}
<p class="sub">Lineup gain and market value use FantasyCalc's Superflex half-PPR values (win-now and dynasty). Points per game are this season's, in your league scoring.
Offers total 100&ndash;120% of the player's market value. Expect to add a little when you send 2&ndash;3 pieces for one; managers pay a premium for the single best piece.</p></section>
<section class="card"><h2>Your trade chips</h2><p class="chips">{chips}</p></section>
<section class="card"><h2>League map</h2><table>
<tr class="head"><td>Team</td><td class="num">Record</td><td>Lifecycle</td><td class="num">Win-now rank</td><td class="num">Dynasty rank</td>
<td class="num hide-sm">Avg age</td><td class="num hide-sm">Youth</td><td class="hide-sm">1st and 2nd round picks</td></tr>{team_rows}</table>
<p class="sub">Lifecycle combines standings, win-now value, dynasty value, roster age, the share of value in picks and players 24 or under, and this season's trades ({rep.get("trades_this_season", 0)} in the league).</p></section>
<p class="sub">Market values: FantasyCalc (from real dynasty trades). League data: Sleeper.</p>
</main></body></html>
"""


def _suffix(n: int) -> str:
    return "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
