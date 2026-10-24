"""List each season's top entering-fourth candidate without using future seasons."""

import argparse
from pathlib import Path
import sys

import pandas as pd

from cards_tracker.app_data import read_local_study

# Support direct invocation from the repository root, like the other scripts.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from analyze_players import analyze_players, rank_candidates

PROJECT_DIR = Path(__file__).resolve().parents[1]


def historical_candidates(data, start_year, through_year, *, min_games=25,
                          min_second_season_ppg=10, max_early_drop=0.25):
    rows = []
    for target_year in range(start_year + 4, through_year + 2):
        cutoff = target_year - 1
        history = data.loc[data.season_year <= cutoff]
        decisions, audit = analyze_players(
            history, min_games=min_games, min_second_season_ppg=min_second_season_ppg,
            max_early_drop=max_early_drop)
        eligible = audit.loc[audit.included & audit.season_qualifies]
        candidates = rank_candidates(decisions, eligible, cutoff)
        fourth = candidates.loc[candidates.entering_qualifying_season == 4]
        target = f"{target_year}-{(target_year + 1) % 100:02d}"
        if fourth.empty:
            rows.append({"target_season": target, "player_name": None, "candidate_count": 0})
            continue
        # Retain tied leaders rather than silently choosing one by name.
        leaders = fourth.loc[fourth.points_per_game == fourth.points_per_game.max()]
        for leader in leaders.to_dict("records"):
            rows.append({"target_season": target, "player_id": leader["player_id"],
                         "player_name": leader["player_name"], "third_qualifying_season": leader["season"],
                         "third_season_ppg": leader["points_per_game"],
                         "third_season_games": leader["games_played"], "candidate_count": len(fourth)})
    return pd.DataFrame(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=PROJECT_DIR / "data/processed/leap_study.sqlite")
    parser.add_argument("--min-games", type=int, default=25)
    parser.add_argument("--min-second-season-ppg", type=float, default=10)
    parser.add_argument("--max-early-drop", type=float, default=0.25)
    args = parser.parse_args()
    data, metadata, _ = read_local_study(args.database)
    result = historical_candidates(data, int(metadata["start_season"][:4]),
                                   int(metadata["through_season"][:4]),
                                   min_games=args.min_games,
                                   min_second_season_ppg=args.min_second_season_ppg,
                                   max_early_drop=args.max_early_drop)
    output = PROJECT_DIR / "data/processed/analysis/historical_fourth_year_candidates.csv"
    output.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(output, index=False)
    print(result.to_string(index=False, float_format=lambda value: f"{value:.2f}"))
    print(f"Saved: {output}")


if __name__ == "__main__":
    main()
