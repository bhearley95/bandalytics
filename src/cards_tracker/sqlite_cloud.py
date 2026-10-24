"""Publish complete NBA datasets without exposing partially uploaded snapshots."""

from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from urllib.parse import urlsplit
from uuid import uuid4


def connect_cloud(connection_string):
    """Connect using a secret supplied by the caller; never log the URL."""
    parsed = urlsplit(connection_string)
    if parsed.scheme != "sqlitecloud" or not parsed.hostname or parsed.path in ("", "/"):
        raise ValueError("SQLite Cloud URL must include a hostname and database name")
    import sqlitecloud
    return sqlitecloud.connect(connection_string)


TABLES = {
    "players": ("player_id", "player_name", "debut_season", "debut_year"),
    "player_seasons": ("player_id", "season", "season_year", "career_year",
                       "games_played", "total_points"),
    "metadata": ("key", "value"),
    "sources": ("source", "retrieved_at", "raw_file"),
}

SCHEMA = [
    """CREATE TABLE IF NOT EXISTS leap_snapshots (
        snapshot_id TEXT PRIMARY KEY, created_at TEXT NOT NULL,
        player_count INTEGER NOT NULL, season_count INTEGER NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS leap_active_snapshot (
        singleton INTEGER PRIMARY KEY CHECK(singleton=1), snapshot_id TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS leap_snapshot_players (
        snapshot_id TEXT NOT NULL, player_id INTEGER NOT NULL, player_name TEXT NOT NULL,
        debut_season TEXT NOT NULL, debut_year INTEGER NOT NULL,
        PRIMARY KEY(snapshot_id,player_id))""",
    """CREATE TABLE IF NOT EXISTS leap_snapshot_player_seasons (
        snapshot_id TEXT NOT NULL, player_id INTEGER NOT NULL, season TEXT NOT NULL,
        season_year INTEGER NOT NULL, career_year INTEGER NOT NULL,
        games_played INTEGER NOT NULL CHECK(games_played>0),
        total_points INTEGER NOT NULL CHECK(total_points>=0),
        PRIMARY KEY(snapshot_id,player_id,season))""",
    """CREATE TABLE IF NOT EXISTS leap_snapshot_metadata (
        snapshot_id TEXT NOT NULL, key TEXT NOT NULL, value TEXT NOT NULL,
        PRIMARY KEY(snapshot_id,key))""",
    """CREATE TABLE IF NOT EXISTS leap_snapshot_sources (
        snapshot_id TEXT NOT NULL, source TEXT NOT NULL, retrieved_at TEXT NOT NULL,
        raw_file TEXT NOT NULL, PRIMARY KEY(snapshot_id,source))""",
]
for _table, _columns in TABLES.items():
    _selection = ", ".join(f"s.{column}" for column in _columns)
    if _table == "player_seasons":
        _selection += ", 1.0*s.total_points/s.games_played AS points_per_game"
    SCHEMA.append(f"CREATE VIEW IF NOT EXISTS leap_{_table} AS "
                  f"SELECT {_selection} FROM leap_snapshot_{_table} s "
                  "JOIN leap_active_snapshot a ON a.snapshot_id=s.snapshot_id WHERE a.singleton=1")
SCHEMA.append("""CREATE VIEW IF NOT EXISTS leap_career_progression AS
    SELECT p.player_name, p.debut_season, s.*,
        ROW_NUMBER() OVER w AS seasons_played,
        SUM(games_played) OVER w AS career_games_to_date,
        SUM(total_points) OVER w AS career_points_to_date,
        1.0*SUM(total_points) OVER w / SUM(games_played) OVER w AS career_ppg_to_date
    FROM leap_player_seasons s JOIN leap_players p USING(player_id)
    WINDOW w AS (PARTITION BY s.player_id ORDER BY season_year
                ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)""")


def read_snapshot(path):
    """Validate and materialize the local collection before touching the cloud."""
    path = Path(path).resolve()
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
        if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("Local database failed integrity check")
        if db.execute("PRAGMA foreign_key_check").fetchone():
            raise ValueError("Local database contains orphaned records")
        tables = {table: db.execute(f"SELECT {','.join(columns)} FROM {table}").fetchall()
                  for table, columns in TABLES.items()}
    if not tables["players"] or not tables["player_seasons"]:
        raise ValueError("Refusing to publish an empty dataset")
    metadata = dict(tables["metadata"])
    if not {"start_season", "through_season", "season_type"}.issubset(metadata):
        raise ValueError("Local database is missing collection metadata")
    if metadata["season_type"] != "Regular Season":
        raise ValueError("Only regular-season snapshots are supported")
    return tables


def publish_snapshot(connection, tables, *, batch_size=100):
    """Upload immutable rows, then publish with a single atomic pointer change.

    Old snapshots remain available. A failed upload never changes the active
    snapshot; abandoned rows can be cleaned up later by snapshot_id.
    """
    if not 1 <= batch_size <= 100:
        raise ValueError("batch_size must be between 1 and 100")
    snapshot_id = uuid4().hex
    for statement in SCHEMA:
        connection.execute(statement)
    for table, columns in TABLES.items():
        rows = tables[table]
        for offset in range(0, len(rows), batch_size):
            batch = [(snapshot_id, *row) for row in rows[offset:offset + batch_size]]
            placeholder = "(" + ",".join("?" for _ in range(len(columns) + 1)) + ")"
            connection.execute(
                f"INSERT INTO leap_snapshot_{table} (snapshot_id,{','.join(columns)}) VALUES "
                + ",".join(placeholder for _ in batch),
                tuple(value for row in batch for value in row),
            )
        actual = connection.execute(
            f"SELECT COUNT(*) FROM leap_snapshot_{table} WHERE snapshot_id=?", (snapshot_id,)
        ).fetchone()[0]
        if actual != len(rows):
            raise ValueError(f"Uploaded {table} row count does not match source")
    connection.execute("INSERT INTO leap_snapshots VALUES (?, ?, ?, ?)",
                       (snapshot_id, datetime.now(timezone.utc).isoformat(),
                        len(tables["players"]), len(tables["player_seasons"])))
    connection.execute(
        "INSERT INTO leap_active_snapshot(singleton,snapshot_id) VALUES (1,?) "
        "ON CONFLICT(singleton) DO UPDATE SET snapshot_id=excluded.snapshot_id", (snapshot_id,))
    return snapshot_id
