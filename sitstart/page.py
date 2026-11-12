"""Render a snapshot as one self-contained HTML page (no scripts, no external calls)."""

from __future__ import annotations

from datetime import datetime
from html import escape

from .schedule import utc_to_pacific
from .sleeper import card_value

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


def _pt(iso: str | None, fmt: str = "%a %-I:%M %p") -> str:
    if not iso:
        return ""
    local = utc_to_pacific(datetime.fromisoformat(iso))
    try:
        return local.strftime(fmt)
    except ValueError:  # Windows strftime lacks %-I
        return local.strftime(fmt.replace("%-I", "%I"))


def _pts(v) -> str:
    return f"{v:.1f}" if isinstance(v, (int, float)) else "&ndash;"


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
    if locked or (card and card.get("locked")):
        tags.append('<span class="tag muted">Locked</span>')
    return " ".join(tags)


def _player_cells(card: dict | None) -> str:
    if not card:
        return '<td class="name empty">Empty</td><td class="game"></td><td class="xp"></td><td class="st"></td>'
    who = f'<span class="pname">{escape(card["name"])}</span> <span class="sub">{escape(card.get("position") or "")}' \
          f'{", " + escape(card["team"]) if card.get("team") else ""}</span>'
    game = escape(card.get("opponent") or "")
    when = _pt(card.get("kickoff_utc"))
    rank = escape(card.get("consensus_rank") or "")
    game_cell = f'{game}<span class="sub when">{when}</span>' if when else game
    return (f'<td class="name">{who}</td><td class="game">{game_cell}</td>'
            f'<td class="sub xp">{rank}</td><td class="st">{_stats_cell(card)}</td>')


def _stats_cell(card: dict) -> str:
    adj = card.get("stat_adj")
    if not isinstance(adj, (int, float)):
        return ""
    cls = "up" if adj > 0.025 else "down" if adj < -0.025 else "flat"
    tip = f'Recent expected points {card.get("xfp")}, usage trend {card.get("usage_trend")}'
    return f'<span class="stat {cls}" title="{escape(tip)}">{adj:+.0%}</span>'


def _suggestion_block(sug: dict | None) -> str:
    if not sug:
        return '<section class="card"><h2>Suggested changes</h2><p class="sub">Projections unavailable this run.</p></section>'
    if not sug.get("actionable"):
        return ('<section class="card ok"><h2>Your lineup is set</h2>'
                '<p>No changes beat your current lineup on Score.</p></section>')
    rows = []
    for verb, group in (("Start", sug["start"]), ("Sit", sug["sit"])):
        for c in group:
            note = ""
            if c.get("injury_status") == "Questionable":
                note = f' <span class="tag warn">Questionable, counted as {c["value"]:.1f}</span>'
            rows.append(f'<tr><td class="verb {verb.lower()}">{verb}</td><td class="name">{escape(c["name"])}{note}</td>'
                        f'<td class="num">{_pts(c["proj_pts"])}</td></tr>')
    gain = f' <span class="gain">+{sug["gain"]:.1f} pts</span>' if sug["gain"] > 0.05 else ""
    moves = ""
    if sug.get("slot_moves"):
        moves = '<p class="sub">Then set slots: ' + escape(", ".join(
            f'{r["slot"]} {r["name"]}' for r in sug["lineup"] if r["name"])) + "</p>"
    return (f'<section class="card accent"><h2>Suggested changes{gain}</h2>'
            f'<table class="sug">{"".join(rows)}</table>{moves}'
            '<p class="sub">Ranked on Score (Sleeper projections blended with expert consensus). Questionable players are discounted 15%.</p>'
            '</section>')


def _stats_view_note(snap: dict) -> str:
    sv, sug = snap.get("stats_view"), snap.get("suggestion") or {}
    if not sv or not sv.get("actionable"):
        return ""
    main = {c["player_id"] for c in sug.get("start", [])} if sug.get("actionable") else set()
    if {c["player_id"] for c in sv["start"]} == main:
        return ""
    starts = ", ".join(escape(c["name"]) for c in sv["start"])
    sits = ", ".join(escape(c["name"]) for c in sv["sit"])
    return ('<section class="card"><h2>Stats view <span class="sub">shadow mode, not applied</span></h2>'
            f'<p>Usage and matchup data would start <b>{starts}</b>' + (f' over <b>{sits}</b>' if sits else '') + '.</p>'
            '<p class="sub">Shown for comparison only. It joins the recommendations once the report card shows it beating the app.</p></section>')


