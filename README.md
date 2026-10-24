# Cards tracker

Python tools for sports card sales tracking and NBA statistics. The first component
is `NBAClient`, wrapping [`nba_api`](https://github.com/swar/nba_api).

## Setup

Use Python 3.11 or newer. From the repository root (PowerShell):

```powershell
python -m venv .env
.\.env\Scripts\python.exe -m pip install -r requirements.txt
```

## Player statistics

```python
from cards_tracker import NBAClient

nba = NBAClient(timeout=30)
players = nba.search_players("LeBron")  # local directory; includes retired players

games = nba.get_player_game_logs(
    "LeBron James", "2024-10-01", "2025-04-30"
)
print(games[["GAME_DATE", "MATCHUP", "PTS", "REB", "AST"]])
games.to_csv("lebron_games.csv", index=False)

summary = nba.get_points_summary(2544, "2024-10-01", "2025-04-30")
print(summary.total_points, summary.points_per_game)
```

- Accepts a positive NBA player ID or an exact, case-insensitive full name.
  For ambiguous names, search first and pass the desired ID.
- Dates are inclusive `YYYY-MM-DD` strings or `datetime.date` objects.
- Returns a pandas DataFrame with NBA game-log columns plus `SEASON`.
  `GAME_DATE` is converted to pandas timestamps; rows are sorted oldest first.
- Defaults to `Regular Season`. Pass `season_type="Playoffs"`, `"Pre Season"`,
  or `"All-Star"` to query those games separately.
- Queries potentially overlapping seasons, including the previous calendar
  year's season to support delayed seasons such as 2019-20. This can make an
  extra request for a season with no matching games.
- No matching games produces an empty DataFrame, zero total points, and
  `None` for points per game. A failed season request raises `NBAQueryError`
  with its original cause; partial results are never returned as complete.
- Player lookup uses the installed package's local player directory. Update
  `nba_api` when you need newer player listings.

NBA.com requests need internet access and can time out or be rate limited.
Timeout and proxy are configurable on the client. No API key is needed.
There are no automatic retries or persistent caches.

## Streamlit app

Install and run from the repository root:

```powershell
.\.env\Scripts\python.exe -m pip install -r requirements.txt
.\.env\Scripts\python.exe -m streamlit run app.py
```

The sidebar project dropdown currently offers Leap Study. Its controls adjust
the second-season PPG minimum (10), early PPG drop-off threshold (25%), and
games minimum (25). The plot, player counts and ranked candidates
update together. Rankings label players entering their third or fourth
qualifying season and can be downloaded with the current criteria.

Cloud data is the default. Set `SQLITE_CLOUD_CONNECTION_STRING` in the process
environment or copy `.streamlit/secrets.toml.example` to the ignored
`.streamlit/secrets.toml` and enter your database-specific connection URL there.
The app only reads the database; use a read-only credential for deployment.
For development without credentials, select **Local database** in the sidebar.
On a fresh clone, first create it with
`.\.env\Scripts\python.exe projects/leap_study/analysis/build_database.py`.
Cloud failures are shown as errors rather than silently switching datasets.

Data is cached for five minutes; **Refresh data** reloads it immediately. New
cloud snapshots become available without redeploying the app. The app does not
call NBA.com or modify study outputs when a viewer changes criteria.

For Streamlit hosting, use `app.py` as the entry point, the repository-root
`requirements.txt` for dependencies, and the same connection key in the host's
secrets settings. Local launch does not publish a hosted app.

Add future project pages as `projects/<name>/app.py` with a `render()` function,
then register them in the `PROJECTS` mapping in root `app.py`. Project-specific
widgets should have keys prefixed with the project name.

## Research and articles

Research work lives in [`projects/`](projects/README.md), with one folder per
topic. Each project contains analysis scripts, source and processed data,
figures, and Markdown article drafts. Shared classes remain in
`src/cards_tracker/` so every project can reuse them.

The first project is [`leap_study`](projects/leap_study/README.md).

Source code, article drafts and directory placeholders are tracked in Git.
API caches, SQLite databases, CSV exports and generated figures are ignored
and remain local. Recreate them with the project scripts; the deployed app
reads SQLite Cloud and does not need these files uploaded to GitHub.

## Tests

```powershell
.\.env\Scripts\python.exe -m unittest discover -s tests -v
```

Tests mock NBA.com responses so they run without network access.
