"""Trades page (trades.html) in the shared look from ui.py."""

from __future__ import annotations

from html import escape

from . import ui

LABEL_WORDS = {"rebuilder": "rebuilding", "middle": "in between", "contender": "contending"}


def _fmt(v) -> str:
    return f"{v:,.0f}" if isinstance(v, (int, float)) else "&ndash;"


def _age(a) -> str:
    return f"{a:.0f}" if isinstance(a, (int, float)) else "?"


def _tag(label: str) -> str:
    return f'<span class="lbl-{escape(label)}">{escape(LABEL_WORDS.get(label, label))}</span>'


def _inj(status) -> str:
    return f' <span class="tag bad">{escape(status)}</span>' if status else ""


def _suffix(n: int) -> str:
    return "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")


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


def _sources(t: dict) -> str:
    fc, kt = t.get("fc_value"), t.get("ktc_value")
    if fc is None and kt is None:
        return ""
    parts = []
    if fc is not None:
        parts.append(f"FantasyCalc {_fmt(fc)}")
    if kt is not None:
        parts.append(f"KTC {_fmt(kt)}")
    flag = ' <span class="tag warn">sources disagree</span>' if t.get("disagree") else ""
    return f'<div class="sub small">{" &middot; ".join(parts)}{flag}</div>'


def _values_note(rep: dict) -> str:
    vs = rep.get("value_sources") or {}
    if vs.get("ktc") == "blended":
        return ("Market value = average of FantasyCalc (from real trades) and KeepTradeCut (crowd votes), "
                "with KTC converted to FantasyCalc's scale by rank. Win-now value is FantasyCalc's. ")
    return "Market value = FantasyCalc (KeepTradeCut was unavailable this run). "


def _reuse(t: dict) -> str:
    shared = t.get("shared") or []
    if not shared:
        return ""
    names = ", ".join(f'{escape(x["label"])} (in {x["offers"]} offers)' for x in shared)
    alt = t.get("alt_offer")
    if alt:
        alt_s = (" Without it: " + ", ".join(escape(a["label"]) for a in alt["assets"])
                 + f" ({alt['ratio']:.0%}).")
    else:
        alt_s = " No package works without it."
    return f'<div class="sub small">Shared: {names}.{alt_s}</div>'


def _short(assets: list[dict]) -> str:
    return ", ".join(escape(a["label"]) + (f' ({escape(a["injury_status"])})' if a.get("injury_status") else "")
                     for a in assets)


def _lines(assets: list[dict], tags: bool = False) -> str:
    out = []
    for a in assets:
        extra = _inj(a.get("injury_status"))
        if tags and a.get("tag") == "starter":
            extra += ' <span class="tag blue">starter</span>'
        out.append(f'<div class="row"><span>{escape(a["label"])}{extra}</span><span class="num">{_fmt(a["value"])}</span></div>')
    return "".join(out)


def _value_bar(give: float, get: float) -> str:
    width = 100 if give <= 0 else max(5, min(100, round(get / give * 100))) if give > get else 100
    return (f'<div class="vbar"><i style="width:{width}%"></i></div>'
            f'<div class="row sub small"><span>You give {_fmt(give)}</span><span>You get {_fmt(get)}</span></div>')


MAX_SWING_ROWS = 8


