"""Tests against Sleeper- and nflverse-shaped sample data (no network).

    py -m unittest discover -s tests
"""

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from sitstart.projections import normalize, score_stats
from sitstart.schedule import Schedule, eastern_to_utc, parse_week
from sitstart.sleeper import (
    SleeperError, build_snapshot, format_summary, pick_league, save_snapshot,
    scoring_summary, starting_slots,
)

SLOTS = ["QB", "RB", "RB", "WR", "WR", "WR", "TE", "FLEX", "SUPER_FLEX", "BN", "BN", "BN", "BN", "BN"]
SCORING = {"rec": 0.5, "pass_td": 4.0, "pass_yd": 0.04, "pass_int": -2.0, "rush_yd": 0.1,
           "rush_td": 6.0, "rec_yd": 0.1, "rec_td": 6.0, "fum_lost": -2.0, "bonus_rec_te": 0}

PLAYERS = {
    "100": {"full_name": "Qb One", "position": "QB", "fantasy_positions": ["QB"], "team": "WAS", "age": 26},
    "101": {"full_name": "Qb Two", "position": "QB", "fantasy_positions": ["QB"], "team": "LAR", "age": 24},
    "200": {"full_name": "Rb One", "position": "RB", "fantasy_positions": ["RB"], "team": "ATL", "age": 24},
    "201": {"full_name": "Rb Two", "position": "RB", "fantasy_positions": ["RB"], "team": "DET", "age": 26,
            "injury_status": "Questionable"},
    "202": {"full_name": "Rb Three", "position": "RB", "fantasy_positions": ["RB"], "team": "NYJ", "age": 22},
    "300": {"full_name": "Wr One", "position": "WR", "fantasy_positions": ["WR"], "team": "CIN", "age": 26},
    "301": {"full_name": "Wr Two", "position": "WR", "fantasy_positions": ["WR"], "team": "CHI", "age": 24},
    "302": {"full_name": "Wr Three", "position": "WR", "fantasy_positions": ["WR"], "team": "DAL", "age": 25,
            "injury_status": "Out"},
    "303": {"full_name": "Wr Four", "position": "WR", "fantasy_positions": ["WR"], "team": "JAX", "age": 25},
    "304": {"full_name": "Wr Rookie", "position": "WR", "fantasy_positions": ["WR"], "team": "TEN", "age": 21},
    "400": {"full_name": "Te One", "position": "TE", "fantasy_positions": ["TE"], "team": "NYG", "age": 23},
    "401": {"full_name": "Te Two", "position": "TE", "fantasy_positions": ["TE"], "team": "ATL", "age": 22},
    "500": {"full_name": "Opp Qb", "position": "QB", "fantasy_positions": ["QB"], "team": "KC", "age": 31},
}

# Sleeper app-endpoint shape: a list of entries with nested stats.
PROJ_APP = [
    {"player_id": "100", "stats": {"pass_yd": 250, "pass_td": 1.8, "pass_int": 0.7, "rush_yd": 30, "pts_half_ppr": 17.8}},
    {"player_id": "200", "stats": {"rush_yd": 80, "rush_td": 0.6, "rec": 3, "rec_yd": 20, "pts_half_ppr": 15.1}},
    {"player_id": "202", "stats": {"rush_yd": 50, "rec": 2, "rec_yd": 12, "pts_half_ppr": 7.2}},
    {"player_id": "400", "stats": {"rec": 5, "rec_yd": 55, "rec_td": 0.4, "pts_half_ppr": 10.4}},
    {"player_id": "301", "stats": {"rec": 6, "rec_yd": 70, "pts_half_ppr": 10.0}},
]

