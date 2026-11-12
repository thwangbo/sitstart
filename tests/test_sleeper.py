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


class BlendInSnapshotTests(unittest.TestCase):
    def test_score_blends_and_drives_suggestion(self):
        # Experts rank Qb Two as QB1 (expert pts = best QB projection 18.8); Sleeper gives him nothing.
        cons = {"101": {"pos": "QB", "rank": 1, "scrape_date": "2026-11-12"},
                "100": {"pos": "QB", "rank": 2, "scrape_date": "2026-11-12"}}
        proj = PROJ_APP + [{"player_id": "101", "stats": {"pass_yd": 100}}]   # 4.0 pts
        snap = build_snapshot(FakeClient(ROUTES, proj=proj), "tim", schedule=make_schedule(), now=FRIDAY,
                              consensus=cons, weight=0.5)
        qb2 = next(c for c in snap.bench if c["name"] == "Qb Two")
        self.assertEqual(qb2["consensus_rank"], "QB1")
        self.assertEqual(qb2["expert_pts"], 18.8)
        self.assertAlmostEqual(qb2["score"], 11.4)   # 4.0 + 0.5 * (18.8 - 4.0)
        self.assertEqual(snap.data_status["blend_weight"], 0.5)
        self.assertIn("50% expert consensus", format_summary(snap))

    def test_without_consensus_score_equals_projection(self):
        snap = build_snapshot(FakeClient(ROUTES), "tim", schedule=make_schedule(), now=FRIDAY)
        qb = snap.lineup[0]["player"]
        self.assertEqual(qb["score"], qb["proj_pts"])
        self.assertIn("unavailable", format_summary(snap))


class StatsTests(unittest.TestCase):
    EP = ("season,week,player_id,full_name,position,receptions_exp,rec_yards_gained_exp,rec_touchdown_exp,"
          "rush_yards_gained_exp,rush_touchdown_exp,pass_yards_gained_exp,pass_touchdown_exp,pass_interception_exp\n"
          "2026,1,G1,Wr One,WR,4,50,0.2,0,0,0,0,0\n"      # 2 + 5 + 1.2 = 8.2
          "2026,2,G1,Wr One,WR,6,80,0.5,0,0,0,0,0\n"      # 3 + 8 + 3 = 14.0
          "2026,3,G1,Wr One,WR,8,100,0.5,0,0,0,0,0\n"     # 4 + 10 + 3 = 17.0
          "2026,1,G2,Te One,TE,4,40,0,0,0,0,0,0\n"
          "2026,2,G9,Kicker Guy,K,0,0,0,0,0,0,0,0\n")

    def test_expected_points_in_league_scoring(self):
        from sitstart.stats import parse_ep
        ep = parse_ep(self.EP, SCORING)
        self.assertEqual([round(x, 1) for _, x in ep["G1"]], [8.2, 14.0, 17.0])
        self.assertNotIn("G9", ep)

    def test_te_premium_in_expected_points(self):
        from sitstart.stats import parse_ep
        ep = parse_ep(self.EP, {**SCORING, "bonus_rec_te": 0.5})
        self.assertAlmostEqual(ep["G2"][0][1], 4 * 0.5 + 40 * 0.1 + 4 * 0.5)

    def test_recency_weighting_uses_only_prior_weeks(self):
        from sitstart.stats import parse_ep, recent_xfp
        hist = parse_ep(self.EP, SCORING)["G1"]
        val, n, trend = recent_xfp(hist, before_week=3)   # weeks 1-2 only: (14*.4 + 8.2*.3) / .7
        self.assertEqual(n, 2)
        self.assertAlmostEqual(val, round((14.0 * 0.4 + 8.2 * 0.3) / 0.7, 2))
        self.assertIsNone(trend)

    def test_matchup_factor(self):
        from sitstart.stats import matchup_factor
        games = {"A": {"implied_total": 30.0}, "B": {"implied_total": 20.0}}
        self.assertEqual(matchup_factor("A", games), 1.1)
        self.assertEqual(matchup_factor("B", games), 0.9)
        self.assertEqual(matchup_factor("Z", games), 1.0)

    def test_adjustment_capped_and_needs_two_games(self):
        from sitstart.stats import stat_adjustment
        self.assertEqual(stat_adjustment(10.0, {"stat_pts": 20.0, "games": 3}), 0.15)
        self.assertEqual(stat_adjustment(10.0, {"stat_pts": 9.0, "games": 3}), -0.1)
        self.assertIsNone(stat_adjustment(10.0, {"stat_pts": 20.0, "games": 1}))
        self.assertIsNone(stat_adjustment(0.5, {"stat_pts": 5.0, "games": 3}))

    def test_snapshot_carries_shadow_fields_without_changing_suggestion(self):
        stats = {"100": {"stat_pts": 30.0, "xfp": 28.0, "games": 4, "trend": 2.0, "matchup": 1.07}}
        base = build_snapshot(FakeClient(ROUTES), "tim", schedule=make_schedule(), now=FRIDAY)
        snap = build_snapshot(FakeClient(ROUTES), "tim", schedule=make_schedule(), now=FRIDAY, stats=stats)
        qb = snap.lineup[0]["player"]
        self.assertEqual(qb["stat_adj"], 0.15)
        self.assertAlmostEqual(qb["score_with_stats"], round(qb["score"] * 1.15, 2))
        self.assertEqual(snap.suggestion, base.suggestion)     # shadow: recommendations unchanged
        self.assertIsNotNone(snap.stats_view)


