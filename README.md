# sitstart: Step 1, Sleeper connector (v0.2, Nov 11 2026)

Pulls your dynasty Superflex league from Sleeper and the NFL schedule from nflverse, then saves a JSON snapshot for the scoring model (step 3). It's free, needs no API keys, and uses only the Python standard library.

For you and every player on your roster, it pulls:
- League scoring settings and starting slots.
- Your lineup as set for this week, plus bench, taxi, IR and your opponent's lineup.
- **Projected points in your league's exact scoring.** Sleeper's projected stat lines are multiplied by your `scoring_settings`, with Sleeper's own half-PPR number kept as a cross-check.
- **Opponent, kickoff time and Vegas implied team total.**
- **Bye and lock status:** players whose game has kicked off are marked `[locked]`.
- Warnings for empty slots, starters on bye, starters who are Out, and players in slots they can't fill.

## Run it on Windows

1. Install Python 3.10 or newer if you don't have it. In PowerShell, run `py --version`. If that fails, run `winget install Python.Python.3.12`.
2. Unzip this folder, e.g. to `Documents\sitstart`.
3. In PowerShell:

```powershell
cd $HOME\Documents\sitstart
py -m sitstart --username YOUR_SLEEPER_USERNAME
```

Output is saved to `data\sleeper_2026_wk10.json` and `data\sleeper_latest.json`.

If you're in more than one dynasty Superflex league, it lists them and asks for `--league-id <id>`.

## Options

| Flag | Default | Use |
| --- | --- | --- |
| `--username` | required | Your Sleeper username |
| `--league-id` | auto-detected | Pick a league when you have several |
| `--week` | current NFL week | Look at a past or future week |
| `--season` | current season | |
| `--out` | `data` | Where snapshots go |
| `--no-projections` | off | Skip Sleeper projections |

## Tests

```powershell
py -m unittest discover -s tests
```

## Things to check on your first real run

- **The `Projections:` line.** It should say `app` with a few hundred players. `v1` means the fallback endpoint worked. `none` means neither endpoint returned data; everything else still runs.
- **Projected points vs Sleeper's app.** For a few starters, `proj` should be close to what Sleeper shows. Small differences are expected where your league's scoring differs from standard half-PPR.
- **Byes** should match this week's actual byes (Week 10: CHI, DEN, PHI, TB).

## Automatic runs on GitHub

`.github/workflows/lineup.yml` runs the check four times a week:

- Tuesday at 7:07 PM PT.
- Thursday at 2:37 PM PT, before Thursday night kickoff.
- Saturday at 7:07 PM PT.
- Sunday at 8:40 AM PT, after early-game inactives post.

Each run does three things:
1. Publishes the results page to `https://thwangbo.github.io/sitstart/`.
2. Saves the snapshot in `data/`, which builds a history for the weekly grader.
3. Sends a phone alert through [ntfy](https://ntfy.sh), but only when a recommendation or a starter's status changes.

To run it on demand, go to the repo's **Actions** tab, choose **Lineup check**, then **Run workflow**.

Settings it uses:
- **Secret `NTFY_TOPIC`:** your private alert topic. Keep it secret; anyone who knows it can read your alerts.
- **Variable `SLEEPER_USERNAME`:** optional. It defaults to `thwangbo`.

## Notes

- The player list (~5 MB) is cached in `.cache` for 24 hours, and the schedule for 6 hours.
- Sleeper's projections endpoints are undocumented. The connector tries `api.sleeper.com` first, then the old `api.sleeper.app/v1` path, which started returning empty data in September 2026.
- If the schedule can't be downloaded, the run continues with bye and lock checks turned off.
