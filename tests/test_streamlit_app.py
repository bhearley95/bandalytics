import os
from pathlib import Path
import unittest
from unittest.mock import patch
from uuid import uuid4

import pandas as pd
from streamlit.testing.v1 import AppTest

APP = Path(__file__).resolve().parents[1] / "app.py"


def fixture():
    rows = [(1, "Three Seasons", "2023-24", "2023-24", 2023, 1, 40, 400),
            (1, "Three Seasons", "2023-24", "2024-25", 2024, 2, 40, 480),
            (1, "Three Seasons", "2023-24", "2025-26", 2025, 3, 40, 520),
            (2, "Two Seasons", "2024-25", "2024-25", 2024, 1, 40, 400),
            (2, "Two Seasons", "2024-25", "2025-26", 2025, 2, 40, 560)]
    return (pd.DataFrame(rows, columns=["player_id", "player_name", "debut_season", "season",
                                       "season_year", "career_year", "games_played", "total_points"]),
            {"start_season": "2000-01", "through_season": "2025-26"}, "test-snapshot")


class StreamlitTests(unittest.TestCase):
    def test_controls_update_plot_and_rankings(self):
        with patch.dict(os.environ, {"SQLITE_CLOUD_CONNECTION_STRING": uuid4().hex}), \
                patch("projects.leap_study.app.read_cloud_study", return_value=fixture()):
            app = AppTest.from_file(str(APP), default_timeout=30).run()
            self.assertFalse(app.exception)
            self.assertEqual(app.selectbox(key="project").value, "Leap Study")
            self.assertEqual(len(app.selectbox), 1)
            self.assertIn("Bandalytics", [title.value for title in app.title])
            self.assertIn("by Bandwagon Breaks", [caption.value for caption in app.caption])
            self.assertEqual([m.value for m in app.metric], ["2", "1", "1", "2"])
            ranking = app.dataframe[0].value
            self.assertEqual(ranking["Entering qualifying season"].tolist(), ["3rd", "4th"])
            app.number_input(key="leap_min_ppg").set_value(13.0).run()
            self.assertFalse(app.exception)
            self.assertEqual([m.value for m in app.metric], ["2", "0", "1", "1"])
            app.number_input(key="leap_min_games").set_value(41).run()
            self.assertFalse(app.exception)
            self.assertTrue(any("No players meet" in message.value for message in app.info))

    def test_cloud_errors_do_not_expose_credentials(self):
        secret = uuid4().hex
        with patch.dict(os.environ, {"SQLITE_CLOUD_CONNECTION_STRING": secret}), \
                patch("projects.leap_study.app.read_cloud_study", side_effect=RuntimeError(secret)):
            app = AppTest.from_file(str(APP), default_timeout=30).run()
            self.assertFalse(app.exception)
            self.assertTrue(app.error)
            self.assertNotIn(secret, app.error[0].value)


if __name__ == "__main__":
    unittest.main()
