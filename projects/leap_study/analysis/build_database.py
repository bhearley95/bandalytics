"""Collect rookie cohorts and their yearly scoring into a resumable SQLite DB."""

import argparse
from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import time

import pandas as pd

from cards_tracker import NBAClient, NBAQueryError

PROJECT_DIR = Path(__file__).resolve().parents[1]


def season_name(year):
    return f"{year}-{(year + 1) % 100:02d}"


def season_year(value):
    try:
        year = int(value[:4])
        if value != season_name(year) or not 1947 <= year <= 2100:
            raise ValueError()
        return year
    except (ValueError, TypeError):
        raise argparse.ArgumentTypeError("Use an NBA season such as 2000-01")


def dataset(payload, name):
    result = next(r for r in payload["resultSets"] if r["name"] == name)
    return pd.DataFrame(result["rowSet"], columns=result["headers"])


def cached_query(path, fetch, *, refresh=False, delay=1.0):
    if path.exists() and not refresh:
        return json.loads(path.read_text(encoding="utf-8"))
    for attempt in range(3):
        try:
            payload = fetch()
            break
        except NBAQueryError:
            if attempt == 2:
                raise
            time.sleep(2 ** (attempt + 1))
    wrapper = {"retrieved_at": datetime.now(timezone.utc).isoformat(), "response": payload}
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(wrapper), encoding="utf-8")
    temporary.replace(path)
    time.sleep(delay)
    return wrapper


def normalize_totals(frame):
    """Reject duplicates rather than silently double-counting traded players."""
    frame = frame[["PLAYER_ID", "PLAYER_NAME", "GP", "PTS"]].copy()
    for column in ("PLAYER_ID", "GP", "PTS"):
        frame[column] = pd.to_numeric(frame[column], errors="raise")
        if (frame[column].isna().any() or (frame[column] < 0).any()
                or (frame[column] % 1 != 0).any()):
            raise ValueError(f"Invalid {column} values")
        frame[column] = frame[column].astype("int64")
    if frame["PLAYER_ID"].duplicated().any():
        raise ValueError("Expected one league-wide total per player; duplicate player IDs returned")
    return frame.loc[frame["GP"] > 0]


def assemble(seasons, directory, start, end):
    """Compare against baseline and verify debut year to exclude returning vets."""
    debut_years = {int(row.PERSON_ID): int(row.FROM_YEAR)
                   for row in directory.itertuples()}
    seen = set(seasons[start - 1]["PLAYER_ID"])
    cohort = {}
    names = {}
    records = []
    for year in range(start, end + 1):
        frame = seasons[year]
        current = set(frame["PLAYER_ID"])
        for row in frame.itertuples():
            pid = int(row.PLAYER_ID)
            if pid not in debut_years:
                raise ValueError(f"Player {pid} missing from historical directory")
            if pid not in seen and debut_years[pid] == year:
                cohort[pid] = year
                names[pid] = row.PLAYER_NAME
            if pid in cohort:
                records.append((pid, season_name(year), year, year - cohort[pid] + 1,
                                int(row.GP), int(row.PTS)))
        seen.update(current)
    return [(pid, names[pid], season_name(year), year) for pid, year in cohort.items()], records


SCHEMA = """
CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE players (
    player_id INTEGER PRIMARY KEY, player_name TEXT NOT NULL,
    debut_season TEXT NOT NULL, debut_year INTEGER NOT NULL
);
CREATE TABLE player_seasons (
    player_id INTEGER NOT NULL REFERENCES players(player_id),
    season TEXT NOT NULL, season_year INTEGER NOT NULL, career_year INTEGER NOT NULL,
    games_played INTEGER NOT NULL CHECK(games_played > 0),
    total_points INTEGER NOT NULL CHECK(total_points >= 0),
    points_per_game REAL GENERATED ALWAYS AS (1.0 * total_points / games_played) VIRTUAL,
    PRIMARY KEY (player_id, season)
);
CREATE TABLE sources (
    source TEXT PRIMARY KEY, retrieved_at TEXT NOT NULL, raw_file TEXT NOT NULL
);
CREATE VIEW career_progression AS
SELECT p.player_name, p.debut_season, s.*,
    ROW_NUMBER() OVER w AS seasons_played,
    SUM(games_played) OVER w AS career_games_to_date,
    SUM(total_points) OVER w AS career_points_to_date,
    1.0 * SUM(total_points) OVER w / SUM(games_played) OVER w AS career_ppg_to_date
FROM player_seasons s JOIN players p USING (player_id)
WINDOW w AS (PARTITION BY s.player_id ORDER BY season_year
             ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW);
"""


