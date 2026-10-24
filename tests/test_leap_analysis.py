import importlib.util
from pathlib import Path
import unittest

import pandas as pd

path = Path(__file__).resolve().parents[1] / "projects/leap_study/analysis/analyze_players.py"
spec = importlib.util.spec_from_file_location("leap_analysis", path)
analysis = importlib.util.module_from_spec(spec)
spec.loader.exec_module(analysis)


def player_data(*seasons):
    return pd.DataFrame([
        (1, "Example", "2021-22", f"{2021 + i}-{(2022 + i) % 100:02d}",
         2021 + i, i + 1, games, round(games * ppg))
        for i, (games, ppg) in enumerate(seasons)
    ], columns=["player_id", "player_name", "debut_season", "season", "season_year",
                "career_year", "games_played", "total_points"])


class LeapAnalysisTests(unittest.TestCase):
    def test_skips_short_seasons_before_numbering_and_comparing(self):
        decisions, audit = analysis.analyze_players(player_data(
            (40, 12), (24, 1), (80, 16), (25, 18)))
        self.assertTrue(decisions.iloc[0].included)
        self.assertEqual(decisions.iloc[0].second_qualifying_season, "2023-24")
        self.assertEqual(audit.qualifying_season.dropna().tolist(), [1, 2, 3])
        self.assertEqual(audit.loc[1, "season_exclusion_reason"], "below_minimum_games")

    def test_second_season_threshold_is_inclusive_and_not_cumulative(self):
        for ppg, included in [(10, True), (9.5, False)]:
            decisions, _ = analysis.analyze_players(player_data((40, 8), (40, ppg), (40, 12)))
            self.assertEqual(bool(decisions.iloc[0].included), included)

    def test_exact_drop_boundary_at_either_early_transition(self):
        for sequence in [(20, 15, 16), (12, 20, 15)]:
            decisions, _ = analysis.analyze_players(player_data(*[(40, ppg) for ppg in sequence]))
            self.assertFalse(decisions.iloc[0].included)
            self.assertTrue(decisions.iloc[0].early_decline)

    def test_drop_after_third_season_does_not_exclude(self):
        decisions, _ = analysis.analyze_players(player_data((40, 10), (40, 15), (40, 20), (40, 2)))
        self.assertTrue(decisions.iloc[0].included)

    def test_short_careers_and_provisional_inclusion(self):
        for seasons, status in [([], None), ([(24, 20)], "insufficient_data"),
                                 ([(40, 12)], "insufficient_data"),
                                 ([(40, 10), (40, 12)], "included_pending_third_season")]:
            decisions, audit = analysis.analyze_players(player_data(*seasons))
            if status is None:
                self.assertTrue(decisions.empty)
                self.assertTrue(audit.empty)
            else:
                self.assertEqual(decisions.iloc[0].status, status)

    def test_zero_ppg_and_custom_thresholds(self):
        decisions, _ = analysis.analyze_players(player_data((20, 0), (20, 0), (20, 0)),
                                                min_games=20, min_second_season_ppg=0)
        self.assertTrue(decisions.iloc[0].included)
        decisions, _ = analysis.analyze_players(player_data((40, 20), (40, 16), (40, 18)),
                                                max_early_drop=0.20)
        self.assertFalse(decisions.iloc[0].included)

    def test_validation(self):
        data = player_data((40, 10))
        for kwargs in [{"min_games": 0}, {"max_early_drop": 0}, {"max_early_drop": 1.1},
                       {"min_second_season_ppg": float("nan")}]:
            with self.assertRaises(ValueError):
                analysis.analyze_players(data, **kwargs)
        with self.assertRaises(ValueError):
            analysis.analyze_players(pd.concat([data, data]))

    def test_shortlist_labels_two_and_three_season_players(self):
        two = player_data((25, 10), (25, 12))
        two["season_year"] += 1
        three = player_data((25, 10), (25, 12), (25, 15))
        three["player_id"] = 2
        four = player_data((25, 10), (25, 12), (25, 15), (25, 18))
        four["player_id"] = 3
        decisions, audit = analysis.analyze_players(pd.concat([two, three, four]))
        eligible = audit.loc[audit.included & audit.season_qualifies]
        ranked = analysis.rank_candidates(decisions, eligible, 2023)
        self.assertEqual(ranked.player_id.tolist(), [2, 1])
        self.assertEqual(ranked.entering_qualifying_season.tolist(), [4, 3])
        self.assertTrue(analysis.rank_candidates(decisions, eligible, 2030).empty)


if __name__ == "__main__":
    unittest.main()
