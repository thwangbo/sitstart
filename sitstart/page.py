"""Today (home) and Lineup pages, in the shared look from ui.py."""

from __future__ import annotations

from html import escape

from . import ui
from .sleeper import card_value
from .ui import fmt, icon, pt, pts

FLAG_WORDS = {
    "EMPTY_SLOT": "Empty slot",
    "STARTER_ON_BYE": "On bye",
    "STARTER_OUT": "Out",
    "STARTER_IR": "On IR",
    "STARTER_DOUBTFUL": "Doubtful",
    "STARTER_SUS": "Suspended",
    "STARTER_PUP": "PUP",
    "NO_NFL_TEAM": "No NFL team",
    "INELIGIBLE_FOR_SLOT": "Can't play this slot",
}
SLOT_SHORT = {"SUPER_FLEX": "SF", "FLEX": "FLX", "REC_FLEX": "RFX", "WRRB_FLEX": "W/R", "IDP_FLEX": "IDP"}
INJURED = ("Out", "IR", "Doubtful", "PUP", "Sus")


def _slot(s: str) -> str:
    return SLOT_SHORT.get(s, s.replace("_", " ")[:4])


def _status(card: dict | None, flag: str | None = None, locked: bool = False) -> str:
    tags = []
    if flag and flag in FLAG_WORDS:
        tags.append(f'<span class="tag bad">{FLAG_WORDS[flag]}</span>')
    elif card and card.get("bye"):
        tags.append('<span class="tag muted">Bye</span>')
    elif card and card.get("injury_status"):
        cls = "warn" if card["injury_status"] == "Questionable" else "bad"
        tags.append(f'<span class="tag {cls}">{escape(card["injury_status"])}</span>')
    elif card and not card.get("team"):
        tags.append('<span class="tag muted">No team</span>')
    return " ".join(tags)   # "locked" is shown in the game line instead of a tag


def _meta(card: dict, slot: str = "", locked: bool = False) -> str:
    """Short game line: position only where the slot doesn't say it, then game, then kickoff or 'locked'."""
    parts = []
    if slot not in ("QB", "RB", "WR", "TE", "K", "DEF"):
        parts.append(escape(card.get("position") or ""))
    game = " ".join(x for x in (card.get("team"), card.get("opponent")) if x)
    if game:
        parts.append(escape(game))
    if locked or card.get("locked"):
        parts.append("locked")
    else:
        when = pt(card.get("kickoff_utc"), "%a %-I:%M%p").replace("AM", "a").replace("PM", "p")
        if when:
            parts.append(when)
    return " · ".join(p for p in parts if p)


def _row(slot: str, card: dict | None, flag: str | None = None, locked: bool = False, scale: float = 25.0) -> str:
    if not card:
        return (f'<div class="grid5 trow"><span class="slot">{escape(slot)}</span>'
                f'<div><div class="pn">Empty</div><div class="meta">{_status(None, flag)}</div></div>'
                '<span></span><span></span><div class="sc"><b>&ndash;</b></div></div>')
    v = card_value(card)
    width = 0 if not isinstance(v, (int, float)) or scale <= 0 else max(0, min(100, round(v / scale * 100)))
    tags = _status(card, flag, False)
    return (f'<div class="grid5 trow"><span class="slot">{escape(slot)}</span>'
            f'<div style="min-width:0"><div class="pn">{escape(card["name"])}</div>'
            f'<div class="meta">{_meta(card, slot, locked)}{" " + tags if tags else ""}</div></div>'
            f'<span class="c3 r">{pts(card.get("proj_pts"))}</span><span class="c3 r">{pts(card.get("expert_pts"))}</span>'
            f'<div class="sc"><b>{pts(v)}</b><div class="bar"><i style="width:{width}%"></i></div></div></div>')


def _table(rows: str, head_slot: str = "SLOT") -> str:
    return (f'<div class="card flush"><div class="grid5 thead"><span>{head_slot}</span><span>PLAYER</span>'
            f'<span class="r">SLPR</span><span class="r">EXP</span><span class="r">SCORE</span></div>{rows}</div>')


def _totals(snap: dict) -> tuple[float, float | None]:
    mine = sum(card_value(r["player"]) or 0 for r in snap["lineup"])
    opp = snap.get("opponent") or {}
    return mine, opp.get("proj_total")