def write_database(path, players, records, metadata, sources):
    # Build separately: a failed collection never replaces an existing complete DB.
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".building.sqlite")
    if temporary.exists():
        temporary.unlink()
    with closing(sqlite3.connect(temporary)) as db, db:
        db.execute("PRAGMA foreign_keys = ON")
        db.executescript(SCHEMA)
        db.executemany("INSERT INTO metadata VALUES (?, ?)", metadata.items())
        db.executemany("INSERT INTO players VALUES (?, ?, ?, ?)", players)
        db.executemany("INSERT INTO player_seasons "
                       "(player_id,season,season_year,career_year,games_played,total_points) "
                       "VALUES (?, ?, ?, ?, ?, ?)", records)
        db.executemany("INSERT INTO sources VALUES (?, ?, ?)", sources)
    temporary.replace(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-season", type=season_year, default=2000)
    parser.add_argument("--through-season", type=season_year, default=2025,
                        help="Last season to collect (default: 2025-26)")
    parser.add_argument("--refresh", action="store_true", help="Re-fetch cached sources")
    parser.add_argument("--timeout", type=float, default=30)
    parser.add_argument("--delay", type=float, default=1.0)
    args = parser.parse_args()
    if args.start_season > args.through_season or not 0 <= args.delay <= 60:
        parser.error("Start must precede end; delay must be between 0 and 60 seconds")
    client = NBAClient(timeout=args.timeout)
    raw = PROJECT_DIR / "data" / "raw"
    sources = []

    def collect(filename, fetch):
        path = raw / filename
        result = cached_query(path, fetch, refresh=args.refresh, delay=args.delay)
        sources.append((filename, result["retrieved_at"], str(path.relative_to(PROJECT_DIR))))
        return result["response"]

    end = season_name(args.through_season)
    print("Loading historical player directory...", flush=True)
    directory = dataset(collect(f"directory_{end}.json", lambda: client.get_player_directory(end)),
                        "CommonAllPlayers")
    seasons = {}
    for year in range(args.start_season - 1, args.through_season + 1):
        season = season_name(year)
        print(f"Loading {season} regular-season totals (cached if available)...", flush=True)
        payload = collect(f"totals_{season}.json", lambda: client.get_league_season_totals(season))
        seasons[year] = normalize_totals(dataset(payload, "LeagueDashPlayerStats"))
        if seasons[year].empty:
            raise ValueError(f"No games returned for {season}; refusing an incomplete build")
    players, records = assemble(seasons, directory, args.start_season, args.through_season)
    output = PROJECT_DIR / "data" / "processed" / "leap_study.sqlite"
    write_database(output, players, records, {
        "start_season": season_name(args.start_season), "through_season": end,
        "season_type": "Regular Season", "source": "NBA.com via nba_api",
        "built_at": datetime.now(timezone.utc).isoformat(),
        "cohort_definition": "First NBA regular-season appearance, not draft year or award eligibility",
    }, sources)
    with closing(sqlite3.connect(output)) as db:
        table = pd.read_sql_query("SELECT * FROM career_progression ORDER BY debut_season, player_id, season_year", db)
    table.to_csv(output.with_suffix(".csv"), index=False)
    print(f"Saved {len(players):,} players and {len(records):,} player-seasons to {output}")
    print(f"CSV: {output.with_suffix('.csv')}")


if __name__ == "__main__":
    try:
        main()
    except (NBAQueryError, ValueError, KeyError, StopIteration) as exc:
        raise SystemExit(f"Build failed: {exc}. Cached successful queries are retained; rerun to resume.")
