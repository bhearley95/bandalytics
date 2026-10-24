"""Plot mean PPG relative to the first qualifying season, with sample SD."""

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_DIR = Path(__file__).resolve().parents[1]


def summarize_growth(seasons):
    """Equal player weights within each season; no padding of missing careers."""
    data = seasons.sort_values(["player_id", "qualifying_season"]).copy()
    if data.empty:
        raise ValueError("No eligible player-seasons to plot")
    if data.duplicated(["player_id", "qualifying_season"]).any():
        raise ValueError("Duplicate player/qualifying-season rows")
    ppg = pd.to_numeric(data["points_per_game"], errors="raise")
    if not np.isfinite(ppg).all() or (ppg < 0).any():
        raise ValueError("PPG must be finite and nonnegative")
    data["points_per_game"] = ppg
    baseline = data.loc[data["qualifying_season"] == 1, ["player_id", "points_per_game"]]
    baseline = baseline.rename(columns={"points_per_game": "baseline_ppg"})
    data = data.merge(baseline, on="player_id", how="left", validate="many_to_one")
    if data["baseline_ppg"].isna().any():
        raise ValueError("Every player must have qualifying season one")
    excluded = data.loc[data["baseline_ppg"] == 0, "player_id"].nunique()
    data = data.loc[data["baseline_ppg"] > 0].copy()
    if data.empty:
        raise ValueError("All players have zero baseline PPG; relative growth is undefined")
    data["ppg_relative_to_rookie"] = data["points_per_game"] / data["baseline_ppg"]
    data["percent_increase_from_rookie"] = (data["ppg_relative_to_rookie"] - 1) * 100
    summary = data.groupby("qualifying_season")["ppg_relative_to_rookie"].agg(
        player_count="count", mean_ratio="mean", std_ratio="std").reset_index()
    summary["mean_percent_increase"] = (summary["mean_ratio"] - 1) * 100
    summary["std_percentage_points"] = summary["std_ratio"] * 100
    return data, summary, int(excluded)


def create_growth_figure(summary, *, subtitle):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.ticker import MaxNLocator

    x = summary["qualifying_season"].to_numpy()
    mean = summary["mean_ratio"].to_numpy()
    std = summary["std_ratio"].to_numpy()
    with plt.style.context("seaborn-v0_8-whitegrid"):
        fig, (ax, counts) = plt.subplots(
            2, 1, figsize=(12, 8), sharex=True,
            gridspec_kw={"height_ratios": [4, 1], "hspace": 0.12})
        ax.plot(x, mean, color="#176b9b", marker="o", markersize=4, label="Mean PPG ratio")
        ax.fill_between(x, mean - std, mean + std, color="#176b9b", alpha=0.18,
                        label="Mean ± 1 sample standard deviation")
        ax.axhline(1, color="#6b7280", linestyle="--", linewidth=1)
        ax.axvline(4, color="#c76a26", linestyle="--", linewidth=1.5,
                   label="Qualifying season 4")
        ax.set_ylabel("PPG / first qualifying season PPG")
        ax.set_title("How scoring changes after a player's first qualifying season", loc="left", pad=30)
        ax.text(0, 1.02, subtitle, transform=ax.transAxes, fontsize=9, color="#4b5563")
        ax.legend(loc="upper right", fontsize=9, frameon=True, framealpha=0.95)
        ax.text(0.99, 0.02, "1.0 = baseline · 1.5 = +50% · 2.0 = +100%",
                transform=ax.transAxes, ha="right", fontsize=9)
        counts.bar(x, summary["player_count"], color="#8198a5", width=0.7)
        counts.set_ylabel("Players")
        counts.set_xlabel("Qualifying career season (seasons below the games threshold are skipped)")
        counts.xaxis.set_major_locator(MaxNLocator(integer=True))
        for axis in (ax, counts):
            axis.spines[["top", "right"]].set_visible(False)
        fig.text(0.08, 0.025,
                 "Equal weight per player. Available players vary by season; later years select for longer careers.\n"
                 "Band shows player variation, not uncertainty in the mean. SD is undefined for a single player.",
                 fontsize=9, color="#4b5563")
        fig.subplots_adjust(left=0.09, right=0.97, top=0.87, bottom=0.14)
        return fig


def plot_growth(summary, output, *, subtitle):
    import matplotlib.pyplot as plt
    fig = create_growth_figure(summary, subtitle=subtitle)
    try:
        for suffix in (".png", ".svg"):
            fig.savefig(output.with_suffix(suffix), dpi=180)
    finally:
        plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path,
                        default=PROJECT_DIR / "data/processed/analysis/eligible_seasons.csv")
    parser.add_argument("--output-dir", type=Path, default=PROJECT_DIR / "figures")
    parser.add_argument("--exclude-provisional", action="store_true",
                        help="Only use players with a completed three-season decline check")
    args = parser.parse_args()
    seasons = pd.read_csv(args.input)
    if args.exclude_provisional:
        seasons = seasons.loc[seasons["status"] == "included"]
    data, summary, excluded = summarize_growth(seasons)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    stem = "ppg_growth" + ("_confirmed" if args.exclude_provisional else "")
    output = args.output_dir / stem
    summary.to_csv(output.with_suffix(".csv"), index=False)
    data.to_csv(args.output_dir / f"{stem}_player_ratios.csv", index=False)
    policy = "provisional players excluded" if args.exclude_provisional else "includes provisional players"
    plot_growth(summary, output, subtitle=f"{data.player_id.nunique():,} eligible players · regular season · {policy}")
    print(summary.to_string(index=False, float_format=lambda value: f"{value:.3f}"))
    print(f"Zero-baseline players excluded: {excluded}")
    print(f"Saved PNG, SVG and chart data: {output}")


if __name__ == "__main__":
    main()