def _scoreboard(snap: dict, in_hero: bool = False) -> str:
    mine, theirs = _totals(snap)
    me_name = escape(snap["me"].get("team_name") or snap["me"].get("display_name") or "You")
    opp = snap.get("opponent") or {}
    if theirs is None:
        return (f'<div class="score3"><div><div class="nm">{me_name}</div><div class="big me">{mine:.1f}</div></div>'
                '<div class="mid"><span class="small">projected</span></div><div></div></div>')
    diff = mine - theirs
    opp_name = escape(opp.get("team_name") or opp.get("display_name") or "Opponent")
    return (f'<div class="score3"><div><div class="nm">{me_name}</div><div class="big me">{mine:.1f}</div></div>'
            f'<div class="mid"><b class="{"" if diff >= 0 else "behind"}">{diff:+.1f}</b><span class="small sub">projected</span></div>'
            f'<div class="r"><div class="nm">{opp_name}</div><div class="big">{theirs:.1f}</div></div></div>')


def _moves(sug: dict) -> list[str]:
    starts, sits = sug.get("start") or [], sug.get("sit") or []
    out = []
    for i, c in enumerate(starts):
        over = f" over {escape(sits[i]['name'])}" if i < len(sits) else ""
        q = " (Questionable)" if c.get("injury_status") == "Questionable" else ""
        out.append(f"Start <b>{escape(c['name'])}</b>{q}{over}")
    for c in sits[len(starts):]:
        out.append(f"Bench <b>{escape(c['name'])}</b>")
    if not out and sug.get("slot_moves"):
        out.append("Rearrange slots: " + escape(", ".join(f'{_slot(r["slot"])} {r["name"]}' for r in sug["lineup"] if r["name"])))
    return out


def _verdict(sug: dict | None) -> str:
    if not sug:
        return f'<div class="strip warn">{icon("alert", 16, 2.4)}Projections unavailable this run</div>'
    if not sug.get("actionable"):
        return f'<div class="strip ok">{icon("check", 16, 2.6)}Best lineup · no changes</div>'
    rows = "".join(f'<div class="row"><span>{m}</span></div>' for m in _moves(sug))
    slots = ""
    if sug.get("slot_moves"):
        slots = ('<div class="sub small">Then set slots: ' + escape(", ".join(
            f'{_slot(r["slot"])} {r["name"]}' for r in sug["lineup"] if r["name"])) + "</div>")
    return (f'<div class="card"><div class="row"><span class="label warn">Make these changes</span>'
            f'<span class="gain">+{sug["gain"]:.1f} pts</span></div><div class="lines" style="margin-top:8px">{rows}</div>'
            f'{slots}<div class="sub small" style="margin-top:6px">Questionable players are discounted 15%.</div></div>')


def _stats_view_note(snap: dict) -> str:
    sv, sug = snap.get("stats_view"), snap.get("suggestion") or {}
    if not sv or not sv.get("actionable"):
        return ""
    main = {c["player_id"] for c in sug.get("start", [])} if sug.get("actionable") else set()
    if {c["player_id"] for c in sv["start"]} == main:
        return ""
    starts = ", ".join(escape(c["name"]) for c in sv["start"])
    sits = ", ".join(escape(c["name"]) for c in sv["sit"])
    return ('<div class="card"><span class="label sub">Stats view · not applied</span>'
            f'<div class="body" style="margin-top:4px">Usage and matchup data would start <b>{starts}</b>'
            + (f' over <b>{sits}</b>' if sits else '') + '. Shown for comparison until the report card shows it '
            'beating the app.</div></div>')


def _report_card(grades: list[dict]) -> str:
    if not grades:
        return ""
    from .grades import stats_streak
    rows = "".join(
        f'<tr class="{"bt" if g.get("source") == "backtest" else ""}"><td>Wk {g["week"]}</td>'
        f'<td class="r">{pts(g.get("you"))}</td><td class="r">{pts(g.get("app"))}</td><td class="r">{pts(g.get("sleeper"))}</td>'
        f'<td class="r">{pts(g.get("stats"))}</td><td class="r">{pts(g.get("best"))}</td></tr>'
        for g in sorted(grades, key=lambda g: -g["week"]))
    tot = lambda k: sum(g.get(k) or 0 for g in grades)
    note = ("Stats view has beaten the app 3 weeks running. Consider switching it on."
            if stats_streak(grades) else
            "Gray rows are backtest weeks (before the app existed, no injury info). Stats view is shadow-only.")
    return ('<details class="fold"><summary><h2>Report card</h2><span class="twisty"><span class="o">Show</span>'
            '<span class="c">Hide</span></span></summary><div class="in">'
            '<table class="plain"><tr class="h"><td>Week</td><td class="r">You</td><td class="r">App</td>'
            '<td class="r">Sleeper</td><td class="r">Stats</td><td class="r">Best</td></tr>'
            f'{rows}<tr class="tot"><td>Season</td><td class="r">{tot("you"):.1f}</td><td class="r">{tot("app"):.1f}</td>'
            f'<td class="r">{tot("sleeper"):.1f}</td><td class="r">&ndash;</td><td class="r">{tot("best"):.1f}</td></tr></table>'
            f'<p class="sub small">Points your lineup scored under each approach. {note}</p></div></details>')