def _report_card(grades: list[dict]) -> str:
    if not grades:
        return ""
    from .grades import stats_streak
    def cell(v):
        return f"{v:.1f}" if isinstance(v, (int, float)) else "&ndash;"
    rows = "".join(
        f'<tr class="{"bt" if g.get("source") == "backtest" else ""}"><td>Week {g["week"]}</td>'
        f'<td>{cell(g.get("you"))}</td><td>{cell(g.get("app"))}</td><td>{cell(g.get("sleeper"))}</td>'
        f'<td>{cell(g.get("stats"))}</td><td>{cell(g.get("best"))}</td></tr>'
        for g in sorted(grades, key=lambda g: -g["week"]))
    tot = lambda k: sum(g.get(k) or 0 for g in grades)
    has_stats = [g for g in grades if isinstance(g.get("stats"), (int, float))]
    stats_tot = f"{sum(g['stats'] for g in has_stats):.1f}*" if has_stats else "&ndash;"
    same = ""
    if has_stats and len(has_stats) < len(grades):
        wks = [g["week"] for g in has_stats]
        same = (f" *Stats view covers Weeks {min(wks)}&ndash;{max(wks)} only; over those weeks the app scored "
                f"{sum(g['app'] or 0 for g in has_stats):.1f} and the stats view {sum(g['stats'] for g in has_stats):.1f}.")
    note = ("Stats view has beaten the app 3 weeks running. Consider switching it on."
            if stats_streak(grades) else
            "Gray rows are backtest weeks (before the app existed, no injury info). The stats view is shadow-only.") + same
    return ('<section class="card"><h2>Report card</h2><table class="grades">'
            '<tr class="head"><td>Week</td><td>You</td><td>App</td><td>Sleeper only</td><td>Stats view</td><td>Best possible</td></tr>'
            f'{rows}<tr class="total"><td>Season</td><td>{tot("you"):.1f}</td><td>{tot("app"):.1f}</td>'
            f'<td>{tot("sleeper"):.1f}</td><td>{stats_tot}</td><td>{tot("best"):.1f}</td></tr></table>'
            f'<p class="sub">Points your lineup scored under each approach. {note}</p></section>')


def _blend_note(ds: dict) -> str:
    if ds.get("consensus_players"):
        w = ds.get("blend_weight", 0.5)
        return (f"Score = {1 - w:.0%} Sleeper projection in your league scoring + {w:.0%} expert consensus "
                f"(FantasyPros rankings via DynastyProcess, {ds.get('consensus_scrape_date')}). "
                "Experts = consensus positional rank.")
    return "Score = Sleeper projection in your league scoring. Expert consensus was unavailable this run."