def _swing_items(rep: dict) -> list[dict]:
    """Bigger swings and injured-player sells as one list of trades, ranked together."""
    items = []
    for x in rep.get("bigger_swings") or []:
        starter = x["gives_starter"][0] if x.get("gives_starter") else {}
        items.append({"score": x.get("score", 0), "owner": x["owner"], "owner_label": x["owner_label"], "why": x["why"],
                      "net_gain": x["net_gain"], "ratio": x["offer"]["ratio"],
                      "get": [{"label": x["name"], "value": x["value"], "ppg": x.get("ppg"), "kind": "player",
                               "injury_status": x.get("injury_status"),
                               "meta": f'{x["pos"] or ""}, {_age(x["age"])}, {x.get("nfl_team") or "FA"}'}],
                      "give": [dict(a, tag="starter" if a.get("core") else None) for a in x["offer"]["assets"]],
                      "note": f'net, after losing {starter.get("name", "a starter")}'
                              + (f' ({starter["ppg"]:.1f} pts/game)' if isinstance(starter.get("ppg"), (int, float)) else "")})
    # One injured-player deal per team: the biggest gain, then the one that gives up less dynasty value
    best = {}
    for x in rep.get("injured_sells") or []:
        for d in x["deals"]:
            k = (d["score"], -x["value"])
            if d["owner"] not in best or k > best[d["owner"]][0]:
                best[d["owner"]] = (k, x, d)
    for _, x, d in best.values():
        items.append({"score": d["score"], "owner": d["owner"], "owner_label": d["owner_label"],
                      "why": "rebuilding, so they can wait for him to come back" if d["owner_label"] == "rebuilder"
                             else "in the middle, so they can wait for him to come back",
                      "net_gain": d["net_gain"], "ratio": round(1 / d["ratio"], 3) if d["ratio"] else 1.0,
                      "get": [dict(g, meta=(f'{g["pos"]}, {_age(g["age"])}' if g["kind"] == "player" else "pick"))
                              for g in d["get"]],
                      "give": [{"label": x["name"], "value": x["value"], "kind": "player",
                                "injury_status": x.get("injury_status"), "tag": "out long-term"}],
                      "note": f'{x["name"]} adds nothing to your lineup this season'})
    items.sort(key=lambda i: -i["score"])
    return items[:MAX_SWING_ROWS]


def _swing_rows(items: list[dict]) -> str:
    out = []
    for x in items:
        get_names = " + ".join(escape(g["label"]) for g in x["get"])
        get_value = sum(g["value"] for g in x["get"])
        give_value = sum(a["value"] for a in x["give"])
        get_lines = "".join(
            f'<div class="row"><span>{escape(g["label"])}{_inj(g.get("injury_status"))} '
            f'<span class="sub small">{escape(g.get("meta") or "")}'
            + (f', {g["ppg"]:.1f} pts/game' if isinstance(g.get("ppg"), (int, float)) else "")
            + f'</span></span><span class="num">{_fmt(g["value"])}</span></div>' for g in x["get"])
        out.append(
            f'<details class="item"><summary>'
            f'<div class="row"><span class="pname">{get_names}</span><span class="gain">+{_fmt(x["net_gain"])}</span></div>'
            f'<div class="row sub small"><span>{escape(x["owner"])} · {_tag(x["owner_label"])}</span>'
            f'<span>{escape(x["note"])}</span></div>'
            f'<div class="row body"><span>Give: {_short(x["give"])}</span>'
            f'<span class="sub" style="white-space:nowrap">{x["ratio"]:.0%} of what you get</span></div></summary>'
            f'<div class="more"><div class="body">{escape(x["owner"])} is {escape(x["why"])}.</div>'
            f'<div><span class="label sub">You get</span><div class="lines">{get_lines}</div></div>'
            f'<div><span class="label sub">You give</span><div class="lines">{_lines(x["give"], tags=True)}</div></div>'
            f'{_value_bar(give_value, get_value)}</div></details>')
    return "".join(out)


