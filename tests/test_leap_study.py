import importlib.util
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest

import pandas as pd

path = Path(__file__).resolve().parents[1] / "projects/leap_study/analysis/build_database.py"
spec = importlib.util.spec_from_file_location("leap_builder", path)
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


def season(*rows):
    return pd.DataFrame(rows, columns=["PLAYER_ID", "PLAYER_NAME", "GP", "PTS"])


class LeapStudyTests(unittest.TestCase):
    def test_rookie_cohorts_returning_veteran_gaps_and_weighted_ppg(self):
        seasons = {
            1999: season((1, "Veteran", 50, 500)),
            2000: season((1, "Veteran", 40, 400), (2, "Rookie", 10, 100),
                         (3, "Returning veteran", 5, 50)),
            2001: season((4, "Next rookie", 20, 300)),
            2002: season((2, "Rookie", 30, 600), (4, "Next rookie", 40, 800)),
        }
        directory = pd.DataFrame([(1, 1990), (2, 2000), (3, 1995), (4, 2001)],
                                 columns=["PERSON_ID", "FROM_YEAR"])
        players, records = builder.assemble(seasons, directory, 2000, 2002)
        self.assertEqual({p[0] for p in players}, {2, 4})
        with tempfile.TemporaryDirectory() as folder:
            db_path = Path(folder) / "test.sqlite"
            builder.write_database(db_path, players, records, {"test": "yes"}, [])
            with closing(sqlite3.connect(db_path)) as db:
                row = db.execute("SELECT career_year,seasons_played,points_per_game,"
                                 "career_ppg_to_date FROM career_progression "
                                 "WHERE player_id=2 AND season_year=2002").fetchone()
                self.assertEqual(row, (3, 2, 20.0, 17.5))
                self.assertEqual(db.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            # Rebuilding is idempotent rather than appending duplicate records.
            builder.write_database(db_path, players, records, {}, [])
            with closing(sqlite3.connect(db_path)) as db:
                self.assertEqual(db.execute("SELECT COUNT(*) FROM player_seasons").fetchone()[0], 4)

    def test_rejects_duplicate_or_invalid_totals(self):
        for frame in [season((1, "A", 10, 100), (1, "A", 5, 40)),
                      season((1, "A", 10, -1)), season((1, "A", None, 50))]:
            with self.assertRaises(ValueError):
                builder.normalize_totals(frame)

    def test_cache_avoids_another_request(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "raw.json"
            first = builder.cached_query(path, lambda: {"resultSets": []}, delay=0)
            second = builder.cached_query(path, lambda: self.fail("Cache should be reused"))
            self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