class GradeTests(unittest.TestCase):
    def setUp(self):
        self.snap = build_snapshot(FakeClient(ROUTES), "tim", schedule=make_schedule(), now=FRIDAY).to_dict()
        # Actual results: Qb Two (bench) blew up; Wr One scored 20.
        self.mine = {"roster_id": 1, "starters": ["100", "200", "202", "300", "301", "302", "400", "303", "0"],
                     "players_points": {"100": 15, "101": 30, "200": 10, "202": 4, "300": 20, "301": 0,
                                        "302": 0, "303": 6, "400": 8, "401": 1, "201": 12}}

    def test_grade_week(self):
        from sitstart.grades import grade_week
        g = grade_week(self.snap, self.mine)
        self.assertEqual(g["you"], 63.0)
        self.assertEqual(g["app"], 94.0)    # app also starts Qb Two (Superflex) and Te Two (FLEX)
        self.assertGreaterEqual(g["best"], g["app"])
        self.assertIsNone(g["stats"])       # no stats data in this snapshot

    def test_update_grades_finished_weeks_and_seeds_backtest(self):
        from sitstart import grades
        with tempfile.TemporaryDirectory() as d:
            snap9 = dict(self.snap, week=9)
            Path(d, "sleeper_2026_wk09.json").write_text(json.dumps(snap9))
            Path(d, "sleeper_2026_wk10.json").write_text(json.dumps(self.snap))   # current week: not graded
            bt = Path(d, "results.json")
            bt.write_text(json.dumps({"rows": [
                {"week": 1, "roster_id": 1, "actual": 100, "w0.0": 98, "w0.5": 101, "hindsight": 130},
                {"week": 1, "roster_id": 2, "actual": 90, "w0.0": 91, "w0.5": 92, "hindsight": 120}]}))
            get = lambda path: [self.mine] if path.endswith("/matchups/9") else []
            out = grades.update(d, "2026", 10, "L-dyn", 1, get, backtest_results=bt)
            self.assertEqual([(g["week"], g["source"]) for g in out], [(1, "backtest"), (9, "live")])
            self.assertEqual(out[1]["you"], 63.0)
            self.assertEqual(json.loads(Path(d, "grades.json").read_text())[0]["app"], 101)

    def test_stats_streak(self):
        from sitstart.grades import stats_streak
        g = [{"week": w, "app": 100, "stats": 101} for w in (7, 8, 9)]
        self.assertTrue(stats_streak(g))
        g[1]["stats"] = 99
        self.assertFalse(stats_streak(g))

    def test_page_shows_report_card(self):
        from sitstart.page import render
        snap = dict(self.snap, grades=[{"week": 9, "source": "live", "you": 63, "app": 94, "sleeper": 90, "stats": None, "best": 99}])
        html = render(snap)
        self.assertIn("Report card", html)
        self.assertIn("94.0", html)


