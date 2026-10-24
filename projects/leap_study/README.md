# Leap study

Status: season-by-season scoring database and player selection analysis are
implemented. The threshold for a "leap" and visualizations are next.

## Research plan

- Question: When does a player's scoring make a leap and settle toward their
  established level?
- Player selection: NBA debut classes from 2000-01 onward, including short
  careers and undrafted players; no minimum games or scoring cutoff.
- Date ranges: 2000-01 through 2025-26 by default, regular season only.
- Metrics and definition of a leap: TBD
- Data sources: NBA statistics through the shared `cards_tracker.NBAClient`;
  additional sources as needed.

## Workspace

- `analysis/`: project-specific searches and calculations.
- `data/raw/`: saved source data with query parameters and retrieval dates.
- `data/processed/`: derived tables used to support article claims.
- `figures/`: charts and images for publication.
- `articles/`: Substack article drafts in Markdown, starting with
  [01_leap_study.md](articles/01_leap_study.md).

Import shared tools rather than copying API code into this project:

```python
from cards_tracker import NBAClient

nba = NBAClient()
```

## Build the database

From the repository root:

```powershell
.\.env\Scripts\python.exe .\projects\leap_study\analysis\build_database.py
```

Optional season range and refresh:

```powershell
.\.env\Scripts\python.exe .\projects\leap_study\analysis\build_database.py --start-season 2000-01 --through-season 2025-26 --refresh
```

The default ending season is explicitly 2025-26; advance `--through-season` when
you want newer seasons. Choosing a season still in progress produces season-to-date
totals, not a completed-season estimate.

The script loads 1999-2000 as a baseline, then compares player IDs each year
against all previously observed players. It verifies the historical directory's
`FROM_YEAR` to exclude veterans returning after an absence. "Rookie" here means
first NBA regular-season appearance, rather than draft year or award eligibility.
Players already in the league before 2000-01 are excluded entirely.

League-wide totals retrieve everyone's stats in one request per season, so each
new cohort can be followed without requesting every player separately. No
playoffs, preseason or All-Star games are included. One row per player per
season includes all teams; unexpected duplicate IDs cause the build to fail
rather than risk double-counting traded players.

Raw NBA.com responses and UTC retrieval timestamps are cached in `data/raw/`.
Successful requests are reused after interruption; `--refresh` fetches them again.
Requests are sequential with a one-second delay and up to three attempts. A
failed collection retains the cache and leaves the previous database intact.

Outputs:

- `data/processed/leap_study.sqlite`: SQLite database.
- `data/processed/leap_study.csv`: export of the `career_progression` view.

Database tables and view:

- `players`: player ID, name, debut season and debut year.
- `player_seasons`: games played, total points, PPG and career year for each
  season with appearances. PPG is total points divided by games played.
- `career_progression`: joins player names and cohorts with season statistics,
  seasons played, cumulative games, cumulative points and cumulative PPG.
- `sources`: raw filenames and retrieval timestamps.
- `metadata`: collection range, build timestamp and cohort definition.

`career_year` counts calendar seasons since debut; `seasons_played` counts only
seasons with appearances. Missing seasons are not invented as zero-game rows.
Cumulative PPG uses cumulative points / cumulative games, not an average of
season PPG. Active players have incomplete careers; cumulative PPG is explicitly
to date and should not be treated as their eventual career scoring level.

Example SQL:

```sql
SELECT player_name, debut_season, season, career_year,
       games_played, points_per_game, career_ppg_to_date
FROM career_progression
WHERE player_name = 'LeBron James'
ORDER BY season_year;
```

## Analyze player eligibility

```powershell
.\.env\Scripts\python.exe .\projects\leap_study\analysis\analyze_players.py --min-games 25 --min-second-season-ppg 10 --max-early-drop 0.25
```

These flags show the defaults. `--database` selects another SQLite input and
`--output-dir` selects another output folder, useful when comparing thresholds.
The analysis reads the existing database without making NBA.com requests.

Rules are applied separately to every player:

1. Ignore seasons with fewer than 25 games, then number the remaining seasons
   starting at one. Exactly 25 games qualifies; calendar gaps do not count.
2. Require at least 10 PPG in the second qualifying season itself. This is not
   cumulative PPG or a requirement to reach 10 in either of the first two seasons.
3. Exclude players with a PPG decline of 25% or more from qualifying season one
   to two, or two to three. Later declines are ignored. The skipped seasons do
   not enter these comparisons. A preceding PPG of zero has no relative decline.

Players with fewer than two qualifying seasons are marked `insufficient_data`.
Those who pass with only two are included provisionally as
`included_pending_third_season`, with `early_decline_check_complete=False`.
They can be separated from fully checked players when plotting. The script
does not infer whether a player has retired from missing future data.

Outputs are in `data/processed/analysis/`:

- `player_decisions.csv`: one row per player, thresholds evaluated, status,
  exclusion reasons, and early-drop season transitions. Multiple failure reasons
  are retained when applicable.
- `season_audit.csv`: every original season, whether it meets the games threshold,
  qualifying season number, and player decision.
- `eligible_seasons.csv`: all qualifying seasons for included players, ready
  for visualization, including seasons after their third qualifying season.
- `summary.json`: counts, thresholds, source database metadata and run timestamp.