ROUTES = {
    "state/nfl": {"week": 10, "display_week": 10, "season": "2026", "league_season": "2026"},
    "user/tim": {"user_id": "u1", "display_name": "tim"},
    "user/u1/leagues/nfl/2026": [
        {"league_id": "L-redraft", "name": "Work League", "settings": {"type": 0},
         "roster_positions": ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "BN"]},
        {"league_id": "L-dyn", "name": "The Dynasty", "total_rosters": 12,
         "settings": {"type": 2, "taxi_slots": 3, "reserve_slots": 2, "playoff_week_start": 15},
         "roster_positions": SLOTS, "scoring_settings": SCORING},
    ],
    "league/L-dyn/rosters": [
        {"roster_id": 1, "owner_id": "u1",
         "players": ["100", "101", "200", "201", "202", "300", "301", "302", "303", "304", "400", "401"],
         "starters": ["100", "200", "201", "300", "301", "302", "400", "303", "101"],
         "taxi": ["304"], "reserve": [], "settings": {"wins": 6, "losses": 3}},
        {"roster_id": 2, "owner_id": "u2", "players": ["500"], "starters": ["500"] + ["0"] * 8,
         "settings": {"wins": 7, "losses": 2}},
    ],
    "league/L-dyn/users": [
        {"user_id": "u1", "display_name": "tim", "metadata": {"team_name": "Tim's Team"}},
        {"user_id": "u2", "display_name": "rival", "metadata": {}},
    ],
    # This week's lineup differs from the roster default: Rb Three over Rb Two, Superflex empty.
    "league/L-dyn/matchups/10": [
        {"roster_id": 1, "matchup_id": 3,
         "starters": ["100", "200", "202", "300", "301", "302", "400", "303", "0"]},
        {"roster_id": 2, "matchup_id": 3, "starters": ["500"] + ["0"] * 8},
    ],
}

# Trimmed from the real nflverse games.csv, 2026 Week 10 (CHI, DEN, PHI, TB on bye).
GAMES_CSV = """game_id,season,game_type,week,gameday,weekday,gametime,away_team,away_score,home_team,home_score,spread_line,total_line
2026_10_WAS_NYG,2026,REG,10,2026-11-12,Thursday,20:15,WAS,,NYG,,2.5,40.5
2026_10_NE_DET,2026,REG,10,2026-11-15,Sunday,09:30,NE,,DET,,2.5,51.5
2026_10_KC_ATL,2026,REG,10,2026-11-15,Sunday,13:00,KC,,ATL,,-3.5,45.5
2026_10_NYJ_CIN,2026,REG,10,2026-11-15,Sunday,13:00,NYJ,,CIN,,6.5,44.5
2026_10_LA_DAL,2026,REG,10,2026-11-15,Sunday,16:25,LA,,DAL,,-2.5,48.5
2026_10_TEN_JAX,2026,REG,10,2026-11-16,Monday,20:15,TEN,,JAX,,3.0,41.0
2026_09_CHI_PHI,2026,REG,9,2026-11-08,Sunday,13:00,CHI,,PHI,,1.5,44.0
2026_09_DEN_TB,2026,REG,9,2026-11-08,Sunday,13:00,DEN,,TB,,1.5,44.0
"""

# Friday after the Thursday game: WAS and NYG players are locked, nobody else.
FRIDAY = datetime(2026, 11, 13, 18, 0, tzinfo=timezone.utc)


class FakeClient:
    def __init__(self, routes, proj=PROJ_APP):
        self.routes = routes
        self.proj = proj
        self.urls = []

    def get(self, path):
        return json.loads(json.dumps(self.routes.get(path)))

    def get_url(self, url):
        self.urls.append(url)
        return json.loads(json.dumps(self.proj)) if "api.sleeper.com" in url else {}

    def players(self):
        return PLAYERS


def make_schedule():
    parsed = parse_week(GAMES_CSV, 2026, 10)
    return Schedule(parsed["games"], parsed["teams"])


