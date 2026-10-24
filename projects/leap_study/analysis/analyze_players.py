"""Apply leap-study selection rules and export data for later visualization."""

import argparse
from contextlib import closing
from datetime import datetime, timezone
import json
from math import isfinite
from pathlib import Path
import sqlite3

import pandas as pd

PROJECT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_DATABASE = PROJECT_DIR / "data" / "processed" / "leap_study.sqlite"
DEFAULT_OUTPUT = PROJECT_DIR / "data" / "processed" / "analysis"


def analyze_players(data, *, min_games=25, min_second_season_ppg=10.0,
                    max_early_drop=0.25):
    """Return player decisions and an audit of every original player-season.

    Seasons below min_games are removed BEFORE numbering qualifying seasons.
    The scoring threshold applies to season two's own PPG, not cumulative PPG.
    Declines are tested for seasons 1->2 and 2->3, including the exact boundary.
    A zero-PPG season cannot have a relative decline to a nonnegative PPG.
    """
    if isinstance(min_games, bool) or not isinstance(min_games, int) or min_games < 1:
        raise ValueError("min_games must be a positive integer")
    if not isfinite(min_second_season_ppg) or min_second_season_ppg < 0:
        raise ValueError("min_second_season_ppg must be finite and nonnegative")
    if not isfinite(max_early_drop) or not 0 < max_early_drop <= 1:
        raise ValueError("max_early_drop must be greater than 0 and at most 1")

    audit = data.sort_values(["player_id", "season_year"]).reset_index(drop=True).copy()
    if audit.duplicated(["player_id", "season_year"]).any():
        raise ValueError("Duplicate player-season records")
    for column in ("games_played", "total_points"):
        values = pd.to_numeric(audit[column], errors="raise")
        if values.isna().any() or (values < 0).any() or (values % 1 != 0).any():
            raise ValueError(f"Invalid {column}")
        audit[column] = values
    if (audit["games_played"] == 0).any():
        raise ValueError("Source seasons must have at least one game played")
    audit["points_per_game"] = audit["total_points"] / audit["games_played"]
    audit["season_qualifies"] = audit["games_played"] >= min_games
    numbering = audit.groupby("player_id")["season_qualifies"].cumsum()
    audit["qualifying_season"] = numbering.where(audit["season_qualifies"]).astype("Int64")
    audit["season_exclusion_reason"] = audit["season_qualifies"].map(
        {True: "", False: "below_minimum_games"})

    columns = ["player_id", "player_name", "debut_season", "total_seasons",
               "qualifying_seasons", "skipped_seasons", "second_qualifying_season",
               "second_season_ppg", "meets_second_season_ppg", "early_decline",
               "early_drop_transitions", "early_decline_check_complete",
               "included", "status", "exclusion_reasons"]
    decisions = []
    for player_id, all_seasons in audit.groupby("player_id", sort=False):
        valid = all_seasons.loc[all_seasons["season_qualifies"]]
        early = list(valid.head(3).itertuples())
        second = early[1] if len(early) >= 2 else None
        passes_ppg = second.points_per_game >= min_second_season_ppg if second else None
        drops = []
        for previous, current in zip(early, early[1:]):
            if (previous.points_per_game > 0 and
                    current.points_per_game <= previous.points_per_game * (1 - max_early_drop)):
                drops.append(f"{previous.season}->{current.season}")
        reasons = []
        if second is None:
            reasons.append("insufficient_qualifying_seasons")
        elif not passes_ppg:
            reasons.append("below_second_season_ppg")
        if drops:
            reasons.append("early_ppg_decline")
        included = not reasons
        status = ("included" if len(early) == 3 else "included_pending_third_season") if included else (
            "insufficient_data" if second is None else "excluded")
        first = all_seasons.iloc[0]
        decisions.append([
            player_id, first["player_name"], first["debut_season"], len(all_seasons),
            len(valid), len(all_seasons) - len(valid), second.season if second else None,
            second.points_per_game if second else None, passes_ppg, bool(drops),
            ";".join(drops), len(early) == 3, included, status, ";".join(reasons),
        ])
    decisions = pd.DataFrame(decisions, columns=columns)
    audit = audit.merge(decisions[["player_id", "included", "status", "exclusion_reasons"]],
                        on="player_id", how="left", validate="many_to_one")
    return decisions, audit


