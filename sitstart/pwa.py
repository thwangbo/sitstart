"""Installable web app bits: manifest, icons, and the freshness bar on each page.

Android Chrome: open the page, menu -> Add to Home screen -> Install. With the manifest it
opens full-screen with its own icon. Standalone mode has no reload or pull-to-refresh,
so each page gets:
- "Data from N min ago", flagged once it's over 12 hours old
- a Reload button that bypasses the phone's cache (GitHub Pages lets it cache ~10 min)
- an automatic reload when you reopen the app after 5+ minutes away
- a "Run a refresh" link to the GitHub page with the Run workflow button
No service worker: nothing is cached offline, so the app never shows an old copy silently.
"""

from __future__ import annotations

import json
import os
import shutil
from html import escape
from pathlib import Path

STATIC = Path(__file__).parent / "static"
ICONS = ["icon-192.png", "icon-512.png", "icon-maskable-512.png", "apple-touch-icon.png", "favicon.png"]
THEME = "#1f7a4d"

MANIFEST = {
    "name": "Sit/Start: lineup, trades and waivers",
    "short_name": "Sit/Start",
    "description": "Weekly lineup calls and trade targets for your Sleeper dynasty team.",
    "start_url": "./",
    "scope": "./",
    "display": "standalone",
    "orientation": "portrait",
    "background_color": "#F6F5F1",
    "theme_color": THEME,
    "icons": [
        {"src": "icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any"},
        {"src": "icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any"},
        {"src": "icon-maskable-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
    ],
    "shortcuts": [
        {"name": "Today", "url": "./", "icons": [{"src": "icon-192.png", "sizes": "192x192"}]},
        {"name": "Lineup", "url": "./lineup.html", "icons": [{"src": "icon-192.png", "sizes": "192x192"}]},
        {"name": "Trade targets", "url": "./trades.html", "icons": [{"src": "icon-192.png", "sizes": "192x192"}]},
        {"name": "Waivers", "url": "./waivers.html", "icons": [{"src": "icon-192.png", "sizes": "192x192"}]},
    ],
}

HEAD = (
    '<link rel="manifest" href="manifest.webmanifest">'
    f'<meta name="theme-color" content="{THEME}">'
    '<meta name="mobile-web-app-capable" content="yes">'
    '<meta name="apple-mobile-web-app-capable" content="yes">'
    '<meta name="apple-mobile-web-app-title" content="Sit/Start">'
    '<link rel="apple-touch-icon" href="apple-touch-icon.png">'
    '<link rel="icon" type="image/png" href="favicon.png">'
)

CSS = (
    ".appbar{display:flex;flex-wrap:wrap;align-items:center;gap:8px 14px;font-size:13px;color:var(--sub);margin:0 0 14px}"
    ".appbar button{font:inherit;font-size:13px;padding:5px 12px;border-radius:999px;border:1px solid var(--line);"
    "background:var(--card);color:var(--ink);cursor:pointer}"
    ".appbar .stale{color:var(--bad);font-weight:600}"
)

SCRIPT = """<script>
(function () {
  var el = document.getElementById('age');
  if (!el) return;
  var ts = Date.parse(el.getAttribute('data-ts'));
  function fmt() {
    var m = Math.round((Date.now() - ts) / 60000);
    var t = m < 1 ? 'just now' : m < 60 ? m + ' min ago' : m < 1440 ? Math.round(m / 60) + ' hr ago'
          : Math.round(m / 1440) + ' days ago';
    el.textContent = t;
    el.className = m > 720 ? 'stale' : '';
  }
  function reload() { location.replace(location.pathname + '?r=' + Date.now()); }
  if (isNaN(ts)) { el.textContent = ''; } else { fmt(); setInterval(fmt, 60000); }
  var btn = document.getElementById('reload');
  if (btn) btn.addEventListener('click', reload);
  var loaded = Date.now();
  document.addEventListener('visibilitychange', function () {
    if (document.visibilityState === 'visible' && Date.now() - loaded > 5 * 60000) reload();
  });
})();
</script>"""


def actions_url() -> str | None:
    """GitHub page with the Run workflow button (set by the workflow; absent on laptop runs)."""
    return os.environ.get("ACTIONS_URL") or None


def appbar(generated_at: str | None) -> str:
    run = actions_url()
    link = (f'<a href="{escape(run)}" target="_blank" rel="noopener">Run a refresh</a>' if run else "")
    return (f'<div class="appbar"><span id="age" data-ts="{escape(generated_at or "")}"></span>'
            f'<button id="reload" type="button">Reload</button>{link}</div>')


def write_static(dest_dir: str | Path) -> list[Path]:
    """Copy the manifest and icons next to the pages."""
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    out = [dest / "manifest.webmanifest"]
    out[0].write_text(json.dumps(MANIFEST, indent=1), encoding="utf-8")
    for name in ICONS:
        shutil.copyfile(STATIC / name, dest / name)
        out.append(dest / name)
    return out
