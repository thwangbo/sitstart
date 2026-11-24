"""Shared look for every page: theme (light and dark), header, bottom tab bar.

Design: "Today feed" home with the Pressbox lineup table, approved Nov 24 (canvas
"Sit/Start UI prototypes", Recommended row). Phone first; on a desktop the same
column is centered. Dark mode follows the phone or browser setting.
"""

from __future__ import annotations

from datetime import datetime
from html import escape

from . import pwa
from .schedule import utc_to_pacific

FONTS = ('<link rel="preconnect" href="https://fonts.googleapis.com">'
         '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
         '<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700'
         '&amp;family=Space+Grotesk:wght@500;600;700&amp;display=swap" rel="stylesheet">')

LIGHT = ("--bg:#F6F5F1;--card:#FFFFFF;--nav:#FFFFFF;--ink:#16181D;--body:#3D424A;--sub:#5B6068;--line:#E4E1D9;"
         "--line2:#DAD7CF;--rule:#F1EFE9;--track:#EDEBE5;--good:#1F7A4D;--warn:#8A4B06;--bad:#A8320C;--blue:#2B4FB0;"
         "--hero:#1F7A4D;--hero2:#8A4B06;--okbg:#E3F1E8;--okfg:#14583A;--warnbg:#F7EBDD;--warnfg:#6B3A05")
DARK = ("--bg:#0E1116;--card:#161B22;--nav:#11161D;--ink:#E6EDF3;--body:#C2CAD4;--sub:#9AA4B2;--line:#222A35;"
        "--line2:#2E3846;--rule:#1E252F;--track:#222A35;--good:#5CC98E;--warn:#F0A04B;--bad:#FF8A70;--blue:#8AB4FF;"
        "--hero:#1B5E3C;--hero2:#7A4206;--okbg:#12301F;--okfg:#8FE3B5;--warnbg:#33240F;--warnfg:#F5C27A")

