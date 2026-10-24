import importlib.util
from pathlib import Path
import unittest

import pandas as pd

path = Path(__file__).resolve().parents[1] / "projects/leap_study/analysis/plot_ppg_growth.py"
spec = importlib.util.spec_from_file_location("ppg_growth", path)
growth = importlib.util.module_from_spec(spec)
spec.loader.exec_module(growth)


class GrowthTests(unittest.TestCase):
    def test_player_normalization_mean_sd_and_missing_careers(self):
        frame = pd.DataFrame([(1, 1, 10), (1, 2, 20), (1, 3, 15),
                              (2, 1, 20), (2, 2, 20)],
                             columns=["player_id", "qualifying_season", "points_per_game"])
        _, summary, excluded = growth.summarize_growth(frame)
        self.assertEqual(excluded, 0)
        self.assertEqual(summary.mean_ratio.tolist(), [1, 1.5, 1.5])
        self.assertEqual(summary.player_count.tolist(), [2, 2, 1])
        self.assertEqual(summary.std_ratio.iloc[0], 0)
        self.assertAlmostEqual(summary.std_ratio.iloc[1], 2 ** -0.5)
        self.assertTrue(pd.isna(summary.std_ratio.iloc[2]))
        self.assertEqual(summary.mean_percent_increase.iloc[1], 50)

    def test_zero_baseline_is_reported_and_excluded(self):
        frame = pd.DataFrame([(1, 1, 0), (1, 2, 10), (2, 1, 5)],
                             columns=["player_id", "qualifying_season", "points_per_game"])
        data, _, excluded = growth.summarize_growth(frame)
        self.assertEqual(excluded, 1)
        self.assertEqual(data.player_id.tolist(), [2])


if __name__ == "__main__":
    unittest.main()