class LeagueTests(unittest.TestCase):
    def setUp(self):
        self.snap = build_snapshot(FakeClient(ROUTES), "tim", schedule=make_schedule(), now=FRIDAY)

    def row(self, i):
        return self.snap.lineup[i]

    def test_picks_dynasty_superflex_league(self):
        self.assertEqual(self.snap.league["league_id"], "L-dyn")
        self.assertTrue(self.snap.league["is_superflex"] and self.snap.league["is_dynasty"])

    def test_current_season_and_week(self):
        self.assertEqual((self.snap.season, self.snap.week), ("2026", 10))

    def test_scoring_summary(self):
        sc = self.snap.league["scoring_summary"]
        self.assertEqual((sc["format"], sc["pass_yd_per_point"], sc["interception"]), ("Half-PPR", 25.0, -2.0))

    def test_starting_slots_drop_bench(self):
        self.assertEqual(starting_slots(SLOTS), SLOTS[:9])

    def test_uses_this_weeks_lineup_not_roster_default(self):
        self.assertEqual(self.row(2)["player"]["name"], "Rb Three")
        self.assertIsNone(self.row(8)["player"])

    def test_bench_taxi_split(self):
        self.assertEqual({c["name"] for c in self.snap.bench}, {"Qb Two", "Rb Two", "Te Two"})
        self.assertEqual([c["name"] for c in self.snap.taxi], ["Wr Rookie"])

    def test_opponent(self):
        self.assertEqual(self.snap.opponent["display_name"], "rival")
        self.assertEqual(self.snap.opponent["lineup"][0]["player"]["name"], "Opp Qb")

    def test_league_rosters_for_v2(self):
        self.assertEqual(len(self.snap.league_rosters), 2)

    def test_ambiguous_league_lists_options(self):
        leagues = [{"league_id": "a", "name": "Dynasty A", "settings": {"type": 2}, "roster_positions": ["SUPER_FLEX"]},
                   {"league_id": "b", "name": "Dynasty B", "settings": {"type": 2}, "roster_positions": ["SUPER_FLEX"]}]
        with self.assertRaises(SleeperError) as ctx:
            pick_league(leagues)
        self.assertIn("--league-id", str(ctx.exception))
        self.assertEqual(pick_league(leagues, "b")["league_id"], "b")

    def test_unknown_user(self):
        with self.assertRaises(SleeperError):
            build_snapshot(FakeClient(ROUTES), "nobody", fetch_proj=False)

    # --- new in 0.2: byes, locks, projections -------------------------------- #

    def test_bye_flag_beats_other_flags(self):
        wr_two = self.row(4)  # CHI is on bye in Week 10
        self.assertEqual(wr_two["flag"], "STARTER_ON_BYE")
        self.assertEqual(wr_two["player"]["proj_pts"], 0.0)

    def test_out_flag_still_fires(self):
        self.assertEqual(self.row(5)["flag"], "STARTER_OUT")

    def test_empty_slot_flag(self):
        self.assertEqual(self.row(8)["flag"], "EMPTY_SLOT")

    def test_thursday_players_locked_on_friday(self):
        self.assertTrue(self.row(0)["locked"])   # Qb One, WAS
        self.assertTrue(self.row(6)["locked"])   # Te One, NYG
        self.assertFalse(self.row(1)["locked"])  # Rb One, ATL plays Sunday

    def test_nothing_locked_before_thursday(self):
        snap = build_snapshot(FakeClient(ROUTES), "tim", schedule=make_schedule(),
                              now=datetime(2026, 11, 12, 12, 0, tzinfo=timezone.utc))
        self.assertFalse(any(r["locked"] for r in snap.lineup))

    def test_opponent_and_implied_total(self):
        rb = self.row(1)["player"]  # ATL home vs KC, KC favored by 3.5, total 45.5
        self.assertEqual(rb["opponent"], "vs KC")
        self.assertEqual(rb["implied_total"], 21.0)

    def test_rams_code_mapped(self):
        self.assertEqual(make_schedule().game("LAR")["opponent"], "DAL")

    def test_league_scored_projection(self):
        qb = self.row(0)["player"]  # 250*.04 + 1.8*4 - .7*2 + 30*.1 = 18.8
        self.assertAlmostEqual(qb["proj_pts"], 18.8)
        self.assertEqual(qb["proj_pts_sleeper_half"], 17.8)

    def test_projection_status_recorded(self):
        ds = self.snap.data_status
        self.assertEqual((ds["projections_source"], ds["projections_count"]), ("app", 5))
        self.assertEqual(ds["bye_teams"], ["CHI", "DEN", "PHI", "TB"])

    def test_summary_and_save(self):
        text = format_summary(self.snap)
        self.assertIn("Half-PPR, Superflex, dynasty", text)
        self.assertIn("[locked]", text)
        self.assertIn("STARTER_ON_BYE", text)
        with tempfile.TemporaryDirectory() as d:
            path = save_snapshot(self.snap, d)
            self.assertTrue(path.name.endswith("wk10.json"))
            self.assertTrue((Path(d) / "sleeper_latest.json").exists())

    def test_runs_without_schedule_or_projections(self):
        snap = build_snapshot(FakeClient(ROUTES, proj=[]), "tim")
        self.assertEqual(snap.data_status["projections_source"], "none")
        self.assertFalse(any(r["locked"] for r in snap.lineup))
        self.assertIn("Lineup warnings", format_summary(snap))