Rerunning replaces these analysis outputs. The source database and its original
career-year numbering are preserved; `qualifying_season` is the analysis timeline.

## Plot scoring growth

```powershell
.\.env\Scripts\python.exe -m pip install -e '.[plots]'
.\.env\Scripts\python.exe .\projects\leap_study\analysis\plot_ppg_growth.py
```

Uses the latest `eligible_seasons.csv` analysis output. Each player's seasonal
PPG is divided by their first **qualifying** season's PPG, consistent with the
games requirement: season one is 1.0 with zero variation; 1.5 represents a 50%
increase and 2.0 a 100% increase. A short actual rookie season is skipped, so the
baseline can be a later calendar season. Zero-baseline players are excluded
and counted because their growth ratio is undefined.

The line is the equally weighted mean of player ratios at each qualifying
season; the band is plus/minus one sample standard deviation (`ddof=1`). It is
not a confidence interval. A single remaining player has undefined SD, so no
band is drawn there. Player counts are shown below: later years contain fewer,
longer-career players, and the selection criteria already favor early scoring
growth. This is a description of the selected players, not all NBA rookies.

By default, provisional two-season players are included. Use
`--exclude-provisional` to restrict to players who completed the early decline
check. `--input` and `--output-dir` allow alternative analysis outputs.

Saves `figures/ppg_growth.png`, `figures/ppg_growth.svg`, `figures/ppg_growth.csv`
(mean, SD, player counts and percent increase), and
`figures/ppg_growth_player_ratios.csv` (individual normalized histories).

### Ranked candidates for the upcoming season

The standard minimum is 25 games. Each analysis run also generates
`data/processed/analysis/leap_candidates.csv`, ranked together by PPG in the
player's most recent qualifying season. It includes eligible players with
exactly two or three qualifying seasons whose latest qualifying season matches
the final source season. `entering_qualifying_season` labels them as entering
season three or four. Two-season candidates are provisional because their
third-season decline check is still pending.

The analysis also refreshes `entering_fourth_year_ppg_rankings.csv` and the
historical `third_year_ppg_rankings.csv` using the same current criteria.
The standard analysis in `data/processed/analysis/` and plots in `figures/`
use the 25-game minimum.

## Sync NBA data to SQLite Cloud

Install the optional SQLite Cloud driver:

```powershell
.\.env\Scripts\python.exe -m pip install -e '.[cloud]'
```

Create a database in SQLite Cloud and use its database-specific connection URL
from the Connect dialog. Follow the provider's
[Python SDK connection instructions](https://docs.sqlitecloud.io/docs/sdk-python-introduction).
Set the URL as an environment variable in the shell running the sync. The
`.env/` folder in this repo is a Python virtual environment, not a secrets file.

```powershell
$env:SQLITE_CLOUD_CONNECTION_STRING = 'sqlitecloud://YOUR_HOST:8860/leap_study.sqlite?apikey=YOUR_API_KEY'
.\.env\Scripts\python.exe .\projects\leap_study\analysis\sync_cloud_database.py
```

The database must already exist and the sync credential must allow table/view
creation and inserts/updates. Keep the actual URL out of tracked files. For a
scheduled job, set the same variable in the job's secret environment.

By default this fetches fresh NBA.com responses, builds and validates the local
database, then uploads the complete raw study dataset. It includes **all**
collected players and seasons; the 25-game, 10-PPG and decline criteria are
not applied to the cloud source data. The future app can change those criteria
without fetching NBA.com again.

```powershell
# Advance the range explicitly to include the new season's available totals:
.\.env\Scripts\python.exe .\projects\leap_study\analysis\sync_cloud_database.py --through-season 2026-27

# Reuse cached NBA responses when populating a new cloud database:
.\.env\Scripts\python.exe .\projects\leap_study\analysis\sync_cloud_database.py --use-cache

# Publish the existing local database, using its recorded season range:
.\.env\Scripts\python.exe .\projects\leap_study\analysis\sync_cloud_database.py --upload-only

# Verify the pipeline without cloud credentials or cloud writes:
.\.env\Scripts\python.exe .\projects\leap_study\analysis\sync_cloud_database.py --dry-run --use-cache
```

Season flags are used by the collection step; `--upload-only` publishes the
existing database as-is. In-progress season totals remain season-to-date and
should be identified separately when the app applies eligibility rules.

Each upload writes immutable rows tagged with a unique snapshot ID and validates
row counts before a single atomic update to `leap_active_snapshot`. A failed
upload leaves the previous snapshot visible; reruns do not duplicate active
player-seasons. SDK credentials are never printed in error messages.

App-facing views select the current complete snapshot:

- `leap_players`
- `leap_player_seasons`
- `leap_career_progression`
- `leap_metadata`
- `leap_sources` (raw paths identify files on the collecting machine, not cloud files)

```sql
SELECT * FROM leap_career_progression ORDER BY player_id, season_year;
```

Read the dataset in one query to stay within a single published snapshot. The
future app should use a read-only credential and cache queries with a refresh
interval or the active snapshot ID. Only the sync script needs write access.

Previous snapshots, including partial failed uploads, are retained in
`leap_snapshot_*` tables. This avoids destructive table replacement; storage
grows with updates, so a retention policy can be added when scheduling the job.
Run only one sync job at a time so an older collection cannot publish after a
newer one. No schedule or Streamlit deployment is configured yet.