CSS = f"""
:root{{{LIGHT};color-scheme:light dark}}
@media (prefers-color-scheme:dark){{:root{{{DARK}}}}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.45 Inter,-apple-system,Segoe UI,Roboto,sans-serif;-webkit-text-size-adjust:100%}}
a{{color:var(--good)}}
.wrap{{max-width:720px;margin:0 auto;padding:20px 18px calc(96px + env(safe-area-inset-bottom))}}
.top{{display:flex;justify-content:space-between;align-items:center;gap:12px;margin-bottom:14px}}
.eyebrow{{font-size:13px;color:var(--sub)}}
h1{{font-family:'Space Grotesk',Inter,sans-serif;font-size:24px;font-weight:700;margin:2px 0 0;line-height:1.15}}
h2{{font-family:'Space Grotesk',Inter,sans-serif;font-size:18px;font-weight:600;margin:0}}
.reload{{min-height:44px;padding:0 14px;border-radius:999px;border:1px solid var(--line2);background:var(--card);color:var(--ink);
font:500 13px Inter,sans-serif;display:flex;align-items:center;gap:6px;cursor:pointer;white-space:nowrap}}
.reload .stale{{color:var(--bad);font-weight:600}}
.stack{{display:flex;flex-direction:column;gap:14px}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:14px 16px}}
.card.flush{{padding:4px 14px}}
a.card{{display:block;text-decoration:none;color:var(--ink)}}
.label{{font-size:12px;font-weight:600;letter-spacing:.04em;text-transform:uppercase}}
.label.good{{color:var(--good)}}.label.warn{{color:var(--warn)}}.label.blue{{color:var(--blue)}}.label.sub{{color:var(--sub)}}
.section{{font-size:13px;font-weight:600;color:var(--sub);letter-spacing:.04em;text-transform:uppercase;margin:6px 0 -4px}}
.row{{display:flex;justify-content:space-between;align-items:baseline;gap:10px}}
.title{{font-family:'Space Grotesk',Inter,sans-serif;font-size:19px;font-weight:600;margin:4px 0}}
.body{{font-size:14px;color:var(--body);line-height:1.4}}
.sub{{color:var(--sub);font-size:13px}}.small{{font-size:12px}}
.gain{{color:var(--good);font-weight:700;font-variant-numeric:tabular-nums}}
.num{{font-variant-numeric:tabular-nums}}
.hero{{display:block;text-decoration:none;background:var(--hero);color:#fff;border-radius:18px;padding:16px 18px}}
.hero.act{{background:var(--hero2)}}
.hero .h-top{{display:flex;justify-content:space-between;align-items:center;font-size:13px;font-weight:600;letter-spacing:.02em}}
.hero .h-msg{{font-family:'Space Grotesk',Inter,sans-serif;font-size:22px;font-weight:600;line-height:1.2;margin:10px 0 12px}}
.hero .moves{{font-size:15px;margin:-4px 0 12px;line-height:1.5}}
.score3{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));align-items:end}}
.score3 .nm{{font-size:12px;color:var(--sub);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
.score3 .big{{font-family:'Space Grotesk',Inter,sans-serif;font-size:30px;font-weight:700;font-variant-numeric:tabular-nums;line-height:1.1}}
.score3 .mid{{display:flex;flex-direction:column;align-items:center;gap:2px;padding-bottom:6px}}
.score3 .mid b{{font-family:'Space Grotesk',Inter,sans-serif;font-size:15px}}
.score3 .r{{text-align:right}}
.hero .score3{{border-top:1px solid rgba(255,255,255,.25);padding-top:10px}}
.hero .score3 .nm,.hero .score3 .mid span{{color:#fff;opacity:.85}}
.card .score3 .me{{color:var(--good)}}.card .score3 .mid b{{color:var(--good)}}.card .score3 .mid b.behind{{color:var(--bad)}}
.strip{{display:flex;align-items:center;gap:8px;padding:10px 12px;border-radius:12px;font-size:14px;font-weight:600}}
.strip.ok{{background:var(--okbg);color:var(--okfg)}}.strip.warn{{background:var(--warnbg);color:var(--warnfg)}}
.note{{display:flex;gap:10px;align-items:flex-start;padding:12px 14px;border-radius:14px;background:var(--warnbg);color:var(--warnfg);font-size:14px;line-height:1.4}}
.tag{{display:inline-block;font-size:11px;font-weight:600;padding:1px 7px;border-radius:999px;border:1px solid currentColor;
white-space:nowrap;vertical-align:1px}}
.tag.bad{{color:var(--bad)}}.tag.warn{{color:var(--warn)}}.tag.muted{{color:var(--sub)}}.tag.good{{color:var(--good)}}.tag.blue{{color:var(--blue)}}
.lbl-rebuilder{{color:var(--warn);font-weight:600}}.lbl-middle{{color:var(--blue);font-weight:600}}.lbl-contender{{color:var(--sub);font-weight:600}}
.grid5{{display:grid;grid-template-columns:34px minmax(0,1fr) 40px 40px 50px;gap:6px;align-items:center}}
.thead{{padding:8px 0 6px;font-size:11px;font-weight:600;color:var(--sub);border-bottom:1px solid var(--line)}}
.trow{{padding:7px 0;border-bottom:1px solid var(--rule);font-variant-numeric:tabular-nums}}
.trow:last-child{{border-bottom:none}}
.trow .slot{{font-size:11px;font-weight:600;color:var(--sub)}}
.pn{{font-size:14px;font-weight:500;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
.meta{{font-size:11px;color:var(--sub)}}
.r{{text-align:right}}.c3{{font-size:13px;color:var(--body)}}
.sc{{display:flex;flex-direction:column;align-items:flex-end;gap:3px}}.sc b{{font-size:14px}}
.bar{{width:40px;height:3px;background:var(--track);border-radius:2px;overflow:hidden}}.bar i{{display:block;height:3px;background:var(--good)}}
.chips{{display:flex;gap:6px;flex-wrap:wrap}}
.chip{{min-height:34px;padding:0 12px;border-radius:999px;border:1px solid var(--line2);background:var(--card);color:var(--ink);
font:500 13px Inter,sans-serif;cursor:pointer}}
.chip[aria-pressed=true]{{background:var(--hero);border-color:var(--hero);color:#fff;font-weight:600}}
details.item{{border-bottom:1px solid var(--rule)}}details.item:last-of-type{{border-bottom:none}}
details.item>summary{{list-style:none;cursor:pointer;padding:11px 0;display:flex;flex-direction:column;gap:4px}}
details.item>summary::-webkit-details-marker{{display:none}}
details.item>summary .pname{{font-size:15px;font-weight:600}}
details.item[open]>summary{{padding-bottom:6px}}
.more{{padding:2px 0 14px;display:flex;flex-direction:column;gap:10px}}
.lines{{display:flex;flex-direction:column;gap:6px}}
.lines .row{{font-size:14px}}
.vbar{{height:8px;border-radius:999px;background:var(--track);overflow:hidden}}.vbar i{{display:block;height:8px;background:var(--good)}}
.twisty{{color:var(--sub);font-size:12px}}
details[open] .twisty .o{{display:none}}details:not([open]) .twisty .c{{display:none}}
details.fold{{background:var(--card);border:1px solid var(--line);border-radius:16px}}
details.fold>summary{{list-style:none;cursor:pointer;padding:14px 16px;display:flex;justify-content:space-between;align-items:center;gap:8px}}
details.fold>summary::-webkit-details-marker{{display:none}}
details.fold>.in{{padding:0 16px 14px}}
table.plain{{width:100%;border-collapse:collapse;font-size:13px;font-variant-numeric:tabular-nums}}
table.plain td{{padding:6px 4px;border-top:1px solid var(--rule)}}table.plain tr:first-child td{{border-top:none}}
table.plain .h td{{color:var(--sub);font-size:11px;font-weight:600}}table.plain td.r{{text-align:right}}
table.plain tr.bt td{{color:var(--sub)}}table.plain tr.tot td{{font-weight:700;border-top:2px solid var(--line)}}
.foot{{font-size:12px;color:var(--sub);line-height:1.5;margin-top:4px}}
nav.tabs{{position:fixed;left:0;right:0;bottom:0;background:var(--nav);border-top:1px solid var(--line);z-index:5;
padding:6px 4px calc(8px + env(safe-area-inset-bottom))}}
nav.tabs .in{{max-width:720px;margin:0 auto;display:grid;grid-template-columns:repeat(4,minmax(0,1fr))}}
nav.tabs a{{text-decoration:none;color:var(--sub);display:flex;flex-direction:column;align-items:center;justify-content:center;
gap:3px;min-height:48px;font-size:12px}}
nav.tabs a[aria-current=page]{{color:var(--good);font-weight:600}}
@media (min-width:760px){{.wrap{{padding-top:28px}}}}
"""