class OptimizerTests(unittest.TestCase):
    def setUp(self):
        from sitstart.optimizer import best_lineup
        self.best_lineup = best_lineup
        self.snap = build_snapshot(FakeClient(ROUTES), "tim", schedule=make_schedule(), now=FRIDAY)

    def test_locked_starters_stay_put(self):
        best = self.best_lineup(self.snap.lineup, self.snap.bench)
        self.assertEqual(best[0]["player"]["name"], "Qb One")
        self.assertEqual(best[6]["player"]["name"], "Te One")

    def test_bye_and_out_starters_replaced(self):
        spare = [{"player_id": f"9{i}", "name": f"Spare Wr {i}", "position": "WR", "fantasy_positions": ["WR"],
                  "team": "SEA", "proj_pts": 4.0} for i in range(2)]
        names = [r["player"]["name"] for r in self.best_lineup(self.snap.lineup, self.snap.bench + spare) if r["player"]]
        self.assertNotIn("Wr Two", names)    # CHI on bye
        self.assertNotIn("Wr Three", names)  # Out

    def test_flex_player_slides_into_wr_when_wr_cant_play(self):
        best = self.best_lineup(self.snap.lineup, self.snap.bench)
        wr_names = {r["player"]["name"] for r in best if r["slot"] == "WR"}
        self.assertIn("Wr Four", wr_names)                         # moved from FLEX
        self.assertEqual(len(wr_names & {"Wr Two", "Wr Three"}), 1)  # only one dead WR slot left, no spare WR
        self.assertEqual(best[7]["player"]["name"], "Te Two")      # bench TE fills FLEX

    def test_superflex_filled_from_bench(self):
        best = self.best_lineup(self.snap.lineup, self.snap.bench)
        self.assertEqual(best[8]["player"]["name"], "Qb Two")

    def test_suggestion_recorded(self):
        sug = self.snap.suggestion
        self.assertEqual({c["name"] for c in sug["start"]}, {"Qb Two", "Te Two"})
        self.assertEqual(len(sug["sit"]), 1)
        self.assertIn(sug["sit"][0]["name"], {"Wr Two", "Wr Three"})
        self.assertTrue(sug["slot_moves"])

    def test_flex_tiebreak_prefers_later_kickoff(self):
        def card(pid, pos, pts, ko):
            return {"player_id": pid, "name": pid, "position": pos, "fantasy_positions": [pos],
                    "team": "X", "proj_pts": pts, "kickoff_utc": ko}
        lineup = [{"slot": "FLEX", "player": card("early", "RB", 10.0, "2026-11-15T18:00:00+00:00"), "locked": False}]
        bench = [card("late", "WR", 9.7, "2026-11-16T01:20:00+00:00")]
        self.assertEqual(self.best_lineup(lineup, bench)[0]["player"]["name"], "late")

    def test_keeps_current_slots_when_only_one_player_changes(self):
        def card(pid, pos, pts):
            return {"player_id": pid, "name": pid, "position": pos, "fantasy_positions": [pos],
                    "team": "X", "proj_pts": pts}
        lineup = [{"slot": "WR", "player": card("weak", "WR", 6.7), "locked": False},
                  {"slot": "WR", "player": card("star", "WR", 13.0), "locked": False}]
        best = self.best_lineup(lineup, [card("better", "WR", 8.6)])
        self.assertEqual([r["player"]["name"] for r in best], ["better", "star"])

    def test_questionable_discount_can_flip_a_close_call(self):
        def card(pid, pts, inj=None):
            return {"player_id": pid, "name": pid, "position": "WR", "fantasy_positions": ["WR"],
                    "team": "X", "proj_pts": pts, "injury_status": inj}
        lineup = [{"slot": "WR", "player": card("healthy", 7.5), "locked": False}]
        self.assertEqual(self.best_lineup(lineup, [card("q", 8.6, "Questionable")])[0]["player"]["name"], "healthy")

    def test_later_kickoff_moves_into_flex_at_no_cost(self):
        def card(pid, pts, ko):
            return {"player_id": pid, "name": pid, "position": "TE", "fantasy_positions": ["TE"],
                    "team": "X", "proj_pts": pts, "kickoff_utc": ko}
        lineup = [{"slot": "TE", "player": card("late", 10.3, "2026-11-15T18:00:00+00:00"), "locked": False},
                  {"slot": "FLEX", "player": card("early", 10.5, "2026-11-15T14:30:00+00:00"), "locked": False}]
        best = self.best_lineup(lineup, [])
        self.assertEqual([r["player"]["name"] for r in best], ["early", "late"])

    def test_locked_bench_player_cannot_enter(self):
        def card(pid, pts, locked):
            return {"player_id": pid, "name": pid, "position": "RB", "fantasy_positions": ["RB"],
                    "team": "X", "proj_pts": pts, "locked": locked}
        lineup = [{"slot": "RB", "player": card("starter", 5.0, False), "locked": False}]
        self.assertEqual(self.best_lineup(lineup, [card("benched", 20.0, True)])[0]["player"]["name"], "starter")


