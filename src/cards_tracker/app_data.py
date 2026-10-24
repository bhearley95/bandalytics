"""Read a consistent published study snapshot for interactive analysis."""

from contextlib import closing
from pathlib import Path
import sqlite3

import pandas as pd

from .sqlite_cloud import connect_cloud


def read_cloud_study(connection_string):
    # Snapshot rows are immutable, so fixing the ID makes all queries consistent
    # even when a sync publishes a new snapshot between these requests.
    with closing(connect_cloud(connection_string)) as db:
        active = db.execute("SELECT snapshot_id FROM leap_active_snapshot WHERE singleton=1").fetchone()
        if active is None:
            raise ValueError("No published study snapshot")
        snapshot_id = active[0]
        metadata = dict(db.execute(
            "SELECT key,value FROM leap_snapshot_metadata WHERE snapshot_id=?", (snapshot_id,)).fetchall())
        cursor = db.execute("""
            SELECT p.player_id,p.player_name,p.debut_season,s.season,s.season_year,
                   s.career_year,s.games_played,s.total_points
            FROM leap_snapshot_player_seasons s
            JOIN leap_snapshot_players p ON p.snapshot_id=s.snapshot_id AND p.player_id=s.player_id
            WHERE s.snapshot_id=? ORDER BY p.player_id,s.season_year
        """, (snapshot_id,))
        columns = [description[0] for description in cursor.description]
        data = pd.DataFrame(cursor.fetchall(), columns=columns)
    return data, metadata, snapshot_id


def read_local_study(path):
    path = Path(path).resolve()
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
        data = pd.read_sql_query("""
            SELECT p.player_id,p.player_name,p.debut_season,s.season,s.season_year,
                   s.career_year,s.games_played,s.total_points
            FROM players p JOIN player_seasons s USING(player_id)
            ORDER BY p.player_id,s.season_year
        """, db)
        metadata = dict(db.execute("SELECT key,value FROM metadata"))
    return data, metadata, "local"
