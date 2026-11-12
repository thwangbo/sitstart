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


def load_ids_text():
    from .consensus import IDS_URL, fetch
    try:
        return fetch(IDS_URL)
    except Exception as e:
        print(f"Warning: player ID crosswalk unavailable ({e}). Experts and stats are off.", file=sys.stderr)
        return None


def load_stats_source(season, ids_text):
    """(ffopportunity csv text, gsis->sleeper map) or None."""
    from .consensus import fetch
    from .stats import EP_URL, parse_gsis_map
    if not ids_text:
        return None
    try:
        return fetch(EP_URL.format(season=season), timeout=120), parse_gsis_map(ids_text)
    except Exception as e:
        print(f"Warning: usage stats unavailable ({e}). Stats view is off.", file=sys.stderr)
        return None


def load_consensus(client, schedule, ids_text):
    """This week's expert consensus mapped to Sleeper ids, or None (with a warning) if unavailable or stale."""
    from .consensus import WEEKLY_URL, fetch, map_to_sleeper, matches_week, parse_ecr, parse_id_map
    if not ids_text:
        return None
    try:
        ecr = parse_ecr(fetch(WEEKLY_URL))
        ids = parse_id_map(ids_text)
    except Exception as e:
        print(f"Warning: expert consensus unavailable ({e}). Using Sleeper projections only.", file=sys.stderr)
        return None
    if schedule is not None and not matches_week(ecr, schedule.games):
        print("Warning: expert consensus file is for a different week (not updated yet). "
              "Using Sleeper projections only.", file=sys.stderr)
        return None
    return map_to_sleeper(ecr, ids, client.players())


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Pull your Sleeper league, roster, lineup and projections.")
    ap.add_argument("--username", required=True, help="Your Sleeper username")
    ap.add_argument("--league-id", help="Only needed if you have more than one dynasty Superflex league")
    ap.add_argument("--season", help="Defaults to the current NFL season")
    ap.add_argument("--week", type=int, help="Defaults to the current NFL week")
    ap.add_argument("--out", default="data", help="Folder for the snapshot JSON (default: data)")
    ap.add_argument("--no-projections", action="store_true", help="Skip Sleeper projections")
    ap.add_argument("--no-experts", action="store_true", help="Skip expert consensus (Sleeper projections only)")
    ap.add_argument("--expert-weight", type=float, default=0.5,
                    help="Weight on expert consensus in the score, 0-1 (default 0.5, from the Weeks 1-9 backtest)")
    ap.add_argument("--no-stats", action="store_true", help="Skip the advanced-stats view")
    ap.add_argument("--html", help="Also write the results page to this path, e.g. site/index.html")
    ap.add_argument("--notify", action="store_true",
                    help="Send a phone alert via ntfy when something changes (topic from NTFY_TOPIC)")
    args = ap.parse_args(argv)

    try:
        sys.stdout.reconfigure(encoding="utf-8")  # Windows console: accented player names
    except Exception:
        pass

    last_sent = None
    sent_path = Path(args.out) / "last_alert.json"
    if sent_path.exists():
        try:
            last_sent = json.loads(sent_path.read_text(encoding="utf-8"))
        except Exception:
            last_sent = None

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

        ids_text = load_ids_text()
        consensus = None
        if not args.no_experts:
            consensus = load_consensus(client, schedule, ids_text)
        stats_source = None if args.no_stats else load_stats_source(season, ids_text)

        snap = build_snapshot(client, args.username, season, week, args.league_id,
                              schedule=schedule, fetch_proj=not args.no_projections,
                              consensus=consensus, weight=args.expert_weight, stats_source=stats_source)

        from . import grades as grades_mod
        try:
            snap.grades = grades_mod.update(args.out, snap.season, snap.week, snap.league["league_id"],
                                            snap.me["roster_id"], client.get)
        except Exception as e:  # the report card is an extra; never fail the run over it
            print(f"Warning: report card not updated ({e})", file=sys.stderr)
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
        from .notify import alert_key, build_alert, send
        topic = os.environ.get("NTFY_TOPIC", "").strip()
        alert = build_alert(snap.to_dict(), last_sent)
        if not topic:
            print("Alerts skipped: NTFY_TOPIC is not set.")
        elif alert is None:
            print("No alert: nothing changed since the last run.")
        else:
            try:
                send(topic, alert[0], alert[1], os.environ.get("PAGE_URL") or None)
                sent_path.parent.mkdir(parents=True, exist_ok=True)
                sent_path.write_text(json.dumps(alert_key(snap.to_dict())), encoding="utf-8")
                print(f"Alert sent: {alert[0]}")
            except Exception as e:  # an alert failure shouldn't fail the run
                print(f"Warning: alert not sent ({e})", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