class PageAndAlertTests(unittest.TestCase):
    def setUp(self):
        self.snap = build_snapshot(FakeClient(ROUTES), "tim", schedule=make_schedule(), now=FRIDAY).to_dict()

    def test_page_renders(self):
        from sitstart.page import render
        html = render(self.snap)
        self.assertIn("The Dynasty", html)
        self.assertIn("Suggested changes", html)
        self.assertIn("On bye", html)
        self.assertIn("Locked", html)
        self.assertIn("Thu 5:15 PM", html)  # WAS @ NYG, 8:15 PM ET

    def test_page_escapes_names(self):
        from sitstart.page import render
        snap = json.loads(json.dumps(self.snap))
        snap["me"]["team_name"] = "<script>x</script>"
        self.assertNotIn("<script>x", render(snap))

    def test_first_run_alerts(self):
        from sitstart.notify import build_alert
        title, msg = build_alert(self.snap, None)
        self.assertIn("Week 10", title)
        self.assertIn("Start", msg)

    def test_no_alert_when_nothing_changed(self):
        from sitstart.notify import alert_key, build_alert
        self.assertIsNone(build_alert(self.snap, alert_key(json.loads(json.dumps(self.snap)))))

    def test_alert_when_starter_newly_out(self):
        from sitstart.notify import alert_key, build_alert
        prev = json.loads(json.dumps(self.snap))
        prev["lineup"][5]["flag"] = None  # Wr Three wasn't Out when the last alert went out
        self.assertIsNotNone(build_alert(self.snap, alert_key(prev)))

    def test_utc_to_pacific(self):
        from sitstart.schedule import utc_to_pacific
        self.assertEqual(utc_to_pacific(datetime(2026, 11, 13, 1, 15, tzinfo=timezone.utc)).hour, 17)  # PST
        self.assertEqual(utc_to_pacific(datetime(2026, 10, 4, 17, 0, tzinfo=timezone.utc)).hour, 10)   # PDT


class ProjectionTests(unittest.TestCase):
    def test_normalize_app_list_shape(self):
        self.assertEqual(set(normalize(PROJ_APP)), {"100", "200", "202", "400", "301"})
        self.assertIn("_week", normalize([{"player_id": "1", "week": 3, "stats": {"rec": 1}}])["1"])

    def test_normalize_v1_map_shape_drops_empty_entries(self):
        self.assertEqual(normalize({"6462": {}, "100": {"pass_yd": 200}}), {"100": {"pass_yd": 200}})

    def test_te_premium_applied_when_stats_lack_bonus(self):
        stats = {"rec": 5, "rec_yd": 50}
        scoring = {"rec": 0.5, "rec_yd": 0.1, "bonus_rec_te": 0.5}
        self.assertEqual(score_stats(stats, scoring, "TE"), 10.0)
        self.assertEqual(score_stats(stats, scoring, "WR"), 7.5)

    def test_falls_back_to_v1_when_app_empty(self):
        class C:
            def get_url(self, url):
                return {"100": {"pass_yd": 200}} if "api.sleeper.app" in url else []
        from sitstart.projections import fetch_projections
        data, src = fetch_projections(C().get_url, 2026, 10)
        self.assertEqual((src, list(data)), ("v1", ["100"]))


class ScheduleTests(unittest.TestCase):
    def test_eastern_to_utc_standard_time(self):
        self.assertEqual(eastern_to_utc("2026-11-15", "13:00").hour, 18)  # EST, UTC-5

    def test_eastern_to_utc_daylight_time(self):
        self.assertEqual(eastern_to_utc("2026-10-04", "13:00").hour, 17)  # EDT, UTC-4

    def test_dst_ends_first_sunday_of_november(self):
        self.assertEqual(eastern_to_utc("2026-11-01", "13:00").hour, 18)

    def test_scoring_summary_te_premium(self):
        self.assertEqual(scoring_summary({"rec": 1, "bonus_rec_te": 0.5})["te_premium"], 0.5)


if __name__ == "__main__":
    unittest.main()