class MarketTests(unittest.TestCase):
    FC = [
        {"player": {"sleeperId": "q1", "name": "Vet QB", "position": "QB", "maybeAge": 33, "maybeTeam": "AAA"}, "value": 3000, "redraftValue": 6000},
        {"player": {"sleeperId": "q2", "name": "Young QB", "position": "QB", "maybeAge": 23, "maybeTeam": "BBB"}, "value": 7000, "redraftValue": 4000},
        {"player": {"sleeperId": "q3", "name": "Backup QB", "position": "QB", "maybeAge": 28, "maybeTeam": "CCC"}, "value": 1500, "redraftValue": 2000},
        {"player": {"sleeperId": "q4", "name": "Bench QB", "position": "QB", "maybeAge": 27, "maybeTeam": "DDD"}, "value": 1400, "redraftValue": 1800},
        {"player": {"sleeperId": "r1", "name": "Old RB", "position": "RB", "maybeAge": 29, "maybeTeam": "EEE"}, "value": 2500, "redraftValue": 5000},
        {"player": {"sleeperId": "r2", "name": "Weak RB", "position": "RB", "maybeAge": 25, "maybeTeam": "FFF"}, "value": 1200, "redraftValue": 900},
        {"player": {"sleeperId": "r3", "name": "Kid RB", "position": "RB", "maybeAge": 22, "maybeTeam": "GGG"}, "value": 2600, "redraftValue": 800},
        {"player": {"name": "2027 1st (Early)", "position": "PICK"}, "value": 5000},
        {"player": {"name": "2027 1st (Late)", "position": "PICK"}, "value": 2500},
        {"player": {"name": "2027 1st", "position": "PICK"}, "value": 3000},
        {"player": {"name": "2028 1st", "position": "PICK"}, "value": 2200},
        {"player": {"name": "2028 2nd", "position": "PICK"}, "value": 1400},
    ]
    SLOTS = ["QB", "RB", "SUPER_FLEX"]

    def market(self):
        from sitstart.market import parse_fantasycalc
        return parse_fantasycalc(self.FC)

    def teams(self):
        from sitstart.market import build_profiles
        m = self.market()
        pos = {pid: p["pos"] for pid, p in m.players.items()}
        rosters = [
            {"roster_id": 1, "owner_id": "me", "players": ["q2", "q3", "q4", "r2", "r3"], "settings": {"wins": 8, "losses": 1, "fpts": 900}},
            {"roster_id": 2, "owner_id": "u2", "players": ["q1"], "settings": {"wins": 1, "losses": 8, "fpts": 500}},
            {"roster_id": 3, "owner_id": "u3", "players": ["r1"], "settings": {"wins": 5, "losses": 4, "fpts": 700}},
        ]
        users = [{"user_id": "me", "display_name": "me"}, {"user_id": "u2", "display_name": "seller"},
                 {"user_id": "u3", "display_name": "mid"}]
        traded = [{"season": "2027", "round": 1, "roster_id": 2, "owner_id": 1}]   # I own the seller's 2027 1st
        return m, pos, build_profiles(rosters, users, m, self.SLOTS, pos, traded, [], 2026, 2)

    def test_pick_values_and_fallback(self):
        m = self.market()
        self.assertEqual(m.pick_value("2027", 1, "Early"), 5000)
        self.assertEqual(m.pick_value("2028", 1, "Early"), 2200)    # no tiers listed for 2028
        self.assertEqual(m.pick_value("2030", 1), 2200)             # unlisted season: latest listed
        self.assertEqual(m.pick_value("2028", 2), 1400)

    def test_pick_ownership_and_tiers(self):
        m, pos, teams = self.teams()
        mine = {p["label"] for p in teams[1].picks}
        self.assertIn("2027 1st (Early)", mine)     # seller is last in standings -> early pick
        self.assertIn("2027 1st (Late)", mine)      # my own, I'm first
        self.assertFalse(any(p["season"] == "2027" and p["round"] == 1 for p in teams[2].picks))

    def test_lifecycle_labels(self):
        _, _, teams = self.teams()
        self.assertEqual(teams[1].label, "contender")
        self.assertEqual(teams[2].label, "rebuilder")

    def test_targets_buy_vet_from_rebuilder_with_surplus(self):
        from sitstart.trades import find_targets
        m, pos, teams = self.teams()
        res = find_targets(teams, teams[1], m, self.SLOTS, pos)
        names = [t["name"] for t in res["targets"]]
        self.assertEqual(names[0], "Vet QB")         # biggest win-now gain, rebuilding seller, he's 33
        t = res["targets"][0]
        self.assertEqual(t["motive"], 1.0)
        offered = {a["label"] for a in t["offer"]["assets"]}
        self.assertNotIn("Young QB", offered)        # my starters are never offered
        self.assertTrue(1.0 <= t["offer"]["ratio"] <= 1.2)

    def test_qb_guard_and_protect(self):
        from sitstart.trades import my_assets, qb_safe
        m, pos, teams = self.teams()
        me = teams[1]
        assets = my_assets(me, m, pos, protect={"q4"})
        self.assertNotIn("Bench QB", [a["label"] for a in assets])
        backup = next(a for a in my_assets(me, m, pos) if a["label"] == "Bench QB")
        self.assertFalse(qb_safe(me, m, [backup], "RB"))   # would leave 2 startable QBs
        self.assertTrue(qb_safe(me, m, [backup], "QB"))    # unless a QB comes back

    def test_offer_rejects_pile_of_small_pieces(self):
        from sitstart.trades import build_offer
        m, pos, teams = self.teams()
        small = [{"kind": "pick", "id": str(i), "label": f"p{i}", "pos": None, "age": None, "value": 1000, "redraft": 0}
                 for i in range(3)]
        self.assertIsNone(build_offer(3000, "RB", teams[2], teams[1], m, small))

    def test_trades_page_renders(self):
        from sitstart.trades import find_targets, position_needs
        from sitstart.trades_page import render
        m, pos, teams = self.teams()
        me = teams[1]
        res = find_targets(teams, me, m, self.SLOTS, pos)
        row = lambda t: {"roster_id": t.roster_id, "name": t.name, "wins": t.wins, "losses": t.losses,
                         "record_rank": t.record_rank, "win_now_rank": t.win_now_rank, "dynasty_rank": t.dynasty_rank,
                         "age": t.age, "youth": t.youth, "label": t.label, "reasons": t.reasons, "picks": []}
        rep = {"week": 10, "deadline_week": 12, "me": row(me), "needs": position_needs(teams, me, m),
               "targets": res["targets"], "out_of_reach": res["out_of_reach"], "my_assets": res["assets"],
               "teams": [row(t) for t in teams.values()], "generated_at": "2026-11-12T17:00:00+00:00"}
        html = render(rep)
        self.assertIn("Vet QB", html)
        self.assertIn("2 weeks left", html)
        rep["targets"][0]["injury_status"] = "Questionable"
        self.assertIn("tag inj", render(rep))