def _target_items(targets: list[dict]) -> str:
    out = []
    for i, t in enumerate(targets, 1):
        o = t["offer"]
        give = sum(a["value"] for a in o["assets"])
        ppg = ""
        if isinstance(t.get("ppg"), (int, float)):
            rep_ppg = [p for p in t.get("replaces_ppg") or [] if isinstance(p, (int, float))]
            ppg = f'{t["ppg"]:.1f} pts/game' + (
                f' vs {rep_ppg[0]:.1f} for {escape(t["replaces"][0])}' if rep_ppg and t.get("replaces") else "")
        replaces = f'Replaces {escape(", ".join(t["replaces"]))}.' if t.get("replaces") else ""
        trend = t.get("trend")
        trend_s = f' ({trend:+,} in 30 days)' if isinstance(trend, (int, float)) and abs(trend) >= 100 else ""
        alt = t.get("alt_offer")
        out.append(
            f'<details class="item" id="t{i}" data-label="{escape(t["owner_label"])}" data-pos="{escape(t["pos"] or "")}">'
            f'<summary><div class="row"><span><span class="pname">{escape(t["name"])}</span>{_inj(t.get("injury_status"))} '
            f'<span class="sub small">{escape(t["pos"] or "")} · {_age(t["age"])} · {escape(t.get("nfl_team") or "FA")}</span></span>'
            f'<span class="gain">+{_fmt(t["gain"])}</span></div>'
            f'<div class="row sub small"><span>{escape(t["owner"])} · {_tag(t["owner_label"])}</span>'
            f'<span>value {_fmt(t["value"])}</span></div>'
            f'<div class="row body"><span>Give: {_short(o["assets"])}</span>'
            f'<span class="sub" style="white-space:nowrap">{o["ratio"]:.0%}</span></div></summary>'
            f'<div class="more"><div class="body">{escape(t["why"])}. {replaces}</div>'
            + (f'<div class="sub small">{ppg}</div>' if ppg else "")
            + f'<div><span class="label sub">Suggested offer · {o["ratio"]:.0%} of his value</span>'
            f'<div class="lines" style="margin-top:6px">{_lines(o["assets"])}</div></div>'
            f'{_value_bar(give, t["value"])}'
            f'<div class="sub small">Market value {_fmt(t["value"])}{trend_s}</div>{_sources(t)}{_reuse(t)}'
            + (f'<div class="sub small">Alternate offer: {_short(alt["assets"])} ({alt["ratio"]:.0%}).</div>'
               if alt and not t.get("shared") else "")
            + '</div></details>')
    return "".join(out)


FILTER_JS = """<script>
(function () {
  var chips = document.querySelectorAll('.chip[data-f]');
  function apply(f) {
    var shown = 0;
    document.querySelectorAll('#targets details.item').forEach(function (d) {
      var ok = f === 'all' || d.getAttribute('data-label') === f || d.getAttribute('data-pos') === f;
      d.hidden = !ok; if (ok) shown++;
    });
    var empty = document.getElementById('t-empty'); if (empty) empty.hidden = shown > 0;
    chips.forEach(function (c) { c.setAttribute('aria-pressed', c.getAttribute('data-f') === f ? 'true' : 'false'); });
  }
  chips.forEach(function (c) { c.addEventListener('click', function () { apply(c.getAttribute('data-f')); }); });
  var h = location.hash && document.getElementById(location.hash.slice(1));
  if (h && h.tagName === 'DETAILS') { h.open = true; }
})();
</script>"""


