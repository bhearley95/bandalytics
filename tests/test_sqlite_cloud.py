from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest

from cards_tracker.sqlite_cloud import connect_cloud, publish_snapshot, read_snapshot


def snapshot(points=400):
    return {
        "players": [(1, "Example Player", "2000-01", 2000)],
        "player_seasons": [(1, "2000-01", 2000, 1, 40, points)],
        "metadata": [("start_season", "2000-01"), ("through_season", "2000-01"),
                     ("season_type", "Regular Season")],
        "sources": [("totals.json", "2026-10-24T00:00:00+00:00", "data/raw/totals.json")],
    }


class CloudTests(unittest.TestCase):
    def test_repeated_publish_switches_views_without_duplicate_active_rows(self):
        with closing(sqlite3.connect(":memory:", isolation_level=None)) as db:
            first = publish_snapshot(db, snapshot())
            second = publish_snapshot(db, snapshot(800))
            self.assertNotEqual(first, second)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM leap_players").fetchone()[0], 1)
            self.assertEqual(db.execute("SELECT points_per_game, career_ppg_to_date "
                                        "FROM leap_career_progression").fetchone(), (20, 20))
            self.assertEqual(db.execute("SELECT COUNT(*) FROM leap_snapshots").fetchone()[0], 2)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM leap_snapshot_players").fetchone()[0], 2)

    def test_failed_upload_preserves_active_snapshot(self):
        with closing(sqlite3.connect(":memory:", isolation_level=None)) as db:
            first = publish_snapshot(db, snapshot())
            broken = snapshot(-1)
            with self.assertRaises(sqlite3.IntegrityError):
                publish_snapshot(db, broken)
            self.assertEqual(db.execute("SELECT snapshot_id FROM leap_active_snapshot").fetchone()[0], first)
            self.assertEqual(db.execute("SELECT points_per_game FROM leap_player_seasons").fetchone()[0], 10)

    def test_batched_upload(self):
        tables = snapshot()
        tables["player_seasons"] = [(1, f"{2000+i}-{(2001+i)%100:02d}", 2000+i, i+1, 40, 400)
                                     for i in range(4)]
        with closing(sqlite3.connect(":memory:", isolation_level=None)) as db:
            publish_snapshot(db, tables, batch_size=2)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM leap_player_seasons").fetchone()[0], 4)

    def test_local_source_validation(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "source.sqlite"
            with closing(sqlite3.connect(path)) as db, db:
                db.execute("CREATE TABLE players(player_id,player_name,debut_season,debut_year)")
                db.execute("CREATE TABLE player_seasons(player_id,season,season_year,career_year,games_played,total_points)")
                db.execute("CREATE TABLE metadata(key,value)")
                db.execute("CREATE TABLE sources(source,retrieved_at,raw_file)")
                for table, rows in snapshot().items():
                    placeholders = ','.join('?' for _ in rows[0])
                    db.executemany(f"INSERT INTO {table} VALUES ({placeholders})", rows)
            self.assertEqual(len(read_snapshot(path)["players"]), 1)
            with closing(sqlite3.connect(path)) as db, db:
                db.execute("DELETE FROM player_seasons")
            with self.assertRaises(ValueError):
                read_snapshot(path)

    def test_connection_requires_database_in_url(self):
        for url in ("", "https://example.com/db", "sqlitecloud://example.com:8860"):
            with self.assertRaises(ValueError):
                connect_cloud(url)


if __name__ == "__main__":
    unittest.main()