ICONS = {
    "today": '<path d="M3 11 12 4l9 7"></path><path d="M5 10v10h14V10"></path>',
    "lineup": '<rect x="4" y="3" width="16" height="18" rx="2"></rect><path d="M8 8h8M8 12h8M8 16h5"></path>',
    "trades": '<path d="M7 7h13l-4-4M17 17H4l4 4"></path>',
    "waivers": '<path d="M12 5v14M5 12h14"></path>',
    "check": '<path d="M20 6 9 17l-5-5"></path>',
    "alert": '<circle cx="12" cy="12" r="9"></circle><path d="M12 8v5M12 16.5v.01"></path>',
    "reload": '<path d="M21 12a9 9 0 1 1-2.6-6.4"></path><path d="M21 4v5h-5"></path>',
}
TABS = [("today", "Today", "./"), ("lineup", "Lineup", "lineup.html"),
        ("trades", "Trades", "trades.html"), ("waivers", "Waivers", "waivers.html")]


def icon(name: str, size: int = 22, width: float = 2) -> str:
    return (f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
            f'stroke-width="{width}" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{ICONS[name]}</svg>')


def pt(iso: str | None, fmt: str = "%a %-I:%M %p") -> str:
    """UTC ISO timestamp -> Pacific time text."""
    if not iso:
        return ""
    local = utc_to_pacific(datetime.fromisoformat(iso))
    try:
        return local.strftime(fmt)
    except ValueError:  # Windows strftime lacks %-I
        return local.strftime(fmt.replace("%-I", "%I").replace("%-d", "%d"))


def fmt(v) -> str:
    return f"{v:,.0f}" if isinstance(v, (int, float)) else "&ndash;"


def pts(v) -> str:
    return f"{v:.1f}" if isinstance(v, (int, float)) else "&ndash;"


def tabs(active: str) -> str:
    links = "".join(
        f'<a href="{href}"{" aria-current=page" if key == active else ""}>{icon(key)}{label}</a>'
        for key, label, href in TABS)
    return f'<nav class="tabs" aria-label="Main"><div class="in">{links}</div></nav>'


def header(eyebrow: str, title: str, generated_at: str | None) -> str:
    return (f'<div class="top"><div><div class="eyebrow">{eyebrow}</div><h1>{title}</h1></div>'
            f'<button id="reload" class="reload" type="button" aria-label="Reload data">{icon("reload", 16)}'
            f'<span id="age" data-ts="{escape(generated_at or "")}"></span></button></div>')


def footer(extra: str = "") -> str:
    run = pwa.actions_url()
    link = f' &middot; <a href="{escape(run)}" target="_blank" rel="noopener">Run a refresh</a>' if run else ""
    return f'<p class="foot">{extra}{link}</p>'


def page(title: str, active: str, eyebrow: str, heading: str, generated_at: str | None, body: str,
         extra_css: str = "", script: str = "") -> str:
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="color-scheme" content="light dark"><title>{title}</title>{pwa.HEAD}{FONTS}
<style>{CSS}{extra_css}</style></head><body>
<main class="wrap">
{header(eyebrow, heading, generated_at)}
{body}
</main>
{tabs(active)}
{pwa.SCRIPT}{script}</body></html>
"""