class KtcTests(unittest.TestCase):
    HTML = ('<html><body><script type="application/json" id="ktc-players">'
            + json.dumps([
                {"playerName": "Vet QB", "position": "QB", "team": "AAA", "age": 33, "mflid": 111,
                 "superflexValues": {"value": 6000}, "oneQBValues": {"value": 3000}},
                {"playerName": "Young QB", "position": "QB", "team": "BBB", "age": 23, "mflid": 222,
                 "superflexValues": {"value": 9000}, "oneQBValues": {"value": 5000}},
                {"playerName": "Kid RB", "position": "RB", "team": "GGG", "age": 22, "mflid": 0,
                 "superflexValues": {"value": 3000}, "oneQBValues": {"value": 3000}},
                {"playerName": "Only In KTC", "position": "WR", "team": "HHH", "age": 21, "mflid": 999,
                 "superflexValues": {"value": 500}, "oneQBValues": {"value": 500}},
                {"playerName": "2027 Early 1st", "position": "RDP", "superflexValues": {"value": 7000}, "oneQBValues": {"value": 7000}},
                {"playerName": "2028 Mid 1st", "position": "RDP", "superflexValues": {"value": 4000}, "oneQBValues": {"value": 4000}},
                {"playerName": "Kicker", "position": "PK", "superflexValues": {"value": 100}},
            ]) + '</script></body></html>')

    def test_parse(self):
        from sitstart.ktc import parse
        rows = parse(self.HTML, superflex=True)
        self.assertEqual(len(rows), 6)                       # kicker dropped
        picks = {r["pick_label"]: r["value"] for r in rows if r["pick_label"]}
        self.assertEqual(picks, {"2027 1st (Early)": 7000.0, "2028 1st (Mid)": 4000.0})
        self.assertEqual(parse(self.HTML, superflex=False)[0]["value"], 3000.0)

    def test_layout_change_raises(self):
        from sitstart.ktc import parse
        with self.assertRaises(ValueError):
            parse("<html>nothing here</html>")

    def test_rank_scaler_is_rank_for_rank(self):
        from sitstart.market import rank_scaler
        sc = rank_scaler([900, 800, 700, 600, 500], [100, 90, 80])
        self.assertEqual(sc(900), 100)
        self.assertEqual(sc(800), 90)
        self.assertEqual(sc(850), 95)          # halfway between 1st and 2nd
        self.assertAlmostEqual(sc(600), 80 * 600 / 700)   # deeper than the target list: tapered

    def test_blend(self):
        from sitstart.ktc import parse
        from sitstart.market import blend_ktc, parse_fantasycalc
        fc_rows = [dict(r) for r in MarketTests.FC]
        fc_rows[0] = {**fc_rows[0], "player": {**fc_rows[0]["player"], "mflId": "111"}}
        fc_rows[1] = {**fc_rows[1], "player": {**fc_rows[1]["player"], "mflId": "222"}}
        fc = parse_fantasycalc(fc_rows)
        m, status = blend_ktc(fc, fc_rows, parse(self.HTML), mfl_to_sleeper={"999": "w9"})
        self.assertEqual(status["ktc_players_mapped"], 4)            # by MFL id (3) and by name (Kid RB)
        yq = m.player("q2")
        self.assertEqual(yq["fc_value"], 7000)
        self.assertIsNotNone(yq["ktc_value"])
        self.assertAlmostEqual(yq["value"], (yq["fc_value"] + yq["ktc_value"]) / 2, places=1)
        self.assertEqual(m.redraft("q1"), 6000)                      # win-now stays FantasyCalc
        self.assertIn("w9", m.players)                               # KTC-only player added
        self.assertEqual(m.players["w9"]["fc_value"], None)
        self.assertIn("2028 1st (Mid)", m.picks)
        from sitstart.market import rank_scaler
        sc = rank_scaler([k["value"] for k in parse(self.HTML)], list(fc.picks.values()) + [p["value"] for p in fc.players.values()])
        self.assertAlmostEqual(m.pick_value("2027", 1, "Early"), round((5000 + sc(7000)) / 2, 1))   # averaged
        self.assertAlmostEqual(m.pick_value("2028", 1), round((2200 + sc(4000)) / 2, 1))            # generic = KTC Mid

    def test_unmapped_counted_not_crashing(self):
        from sitstart.ktc import parse
        from sitstart.market import blend_ktc, parse_fantasycalc
        fc = parse_fantasycalc(MarketTests.FC)
        m, status = blend_ktc(fc, MarketTests.FC, parse(self.HTML))
        self.assertGreaterEqual(status["ktc_players_unmapped"], 1)    # "Only In KTC" has no match
