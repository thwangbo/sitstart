"""Waivers page (waivers.html) in the shared look from ui.py."""

from __future__ import annotations

from html import escape

from . import ui
from .trades_page import _age, _fmt
from .ui import icon


def _bid_more(b: dict) -> str:
    ex = "".join(
        f'<div class="row small"><span>{escape(e["name"])}, Wk {e["week"]}</span><span class="num">${e["bid"]}'
        + (f' (beat ${e["runner_up"]})' if e["runner_up"] is not None else " (no other bids)") + '</span></div>'
        for e in b.get("examples") or [])
    capped = (f'<div class="sub small">Capped at ${b["cap"]} to keep money for the weeks left.</div>'
              if b.get("capped") else "")
    outbid = (f'{b["teams_can_outbid"]} team{"s" if b["teams_can_outbid"] != 1 else ""} can still outbid this.'
              if b.get("teams_can_outbid") is not None else "")
    return (f'<div class="body">{escape(b["reason"])} {outbid}</div>{capped}'
            + (f'<div><span class="label sub">Similar claims</span><div class="lines" style="margin-top:6px">{ex}</div></div>'
               if ex else ""))


def _items(rows: list[dict], kind: str) -> str:
    out = []
    for r in rows:
        tags = ""
        if r.get("injury_status"):
            tags += f' <span class="tag bad">{escape(r["injury_status"])}</span>'
        if r.get("hot"):
            tags += f' <span class="tag good">trending #{r["hot"]}</span>'
        if kind == "adds":
            why = []
            if r["ros_gain"] > 0:
                why.append(f'<span class="gain">+{_fmt(r["ros_gain"])}</span> rest of season')
            if r["dynasty"] > 0:
                why.append(f'stash value {_fmt(r["dynasty"])}')
            why_s = " · ".join(why) or "depth"
        else:
            why_s = f'<span class="gain">+{r["week_gain"]:.1f} pts</span> this week'
        b = r["bid"]
        rank = f', experts {escape(r["consensus_rank"])}' if r.get("consensus_rank") else ""
        out.append(
            f'<details class="item"><summary><div class="row"><span><span class="pname">{escape(r["name"])}</span>{tags}</span>'
            f'<span class="title" style="margin:0">${b["bid"]}</span></div>'
            f'<div class="row sub small"><span>{escape(r["pos"] or "")} · {_age(r.get("age"))} · '
            f'{escape(r.get("nfl_team") or "FA")}{rank}</span><span>up to ${b["aggressive"]}</span></div>'
            f'<div class="body">{why_s}</div></summary>'
            f'<div class="more"><div class="sub small">This week: {r["proj"]:.1f} projected, Score {r["score"]:.1f}</div>'
            f'{_bid_more(b)}</div></details>')
    return "".join(out)


def render(rep: dict) -> str:
    m = rep["market"]
    others = rep["others_left"]
    left, budget = rep["my_left"], rep["budget"] or 100
    pct = max(0, min(100, round(left / budget * 100))) if budget else 0
    stats = [(f'{m["won_at_zero"]} of {m["claims"]}', "claims won at $0")]
    if m.get("median_contested_bid") is not None:
        stats.append((f'${m["median_contested_bid"]:.0f}', "median contested bid"))
    stats.append((f'${others[0] if others else 0}', "most another team has"))
    stat_html = "".join(f'<div><div class="title" style="margin:0;font-size:18px">{v}</div>'
                        f'<div class="sub small">{k}</div></div>' for v, k in stats)
    faab = (f'<div class="card"><div class="row"><span class="title" style="font-size:28px;margin:0">${left}'
            f' <span class="sub" style="font-size:15px;font-weight:500">of ${budget}</span></span>'
            f'<span class="sub">{rep["weeks_left"]} weeks left</span></div>'
            f'<div class="vbar" style="margin:10px 0"><i style="width:{pct}%"></i></div>'
            f'<div style="display:grid;grid-template-columns:repeat({len(stats)},minmax(0,1fr));gap:8px">{stat_html}</div></div>')

    adds, streams, rest = rep.get("adds") or [], rep.get("streamers") or [], rep.get("rest") or []
    verdict = ""
    if not adds and not streams:
        verdict = (f'<div class="note">{icon("alert", 18, 2.2)}<span><b>No bids recommended.</b> Nobody on the wire '
                   'would start for you or is worth stashing. Save the FAAB.</span></div>')
    adds_html = (f'<div class="section">Season adds</div><div class="card flush">{_items(adds, "adds")}</div>') if adds else ""
    str_html = (f'<div class="section">This week\'s streamers</div><div class="card flush">{_items(streams, "streamers")}</div>'
                ) if streams else ""
    rest_html = ""
    if rest:
        rows = "".join(
            f'<div class="trow" style="display:grid;grid-template-columns:minmax(0,1fr) 54px 44px;gap:8px;align-items:center">'
            f'<div><div class="pn">{escape(r["name"])}'
            + (f' <span class="tag bad">{escape(r["injury_status"])}</span>' if r.get("injury_status") else "")
            + f'</div><div class="meta">{escape(r["pos"] or "")} · {escape(r.get("nfl_team") or "FA")}</div></div>'
            f'<span class="c3 r">{r["proj"]:.1f}</span><b class="r">${r["bid"]["bid"]}</b></div>' for r in rest)
        rest_html = ('<div class="card flush"><div class="thead" style="display:grid;grid-template-columns:minmax(0,1fr) 54px 44px;'
                     'gap:8px"><span>DEPTH ONLY</span><span class="r">PROJ</span><span class="r">BID</span></div>'
                     f'{rows}</div>')
    drop = rep.get("drop")
    drop_html = (f'<div class="body" style="padding:0 4px">If you need a roster spot, the cheapest drop is '
                 f'<b>{escape(drop["name"])}</b>.</div>') if drop else ""
    econ = (f'{m["claims"]} claims since Week 2, {m["contested"]} with competing bids'
            + (f' (median runner-up ${m["median_runner_up"]:.0f})' if m.get("median_runner_up") is not None else "")
            + f'; biggest bid ${m["max_bid"]}. {rep["teams_out_of_faab"]} teams are out of FAAB. ')
    body = f"""<div class="stack">
{faab}
{verdict}
{adds_html}
{str_html}
{rest_html}
{drop_html}
{ui.footer(econ + "Bids come from your league's own claims on players with a similar projection that week: $1 more "
           "than what beat 3 in 4 runners-up when similar claims drew competition, otherwise $1, which beats every $0 bid. "
           "Bids are capped by what the player is worth to you ($1 for depth, 10% of your budget for a stash) and by "
           "what you need for the weeks left. A player with no waiver clock is a free agent: just add him.")}
</div>"""
    cadence = "waivers run daily" if rep.get("daily_waivers") else "waivers run weekly"
    return ui.page(f"Waivers &middot; Week {rep['week']}", "waivers", f"Week {rep['week']} · {cadence}", "Waivers",
                   rep.get("generated_at"), body)
