import unittest
from unittest.mock import patch

import pandas as pd

from cards_tracker import NBAClient, NBAQueryError


def logs(*rows):
    return pd.DataFrame(rows, columns=["Game_ID", "GAME_DATE", "PTS"])


class NBAClientTests(unittest.TestCase):
    def setUp(self):
        self.client = NBAClient(timeout=5)

    @patch("cards_tracker.nba.PlayerGameLog")
    def test_cross_season_range_filters_sorts_and_deduplicates(self, endpoint):
        endpoint.return_value.get_data_frames.side_effect = [
            [logs(("1", "JUN 01, 2024", 25), ("0", "MAY 31, 2024", 10))],
            [logs(("2", "OCT 22, 2024", 30), ("1", "JUN 01, 2024", 25),
                  ("3", "OCT 23, 2024", 40))],
        ]
        result = self.client.get_player_game_logs(2544, "2024-06-01", "2024-10-22")
        self.assertEqual(result["Game_ID"].tolist(), ["1", "2"])
        self.assertEqual([c.kwargs["season"] for c in endpoint.call_args_list],
                         ["2023-24", "2024-25"])
        self.assertEqual(endpoint.call_args.kwargs["date_from_nullable"], "06/01/2024")
        self.assertEqual(endpoint.call_args.kwargs["date_to_nullable"], "10/22/2024")
        self.assertEqual(endpoint.call_args.kwargs["timeout"], 5)

    @patch("cards_tracker.nba.PlayerGameLog")
    def test_delayed_2020_playoffs_and_summary(self, endpoint):
        endpoint.return_value.get_data_frames.side_effect = [
            [logs(("1", "OCT 11, 2020", 28))], [logs()],
        ]
        summary = self.client.get_points_summary(
            "LeBron James", "2020-10-11", "2020-10-11", season_type="Playoffs")
        self.assertEqual((summary.games_played, summary.total_points, summary.points_per_game),
                         (1, 28, 28.0))
        self.assertEqual(endpoint.call_args_list[0].kwargs["season"], "2019-20")
        self.assertEqual(endpoint.call_args.kwargs["season_type_all_star"], "Playoffs")

    @patch("cards_tracker.nba.PlayerGameLog")
    def test_empty_summary(self, endpoint):
        endpoint.return_value.get_data_frames.return_value = [logs()]
        summary = self.client.get_points_summary(2544, "2024-08-01", "2024-08-31")
        self.assertEqual(summary.total_points, 0)
        self.assertEqual(summary.games_played, 0)
        self.assertIsNone(summary.points_per_game)

    @patch("cards_tracker.nba.PlayerGameLog")
    def test_failure_does_not_return_partial_data(self, endpoint):
        endpoint.return_value.get_data_frames.side_effect = [
            [logs(("1", "JUN 01, 2024", 25))], TimeoutError("unavailable"),
        ]
        with self.assertRaises(NBAQueryError) as caught:
            self.client.get_player_game_logs(2544, "2024-06-01", "2024-10-22")
        self.assertIsInstance(caught.exception.__cause__, TimeoutError)

    @patch("cards_tracker.nba.PlayerGameLog")
    def test_validation_prevents_requests(self, endpoint):
        for player, start, end in [
            (2544, "2024-12-01", "2024-01-01"),
            (2544, "invalid", "2024-01-01"),
            (True, "2024-01-01", "2024-01-02"),
            ("Unknown Player", "2024-01-01", "2024-01-02"),
        ]:
            with self.subTest(player=player, start=start):
                with self.assertRaises(ValueError):
                    self.client.get_player_game_logs(player, start, end)
        endpoint.assert_not_called()

    def test_local_player_lookup(self):
        self.assertEqual(self.client.resolve_player_id("lebron james"), 2544)
        self.assertTrue(self.client.search_players("LeBron"))

    @patch("cards_tracker.nba.PlayerGameLog")
    def test_missing_points_is_not_treated_as_zero(self, endpoint):
        endpoint.return_value.get_data_frames.return_value = [
            logs(("1", "JAN 01, 2024", None))]
        with self.assertRaises(NBAQueryError):
            self.client.get_points_summary(2544, "2024-01-01", "2024-01-01")


if __name__ == "__main__":
    unittest.main()