def rank_candidates(decisions, eligible, latest_year):
    """Rank by latest qualifying-season PPG, requiring it be in the final source season."""
    counts = decisions.set_index("player_id")["qualifying_seasons"]
    ranked = eligible.copy()
    ranked["completed_qualifying_seasons"] = ranked["player_id"].map(counts)
    ranked = ranked.loc[
        ranked["completed_qualifying_seasons"].isin([2, 3])
        & (ranked["qualifying_season"] == ranked["completed_qualifying_seasons"])
        & (ranked["season_year"] == latest_year)
    ].copy()
    ranked["entering_qualifying_season"] = ranked["completed_qualifying_seasons"] + 1
    ranked = ranked.sort_values(["points_per_game", "player_name"], ascending=[False, True])
    ranked["rank"] = ranked["points_per_game"].rank(method="min", ascending=False).astype(int)
    return ranked[["rank", "player_id", "player_name", "debut_season", "season",
                   "games_played", "points_per_game", "completed_qualifying_seasons",
                   "entering_qualifying_season", "status"]].reset_index(drop=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--min-games", type=int, default=25)
    parser.add_argument("--min-second-season-ppg", type=float, default=10.0)
    parser.add_argument("--max-early-drop", type=float, default=0.25,
                        help="Fractional decline threshold (0.25 means 25%%)")
    args = parser.parse_args()
    # Read-only connection prevents accidentally creating an empty input database.
    database = args.database.resolve()
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as db:
        data = pd.read_sql_query("""
            SELECT p.player_id, p.player_name, p.debut_season,
                   s.season, s.season_year, s.career_year, s.games_played, s.total_points
            FROM players p JOIN player_seasons s USING (player_id)
        """, db)
        source_metadata = dict(db.execute("SELECT key, value FROM metadata"))
    decisions, audit = analyze_players(
        data, min_games=args.min_games, min_second_season_ppg=args.min_second_season_ppg,
        max_early_drop=args.max_early_drop)
    eligible = audit.loc[audit["included"] & audit["season_qualifies"]].copy()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    decisions.to_csv(args.output_dir / "player_decisions.csv", index=False)
    audit.to_csv(args.output_dir / "season_audit.csv", index=False)
    eligible.to_csv(args.output_dir / "eligible_seasons.csv", index=False)
    candidates = rank_candidates(decisions, eligible, int(source_metadata["through_season"][:4]))
    candidates.to_csv(args.output_dir / "leap_candidates.csv", index=False)
    fourth = candidates.loc[candidates["entering_qualifying_season"] == 4].copy()
    fourth["rank"] = fourth["points_per_game"].rank(method="min", ascending=False).astype(int)
    fourth.to_csv(args.output_dir / "entering_fourth_year_ppg_rankings.csv", index=False)
    third_year = eligible.loc[(eligible["status"] == "included")
                              & (eligible["qualifying_season"] == 3)].copy()
    third_year = third_year.sort_values(["points_per_game", "player_name"], ascending=[False, True])
    third_year["rank"] = third_year["points_per_game"].rank(method="min", ascending=False).astype(int)
    third_year[["rank", "player_id", "player_name", "debut_season", "season", "games_played",
                "points_per_game"]].to_csv(args.output_dir / "third_year_ppg_rankings.csv", index=False)
    counts = {str(k): int(v) for k, v in decisions["status"].value_counts().items()}
    summary = {
        "analyzed_at": datetime.now(timezone.utc).isoformat(),
        "database": str(database), "source_metadata": source_metadata,
        "criteria": {"min_games": args.min_games,
                     "min_second_season_ppg": args.min_second_season_ppg,
                     "max_early_drop": args.max_early_drop},
        "players_analyzed": len(decisions), "status_counts": counts,
        "included_players": int(decisions["included"].sum()),
        "eligible_player_seasons": len(eligible),
        "candidates_entering_third": int((candidates["entering_qualifying_season"] == 3).sum()),
        "candidates_entering_fourth": len(fourth),
        "seasons_below_minimum_games": int((~audit["season_qualifies"]).sum()),
        "provisional_policy": "Include passing players with two qualifying seasons; flag pending third season",
    }
    (args.output_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"Analyzed {len(decisions):,} players")
    for status, count in counts.items():
        print(f"  {status}: {count:,}")
    print(f"Retained {len(eligible):,} qualifying player-seasons for visualization")
    print(f"Outputs: {args.output_dir.resolve()}")
    print(f"Ranked shortlist: {len(candidates)} players in leap_candidates.csv "
          f"({len(candidates) - len(fourth)} entering third; {len(fourth)} entering fourth)")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, sqlite3.Error, pd.errors.DatabaseError) as exc:
        raise SystemExit(f"Analysis failed: {exc}")