def _blend_note(ds: dict) -> str:
    if ds.get("consensus_players"):
        w = ds.get("blend_weight", 0.5)
        return (f"Score blends Sleeper's projection in your scoring ({1 - w:.0%}) with the expert consensus ({w:.0%}, "
                f"FantasyPros via DynastyProcess, {ds.get('consensus_scrape_date')}). SLPR = Sleeper, EXP = experts.")
    return "Score = Sleeper projection in your league scoring. Expert consensus was unavailable this run."


def render(snap: dict) -> str:
    """The Lineup page (lineup.html)."""
    ds = snap.get("data_status") or {}
    starters = [r for r in snap["lineup"]]
    scale = max([card_value(r["player"]) or 0 for r in starters] + [1.0])
    rows = "".join(_row(_slot(r["slot"]), r["player"], r["flag"], r.get("locked"), scale) for r in starters)
    mine, _ = _totals(snap)
    rows += (f'<div class="grid5 trow"><span></span><b class="pn">Projected total</b><span></span><span></span>'
             f'<div class="sc"><b>{mine:.1f}</b></div></div>')

    bench = sorted(snap["bench"], key=lambda c: -(card_value(c) or 0))
    top3 = " · ".join(f'{escape(c["name"])} {pts(card_value(c))}' for c in bench[:3] if (card_value(c) or 0) > 0)
    hurt = {}
    for c in bench + list(snap.get("reserve") or []):
        s = c.get("injury_status") or ("IR" if c in (snap.get("reserve") or []) else None)
        if s in INJURED:
            hurt.setdefault(s, []).append(escape(c["name"]))
    hurt_line = " · ".join(f'{s}: {", ".join(n)}' for s, n in hurt.items())
    bench_rows = "".join(_row("BN", c, scale=scale) for c in bench)
    taxi = ", ".join(escape(c["name"]) for c in snap.get("taxi") or [])
    bench_html = (f'<details class="fold"><summary><div><h2>Bench</h2><div class="sub small">{top3 or "No bench points"}</div>'
                  + (f'<div class="small" style="color:var(--warn)">{hurt_line}</div>' if hurt_line else "")
                  + f'</div><span class="twisty"><span class="o">All {len(bench)}</span><span class="c">Hide</span></span>'
                  f'</summary><div class="in">{_table(bench_rows, "")}'
                  + (f'<p class="sub small">Taxi: {taxi}</p>' if taxi else "") + '</div></details>')

    opp_html = ""
    opp = snap.get("opponent")
    if opp:
        oscale = max([card_value(r["player"]) or 0 for r in opp["lineup"]] + [1.0])
        orows = "".join(_row(_slot(r["slot"]), r["player"], r["flag"], r.get("locked"), oscale) for r in opp["lineup"])
        opp_html = (f'<details class="fold"><summary><h2>{escape(opp.get("team_name") or "Opponent")} '
                    f'<span class="sub">{pts(opp.get("proj_total"))}</span></h2><span class="twisty"><span class="o">Show lineup</span>'
                    f'<span class="c">Hide</span></span></summary><div class="in">{_table(orows)}</div></details>')

    byes = ", ".join(ds.get("bye_teams") or []) or "none"
    body = f"""<div class="stack">
<div class="card">{_scoreboard(snap)}</div>
{_verdict(snap.get("suggestion"))}
{_stats_view_note(snap)}
{_table(rows)}
{bench_html}
{opp_html}
{_report_card(snap.get("grades") or [])}
{ui.footer(escape(_blend_note(ds)) + f' Projections: Sleeper ({escape(str(ds.get("projections_source")))}, '
           f'{ds.get("projections_count")} players). Byes: {escape(byes)}. Times are Pacific.')}
</div>"""
    return ui.page(f"Lineup &middot; Week {snap['week']}", "lineup",
                   f"Week {snap['week']}", "Lineup", snap.get("generated_at"), body)


def _record(trades: dict | None) -> str:
    me = (trades or {}).get("me") or {}
    if "wins" not in me:
        return ""
    r = me.get("record_rank")
    suffix = "th" if r and 10 <= r % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get((r or 0) % 10, "th")
    return f" · {me['wins']}-{me['losses']}" + (f", {r}{suffix}" if r else "")


