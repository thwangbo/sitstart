"""Render the waiver report as waivers.html."""

from __future__ import annotations

from datetime import datetime
from html import escape

from . import pwa
from .schedule import utc_to_pacific
from .trades_page import CSS, _age, _fmt


def _bid_cell(b: dict) -> str:
    ex = "".join(
        f'<div class="sub small">{escape(e["name"])}, Wk {e["week"]}: ${e["bid"]}'
        + (f' (beat ${e["runner_up"]})' if e["runner_up"] is not None else " (no other bids)") + '</div>'
        for e in b.get("examples") or [])
    warn = ""
    if b.get("capped"):
        warn += f'<div class="sub small">Capped at ${b["cap"]} to keep money for the weeks left.</div>'
    outbid = (f'<div class="sub small">{b["teams_can_outbid"]} team{"s" if b["teams_can_outbid"] != 1 else ""} '
              f'can still outbid this.</div>')
    return (f'<td class="bid"><div><span class="big">${b["bid"]}</span> '
            f'<span class="sub small">up to ${b["aggressive"]} if you really want him</span></div>'
            f'<div class="sub small">{escape(b["reason"])}</div>{outbid}{warn}'
            f'<div class="sub small comps">Similar claims:</div>{ex}</td>')


def _player_cell(r: dict) -> str:
    tags = ""
    if r.get("injury_status"):
        tags += f' <span class="tag inj">{escape(r["injury_status"])}</span>'
    if r.get("hot"):
        tags += f' <span class="tag hot">trending #{r["hot"]}</span>'
    rank = f', experts {escape(r["consensus_rank"])}' if r.get("consensus_rank") else ""
    return (f'<td><span class="pname">{escape(r["name"])}</span>{tags}'
            f'<div class="sub small">{escape(r["pos"] or "")}, {_age(r.get("age"))}, {escape(r.get("nfl_team") or "FA")}{rank}</div></td>')


def _rows(rows: list[dict], kind: str) -> str:
    out = []
    for r in rows:
        if kind == "adds":
            why = []
            if r["ros_gain"] > 0:
                why.append(f'<span class="gain">+{_fmt(r["ros_gain"])}</span> rest-of-season lineup value')
            if r["dynasty"] > 0:
                why.append(f'stash value {_fmt(r["dynasty"])}')
            mid = "<br>".join(why) or '<span class="sub">depth</span>'
        else:
            mid = f'<span class="gain">+{r["week_gain"]:.1f} pts</span> this week'
        out.append(f'<tr>{_player_cell(r)}<td>{mid}<div class="sub small">This week: {r["proj"]:.1f} projected, '
                   f'Score {r["score"]:.1f}</div></td>{_bid_cell(r["bid"])}</tr>')
    return "".join(out)