def render(snap: dict) -> str:
    lg = snap["league"]
    sc = lg["scoring_summary"]
    ds = snap.get("data_status") or {}
    updated = _pt(snap.get("generated_at"), "%a %b %-d, %-I:%M %p PT")

    lineup_rows = "".join(
        f'<tr><td class="slot">{escape(r["slot"].replace("_", " "))}</td>{_player_cells(r["player"])}'
        f'<td>{_status(r["player"], r["flag"], r.get("locked"))}</td><td class="num">{_pts(card_value(r["player"]))}</td></tr>'
        for r in snap["lineup"])
    total = sum(card_value(r["player"]) or 0 for r in snap["lineup"])

    bench = sorted(snap["bench"], key=lambda c: -(card_value(c) or 0))
    bench_rows = "".join(
        f'<tr>{_player_cells(c)}<td>{_status(c)}</td><td class="num">{_pts(card_value(c))}</td></tr>'
        for c in bench)

    opp_html = ""
    opp = snap.get("opponent")
    if opp:
        def opp_row(r):
            c = r["player"]
            who = (f'<span class="pname">{escape(c["name"])}</span> <span class="sub">{escape(c.get("position") or "")}'
                   f'{", " + escape(c["team"]) if c.get("team") else ""}</span>') if c else "Empty"
            rank = escape((c or {}).get("consensus_rank") or "")
            return (f'<tr><td class="slot">{escape(r["slot"].replace("_", " "))}</td><td class="name">{who}</td>'
                    f'<td class="sub">{rank}</td><td>{_status(c, r["flag"], r.get("locked"))}</td>'
                    f'<td class="num">{_pts(card_value(c))}</td></tr>')
        opp_rows = "".join(opp_row(r) for r in opp["lineup"])
        opp_html = (f'<section class="card"><h2>Opponent: {escape(opp.get("team_name") or "")}'
                    f' <span class="sub">projected {_pts(opp.get("proj_total"))}</span></h2>'
                    '<table><tr class="head"><td>Slot</td><td>Player</td><td>Experts</td><td></td><td class="num">Score</td></tr>'
                    f'{opp_rows}</table></section>')

    reserve = ", ".join(escape(c["name"]) for c in snap.get("reserve") or [])
    taxi = ", ".join(escape(c["name"]) for c in snap.get("taxi") or [])
    extras = ""
    if reserve:
        extras += f'<p class="sub">IR: {reserve}</p>'
    if taxi:
        extras += f'<p class="sub">Taxi: {taxi}</p>'

    byes = ", ".join(ds.get("bye_teams") or []) or "none"
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Lineup &middot; Week {snap["week"]}</title>
<style>
:root{{--bg:#f7f6f3;--card:#fff;--ink:#1d1d1b;--sub:#6b6a66;--line:#e6e4de;--accent:#2f5bd3;--good:#1f7a4d;--warn:#a86400;--bad:#b3261e}}
@media (prefers-color-scheme:dark){{:root{{--bg:#151514;--card:#1f1f1d;--ink:#ecebe7;--sub:#a3a29d;--line:#33322f;--accent:#7f9cf5;--good:#5cc28f;--warn:#e0a84a;--bad:#f08a80}}}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.45 -apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif}}
main{{max-width:1120px;margin:0 auto;padding:28px 16px 48px}}a{{color:var(--accent)}}
header h1{{margin:0;font-size:24px}}header p{{margin:4px 0 0;color:var(--sub)}}
.grid{{display:grid;grid-template-columns:1fr;gap:16px;margin-top:20px}}
@media (min-width:1000px){{.grid{{grid-template-columns:minmax(0,11fr) minmax(0,9fr)}}}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px 18px;margin-top:16px;overflow-x:auto}}
.grid .card{{margin-top:0}}.grid>div{{min-width:0}}.grid>div>.card+.card{{margin-top:16px}}
.card.accent{{border-color:var(--accent);border-width:2px}}.card.ok{{border-color:var(--good)}}
h2{{font-size:16px;margin:0 0 10px}}.gain{{color:var(--good);margin-left:6px}}
table{{width:100%;border-collapse:collapse}}td{{padding:7px 8px;border-top:1px solid var(--line);vertical-align:middle;white-space:nowrap}}
tr:first-child td{{border-top:none}}.num{{text-align:right;font-variant-numeric:tabular-nums;font-weight:600}}
.slot{{color:var(--sub);font-size:12px;letter-spacing:.04em;width:88px}}.name{{white-space:normal;min-width:150px}}.pname{{font-weight:600;display:block}}.name .sub{{display:block;font-size:12px}}
.sub{{color:var(--sub);font-size:13px}}.empty{{color:var(--bad)}}
.tag{{display:inline-block;font-size:12px;padding:1px 7px;border-radius:999px;border:1px solid currentColor}}
.tag.bad{{color:var(--bad)}}.tag.warn{{color:var(--warn)}}.tag.muted{{color:var(--sub)}}
.verb{{font-weight:700;width:56px}}.verb.start{{color:var(--good)}}.verb.sit{{color:var(--bad)}}
.total td{{font-weight:700;border-top:2px solid var(--line)}}.head td{{color:var(--sub);font-size:12px;border-top:none;padding-top:0}}
.game .when{{display:block;font-size:12px}}
@media (max-width:640px){{.game,.xp,.st{{display:none}}.slot{{width:64px}}td{{padding:7px 5px}}}}.stat{{font-size:12px;font-variant-numeric:tabular-nums}}.stat.up{{color:var(--good)}}.stat.down{{color:var(--bad)}}.stat.flat{{color:var(--sub)}}
.grades td{{text-align:right;font-variant-numeric:tabular-nums}}.grades td:first-child{{text-align:left}}.grades .bt td{{color:var(--sub)}}
</style></head><body><main>
<header><h1>{escape(lg["name"] or "")} &middot; Week {snap["week"]}</h1>
<p>{escape(snap["me"].get("team_name") or "")} &middot; {escape(sc["format"])}, {"Superflex" if lg["is_superflex"] else "1QB"} &middot; Updated {updated}{' &middot; <a href="trades.html">Trade targets &rarr;</a>' if ds.get("trades_page") else ""}</p></header>
<div class="grid">
<div>
{_suggestion_block(snap.get("suggestion"))}
{_stats_view_note(snap)}
<section class="card"><h2>Current lineup</h2><table><tr class="head"><td>Slot</td><td>Player</td><td class="game">Game (PT)</td><td class="xp">Experts</td><td class="st">Stats</td><td></td><td class="num">Score</td></tr>{lineup_rows}
<tr class="total"><td colspan="2">Projected total</td><td class="game"></td><td class="xp"></td><td class="st"></td><td></td><td class="num">{total:.1f}</td></tr></table></section>
</div>
<div>{opp_html}</div>
</div>
{_report_card(snap.get("grades") or [])}
<section class="card"><h2>Bench</h2><table><tr class="head"><td>Player</td><td class="game">Game (PT)</td><td class="xp">Experts</td><td class="st">Stats</td><td></td><td class="num">Score</td></tr>{bench_rows}</table>{extras}</section>
<p class="sub">{escape(_blend_note(ds))}</p>
<p class="sub">Projections: Sleeper ({escape(str(ds.get("projections_source")))}, {ds.get("projections_count")} players). Byes: {escape(byes)}. Kickoff times are Pacific.</p>
</main></body></html>
"""