class ConsensusTests(unittest.TestCase):
    ECR = ('"page","page_pos","scrape_date","fantasypros_id","player_name","pos","team","rank","ecr","sd","best","worst","player_opponent_id","pos_rank"\n'
           '"qb","QB",2026-11-12,"1","Qb One","QB","WAS",1,1.2,0.5,1,2,"NYG","QB1"\n'
           '"ppr-wr","WR",2026-11-12,"3","Wr Two","WR","CHI",2,2.4,0.9,1,4,"NA","WR2"\n'
           '"ppr-wr","WR",2026-11-12,"4","D.J. Wr-One Jr.","WR","CIN",1,1.1,0.3,1,2,"NYJ","WR1"\n'
           '"k","K",2026-11-12,"9","Kicker","K","CIN",1,1,0,1,1,"NYJ","K1"\n')

    def test_parse_skips_non_skill_positions(self):
        from sitstart.consensus import parse_ecr
        rows = parse_ecr(self.ECR)
        self.assertEqual([r["pos"] for r in rows], ["QB", "WR", "WR"])
        self.assertEqual(rows[2]["rank"], 1)

    def test_map_by_id_then_name(self):
        from sitstart.consensus import map_to_sleeper, parse_ecr
        players = {"100": {"full_name": "Qb One", "position": "QB"},
                   "300": {"full_name": "DJ Wr One", "position": "WR"}}
        m = map_to_sleeper(parse_ecr(self.ECR), {"1": "100"}, players)
        self.assertEqual(m["100"]["rank"], 1)          # by crosswalk
        self.assertEqual(m["300"]["name"], "D.J. Wr-One Jr.")  # by normalized name

    def test_expert_points_use_projection_ladder(self):
        from sitstart.consensus import expert_points
        cons = {"a": {"pos": "WR", "rank": 1}, "b": {"pos": "WR", "rank": 3}, "c": {"pos": "WR", "rank": 9}}
        P = {"a": 10.0, "b": 15.0, "x": 12.0}
        E = expert_points(cons, P, {"a": "WR", "b": "WR", "c": "WR", "x": "WR"})
        self.assertEqual(E, {"a": 15.0, "b": 10.0, "c": 0.0})

    def test_blend(self):
        from sitstart.consensus import blend
        self.assertEqual(blend(10, 14, 0.5), 12.0)
        self.assertEqual(blend(10, None, 0.5), 10.0)
        self.assertEqual(blend(None, 8, 0.0), 0.0)

    def test_stale_snapshot_detected(self):
        from sitstart.consensus import matches_week, parse_ecr
        games = make_schedule().games
        rows = parse_ecr(self.ECR) * 10
        self.assertTrue(matches_week(rows, games))
        for r in rows:
            r["opponent"] = "BUF"
        self.assertFalse(matches_week(rows, games))


class BacktestTests(unittest.TestCase):
    def test_week_scoring(self):
        from sitstart.backtest import run_week, summarize
        players = {"q1": {"full_name": "Q1", "position": "QB"}, "q2": {"full_name": "Q2", "position": "QB"},
                   "w1": {"full_name": "W1", "position": "WR"}, "w2": {"full_name": "W2", "position": "WR"}}
        slots = ["QB", "WR"]
        m = [{"roster_id": 1, "players": ["q1", "q2", "w1", "w2"], "starters": ["q1", "w1"],
              "players_points": {"q1": 10, "q2": 25, "w1": 5, "w2": 12}}]
        P = {"q1": 18, "q2": 16, "w1": 9, "w2": 10}      # Sleeper likes q1, w2
        E = {"q1": 15, "q2": 20, "w1": 8, "w2": 11}      # experts like q2, w2
        rows = run_week(1, slots, m, players, P, E, set())
        r = rows[0]
        self.assertEqual((r["actual"], r["hindsight"]), (15.0, 37.0))
        self.assertEqual(r["w0.0"], 22.0)   # q1 + w2
        self.assertEqual(r["w1.0"], 37.0)   # q2 + w2
        s = summarize(rows, 1)
        self.assertEqual(s["best_weight"], 0.5)  # 0.5..1.0 tie at 37; pick the one nearest 0.5
        self.assertEqual(s["my_team"]["totals"]["actual"], 15.0)

    def test_taxi_players_excluded(self):
        from sitstart.backtest import run_week
        players = {"q1": {"full_name": "Q1", "position": "QB"}, "q2": {"full_name": "Q2", "position": "QB"}}
        m = [{"roster_id": 1, "players": ["q1", "q2"], "starters": ["q1"], "players_points": {"q1": 5, "q2": 30}}]
        rows = run_week(1, ["QB"], m, players, {"q1": 1, "q2": 20}, {}, {"q2"})
        self.assertEqual(rows[0]["hindsight"], 5.0)
