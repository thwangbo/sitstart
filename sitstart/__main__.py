"""Command line entry point.

    py -m sitstart --username YOUR_SLEEPER_NAME
    py -m sitstart --username YOUR_SLEEPER_NAME --html site/index.html --notify
"""

import argparse
import json
import os
import sys
from pathlib import Path

from .schedule import load_schedule
from .sleeper import SleeperClient, SleeperError, build_snapshot, format_summary, save_snapshot


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Pull your Sleeper league, roster, lineup and projections.")
    ap.add_argument("--username", required=True, help="Your Sleeper username")
    ap.add_argument("--league-id", help="Only needed if you have more than one dynasty Superflex league")
    ap.add_argument("--season", help="Defaults to the current NFL season")
    ap.add_argument("--week", type=int, help="Defaults to the current NFL week")
    ap.add_argument("--out", default="data", help="Folder for the snapshot JSON (default: data)")
    ap.add_argument("--no-projections", action="store_true", help="Skip Sleeper projections")
    ap.add_argument("--html", help="Also write the results page to this path, e.g. site/index.html")
    ap.add_argument("--notify", action="store_true",
                    help="Send a phone alert via ntfy when something changes (topic from NTFY_TOPIC)")
    args = ap.parse_args(argv)

    try:
        sys.stdout.reconfigure(encoding="utf-8")  # Windows console: accented player names
    except Exception:
        pass

    previous = None
    prev_path = Path(args.out) / "sleeper_latest.json"
    if prev_path.exists():
        try:
            previous = json.loads(prev_path.read_text(encoding="utf-8"))
        except Exception:
            previous = None

    client = SleeperClient()
    try:
        state = client.get("state/nfl") or {}
        season = args.season or state.get("league_season") or state.get("season")
        week = args.week or state.get("display_week") or state.get("week")

        schedule = None
        try:
            schedule = load_schedule(season, int(week))
        except Exception as e:  # schedule is an enhancement; keep going without it
            print(f"Warning: couldn't load the NFL schedule ({e}). Bye and lock checks are off.", file=sys.stderr)

        snap = build_snapshot(client, args.username, season, week, args.league_id,
                              schedule=schedule, fetch_proj=not args.no_projections)
    except SleeperError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    if snap.data_status.get("projections_source") == "none":
        print("Warning: Sleeper returned no projections from either endpoint.", file=sys.stderr)

    path = save_snapshot(snap, args.out)
    print(format_summary(snap))
    print(f"\nSaved {path}")

    if args.html:
        from .page import render
        html_path = Path(args.html)
        html_path.parent.mkdir(parents=True, exist_ok=True)
        html_path.write_text(render(snap.to_dict()), encoding="utf-8")
        print(f"Wrote {html_path}")

    if args.notify:
        from .notify import build_alert, send
        topic = os.environ.get("NTFY_TOPIC", "").strip()
        alert = build_alert(snap.to_dict(), previous)
        if not topic:
            print("Alerts skipped: NTFY_TOPIC is not set.")
        elif alert is None:
            print("No alert: nothing changed since the last run.")
        else:
            try:
                send(topic, alert[0], alert[1], os.environ.get("PAGE_URL") or None)
                print(f"Alert sent: {alert[0]}")
            except Exception as e:  # an alert failure shouldn't fail the run
                print(f"Warning: alert not sent ({e})", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