def _trade_card(trades: dict | None) -> str:
    targets = (trades or {}).get("targets") or []
    if not targets:
        return ""
    t = targets[0]
    phrase = {"rebuilder": "is rebuilding", "middle": "is in between", "contender": "is contending"}.get(t["owner_label"], "")
    offer = ", ".join(escape(a["label"]) + (f' ({escape(a["injury_status"])})' if a.get("injury_status") else "")
                      for a in t["offer"]["assets"])
    return (f'<a class="card" href="trades.html#t1"><div class="row"><span class="label good">Top trade</span>'
            f'<span class="sub small">1 of {len(targets)} targets</span></div>'
            f'<div class="title">{escape(t["name"])} is gettable</div>'
            f'<div class="body">{escape(t["owner"])} {phrase}. Offer {offer}.</div>'
            f'<div class="row" style="margin-top:6px"><span class="gain">+{fmt(t["gain"])} lineup value</span>'
            f'<span class="gain">See offer &rarr;</span></div></a>')


def _waiver_card(w: dict | None) -> str:
    if not w:
        return ""
    meta = f'${w["my_left"]} left · {w["weeks_left"]} weeks'
    adds, streams = w.get("adds") or [], w.get("streamers") or []
    if adds:
        r = adds[0]
        title = f'Bid ${r["bid"]["bid"]} on {escape(r["name"])}'
        body = (f'{escape(r["pos"] or "")}, {escape(r.get("nfl_team") or "FA")}. '
                + (f'Improves your lineup by {fmt(r["ros_gain"])} for the rest of the season.' if r["ros_gain"] > 0
                   else f'Stash value {fmt(r["dynasty"])}.')
                + (f' {len(adds) - 1} more worth a claim.' if len(adds) > 1 else ""))
    elif streams:
        r = streams[0]
        title = f'Stream {escape(r["name"])}'
        body = f'+{r["week_gain"]:.1f} points to this week\'s best lineup. Bid ${r["bid"]["bid"]}.'
    else:
        title = "Nothing worth a bid"
        body = "Nobody on the wire would start for you. Depth options are $1 claims."
    return (f'<a class="card" href="waivers.html"><div class="row"><span class="label warn">Waivers</span>'
            f'<span class="sub small">{meta}</span></div><div class="title">{title}</div><div class="body">{body}</div></a>')


def _grade_card(grades: list[dict]) -> str:
    live = [g for g in grades if isinstance(g.get("you"), (int, float)) and isinstance(g.get("best"), (int, float))]
    if not live:
        return ""
    g = max(live, key=lambda g: g["week"])
    if g["best"] - g["you"] < 0.05:
        title, body = f'Week {g["week"]}: perfect lineup', f'You scored {g["you"]:.1f}, the most your roster could have scored.'
    else:
        app = f' The app\'s lineup would have scored {g["app"]:.1f}.' if isinstance(g.get("app"), (int, float)) else ""
        title = f'Week {g["week"]}: {g["you"]:.1f} points'
        body = f'Best possible was {g["best"]:.1f}.{app}'
    return (f'<a class="card" href="lineup.html"><span class="label blue">Report card</span>'
            f'<div class="title">{title}</div><div class="body">{body}</div></a>')


def render_today(snap: dict, trades: dict | None = None, waivers: dict | None = None) -> str:
    """The home page (index.html): what needs doing, one card each."""
    sug = snap.get("suggestion")
    if not sug:
        top, msg, cls, moves = "PROJECTIONS UNAVAILABLE", "Sleeper didn't return projections this run.", "act", ""
    elif sug.get("actionable"):
        mv = _moves(sug)
        top = f'{len(mv)} CHANGE{"S" if len(mv) != 1 else ""} TO MAKE'
        msg = f'Your best lineup scores {sug["gain"]:.1f} more.'
        cls = "act"
        moves = '<div class="moves">' + "<br>".join(mv) + "</div>"
    else:
        top, msg, cls, moves = "LINEUP IS SET", "No changes needed. You're starting the best possible lineup.", "", ""
    hero = (f'<a class="hero {cls}" href="lineup.html"><div class="h-top"><span style="display:flex;align-items:center;gap:8px">'
            f'{icon("check" if not cls else "alert", 18, 2.4)}{top}</span><span style="font-weight:500">View &rarr;</span></div>'
            f'<div class="h-msg">{msg}</div>{moves}{_scoreboard(snap, in_hero=True)}</a>')
    cards = "".join(c for c in (_trade_card(trades), _waiver_card(waivers), _grade_card(snap.get("grades") or [])) if c)
    body = (f'<div class="stack">{hero}' + (f'<div class="section">Worth a look</div>{cards}' if cards else "")
            + ui.footer(f'Updated {pt(snap.get("generated_at"), "%a %b %-d, %-I:%M %p PT")}.') + '</div>')
    return ui.page(f"Today &middot; Week {snap['week']}", "today", f"Week {snap['week']}{_record(trades)}", "Today",
                   snap.get("generated_at"), body)