def render(rep: dict) -> str:
    updated = ""
    if rep.get("generated_at"):
        local = utc_to_pacific(datetime.fromisoformat(rep["generated_at"]))
        updated = local.strftime("%a %b %d, %I:%M %p PT").replace(" 0", " ")
    m = rep["market"]
    econ = (f'{m["claims"]} waiver claims since Week 2: {m["won_at_zero"]} won with a $0 bid, '
            f'{m["contested"]} drew competing bids'
            + (f' (median winning bid ${m["median_contested_bid"]:.0f}, median runner-up ${m["median_runner_up"]:.0f})'
               if m.get("median_contested_bid") is not None else "")
            + f'. Biggest bid: ${m["max_bid"]}.')
    others = rep["others_left"]
    budget_line = (f'You have <b>${rep["my_left"]}</b> of ${rep["budget"]} left with {rep["weeks_left"]} weeks to go '
                   f'(through Week {int(rep["week"]) + rep["weeks_left"] - 1}). '
                   f'{rep["teams_out_of_faab"]} teams are out of FAAB; the most any other team has is ${others[0] if others else 0}.')
    drop = rep.get("drop")
    drop_line = (f'<p class="sub">If your roster is full, the cheapest drop is <b>{escape(drop["name"])}</b> '
                 f'(market value {_fmt(drop["value"])}), the lowest-value bench player outside your core.</p>') if drop else ""
    head = ('<tr class="head"><td>Player</td><td>Why</td><td>Bid</td></tr>')
    adds = rep.get("adds") or []
    streamers = rep.get("streamers") or []
    adds_html = (f'<table class="ttable wtable">{head}{_rows(adds, "adds")}</table>' if adds
                 else '<p class="sub">Nobody on the wire improves your lineup for the rest of the season or is worth '
                      'stashing. That\'s normal in a league this deep.</p>')
    rest = rep.get("rest") or []
    rest_html = ""
    if rest:
        items = "".join(
            f'<tr><td><span class="pname">{escape(r["name"])}</span>'
            + (f' <span class="tag inj">{escape(r["injury_status"])}</span>' if r.get("injury_status") else "")
            + f'<div class="sub small">{escape(r["pos"] or "")}, {escape(r.get("nfl_team") or "FA")}</div></td>'
            f'<td class="num">{r["proj"]:.1f}</td><td class="num">{_fmt(r["dynasty"])}</td>'
            f'<td class="num">${r["bid"]["bid"]}</td></tr>' for r in rest)
        rest_html = ('<section class="card"><h2>Best of the rest <span class="sub">depth only</span></h2>'
                     '<table><tr class="head"><td>Player</td><td class="num">Proj this week</td>'
                     '<td class="num">Market value</td><td class="num">Bid</td></tr>'
                     f'{items}</table><p class="sub">None of these would start for you. Worth a $1 claim only to cover '
                     'an injury or bye.</p></section>')
    str_html = (f'<table class="ttable wtable">{head}{_rows(streamers, "streamers")}</table>' if streamers
                else '<p class="sub">No free agent beats your current starters this week.</p>')
    extra_css = (".big{font-size:20px;font-weight:700}.tag.hot{color:var(--accent)}.bid{min-width:240px}"
                 ".comps{margin-top:6px}"
                 "@media (max-width:700px){.wtable td:nth-child(2)::before{content:'Why ';color:var(--sub);font-size:12px}"
                 ".wtable td:last-child::before{content:'Bid';display:block;color:var(--sub);font-size:12px}"
                 ".wtable td:nth-last-child(3)::before,.wtable td:nth-last-child(2)::before{content:none}}")
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Waivers &middot; Week {rep["week"]}</title>{pwa.HEAD}<style>{CSS}{pwa.CSS}{extra_css}</style></head><body><main>
{pwa.appbar(rep.get("generated_at"))}
<header><p><a href="./">&larr; Lineup</a> &middot; <a href="trades.html">Trade targets</a></p><h1>Waivers &middot; Week {rep["week"]}</h1>
<p>Updated {updated}</p></header>
<section class="card accent"><h2>Your FAAB</h2><p>{budget_line}</p><p class="sub">{econ}</p>{drop_line}
<p class="sub">Waivers run {"daily" if rep.get("daily_waivers") else "weekly"}. If Sleeper shows a player as a free agent
(no waiver clock), just add him; no bid needed.</p></section>
<section class="card"><h2>Season adds</h2>{adds_html}
<p class="sub">Ranked on how much your best lineup improves for the rest of the season (win-now market value), plus
stash value for players who could matter beyond this year.</p></section>
<section class="card"><h2>This week's streamers</h2>{str_html}
<p class="sub">Points added to this week's best lineup, using the same Score as your lineup page.</p></section>
{rest_html}
<section class="card"><h2>How bids are priced</h2><p class="sub">Each bid comes from your league's own claims this season.
For every target, the app finds past claims on players with a similar projection that week, same position preferred,
and bids $1 more than what beat 3 in 4 of the runners-up. When similar claims usually went uncontested, $1 is enough,
because it beats every $0 bid regardless of waiver order. Bids are also capped by what the player is worth to you:
$1 for depth, 10% of your budget for a stash, and a share of what's left for the weeks remaining.</p></section>
</main>{pwa.SCRIPT}</body></html>
"""