def render(rep: dict) -> str:
    me = rep["me"]
    targets = rep.get("targets") or []
    labels = {t["owner_label"] for t in targets}
    positions = [p for p in ("QB", "RB", "WR", "TE") if any(t["pos"] == p for t in targets)]
    chips = [("all", f"All {len(targets)}")]
    chips += [(lab, LABEL_WORDS[lab].capitalize()) for lab in ("rebuilder", "middle") if lab in labels]
    chips += [(p, p) for p in positions]
    chip_html = "".join(f'<button type="button" class="chip" data-f="{k}" aria-pressed="{"true" if k == "all" else "false"}">'
                        f'{escape(v)}</button>' for k, v in chips) if targets else ""
    target_html = (f'<div class="card flush" id="targets">{_target_items(targets)}'
                   '<p class="sub" id="t-empty" hidden style="padding:10px 0">No targets match this filter.</p></div>'
                   ) if targets else '<div class="card"><div class="body">No upgrades found that your surplus can pay for.</div></div>'
    oor = rep.get("out_of_reach") or []
    oor_html = ('<p class="sub small" style="margin:0 4px">Out of reach without a starter: '
                + ", ".join(f'{escape(t["name"])} ({escape(t["owner"])})' for t in oor)
                + ". See Bigger swings.</p>") if oor else ""

    swing_items = _swing_items(rep)
    swings_html = ""
    if swing_items:
        swings_html = (f'<details class="fold" id="swings"><summary><div><h2>Bigger swings</h2><div class="sub small">'
                       f'{len(swing_items)} trades built around a starter or an injured player</div></div>'
                       '<span class="twisty"><span class="o">Show</span><span class="c">Hide</span></span></summary>'
                       f'<div class="in">{_swing_rows(swing_items)}'
                       '<p class="sub small">Starter: for players your other assets can\'t reach, you send a starter plus up '
                       'to two pieces, shown only if your lineup still improves. Out long-term: an injured player who '
                       'wouldn\'t start for you this season goes only to rebuilding or in-between teams, for players who '
                       'start now. Both are priced on dynasty value. Selling an injured young player gives up future value '
                       'to win now.</p></div></details>')

    chip_list = "".join(f'<div class="row"><span>{escape(a["label"])}</span><span class="num sub">{_fmt(a["value"])}</span></div>'
                        for a in rep.get("my_assets") or [])
    chip_list += "".join(f'<div class="row"><span>{escape(x["name"])} <span class="tag bad">non-contenders only</span></span>'
                         f'<span class="num sub">{_fmt(x["value"])}</span></div>'
                         for x in rep.get("injured_sells") or [] if x["deals"])
    hurt_names = [x["name"] for x in rep.get("injured_sells") or [] if x["deals"]]
    chips_sub = (f'{" and ".join(escape(n) for n in hurt_names)}: non-contenders only' if hurt_names
                 else f'{len(rep.get("my_assets") or [])} players and picks you can deal')
    chips_html = (f'<details class="fold"><summary><div><h2>Your trade chips</h2><div class="sub small">{chips_sub}</div></div>'
                  f'<span class="twisty"><span class="o">Show</span><span class="c">Hide</span></span></summary>'
                  f'<div class="in"><div class="lines">{chip_list}</div></div></details>')

    needs = " · ".join(f'{n["pos"]} {n["rank"]}{_suffix(n["rank"])}' + (" (below avg)" if n["need"] else "")
                       for n in rep.get("needs") or [])
    lens = ("You're contending, so targets are ranked on how much they improve your starting lineup this season, "
            "weighted by how likely their manager is to sell. Offers never include your best lineup or the players "
            "filling in for your injured starters, and favor picks and the players who add the least this season. "
            "Injured players out long-term are offered only to teams that aren't contending.") if me["label"] != "rebuilder" else (
            "You're rebuilding, so targets are young players ranked on dynasty value, "
            "weighted by how likely their manager is to sell.")
    team_rows = "".join(
        f'<tr><td>{"<b>" if t["roster_id"] == me["roster_id"] else ""}{escape(t["name"])}'
        f'{"</b>" if t["roster_id"] == me["roster_id"] else ""}</td><td class="r">{t["wins"]}-{t["losses"]}</td>'
        f'<td>{_tag(t["label"])}</td><td class="r">{t["win_now_rank"]}</td><td class="r">{t["dynasty_rank"]}</td></tr>'
        for t in rep["teams"])
    team_html = (f'<details class="fold"><summary><div><h2>Your team and the league</h2><div class="sub small">'
                 f'{escape("; ".join(me["reasons"]))}</div></div><span class="twisty"><span class="o">Show</span>'
                 f'<span class="c">Hide</span></span></summary><div class="in"><div class="body">{lens}</div>'
                 + (f'<p class="sub small">Your starters vs the league: {needs}</p>' if needs else "")
                 + '<table class="plain"><tr class="h"><td>Team</td><td class="r">Record</td><td>Direction</td>'
                 f'<td class="r">Win-now</td><td class="r">Dynasty</td></tr>{team_rows}</table>'
                 f'<p class="sub small">Direction combines standings, win-now and dynasty value, roster age, youth and '
                 f'this season\'s trades ({rep.get("trades_this_season", 0)} in the league).</p></div></details>')

    deadline = _deadline(rep)
    body = f"""<div class="stack">
{f'<div class="sub">{escape(deadline)}</div>' if deadline else ''}
<div class="chips">{chip_html}</div>
{target_html}
{oor_html}
{swings_html}
{chips_html}
{team_html}
{ui.footer(_values_note(rep) + "Lineup gain uses win-now value. Offers total 100&ndash;120% of the player's market "
           "value, plus 8% for each extra piece; the best piece is worth at least half of what you get.")}
</div>"""
    rank = me.get("record_rank")
    eyebrow = (f"You're {'a ' + me['label'] if me['label'] != 'middle' else 'in between'} · {me['wins']}-{me['losses']}"
               + (f", {rank}{_suffix(rank)}" if rank else ""))
    return ui.page(f"Trades &middot; Week {rep['week']}", "trades", escape(eyebrow), "Trades",
                   rep.get("generated_at"), body, script=FILTER_JS)
