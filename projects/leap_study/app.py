"""Interactive Leap Study page, using the same rules as the analysis scripts."""

from io import BytesIO
import os
from pathlib import Path

import matplotlib.pyplot as plt
import streamlit as st
from streamlit.errors import StreamlitSecretNotFoundError

from cards_tracker.app_data import read_cloud_study, read_local_study
from projects.leap_study.analysis.analyze_players import analyze_players, rank_candidates
from projects.leap_study.analysis.plot_ppg_growth import create_growth_figure, summarize_growth

PROJECT_DIR = Path(__file__).resolve().parent


def connection_string():
    value = os.environ.get("SQLITE_CLOUD_CONNECTION_STRING")
    if value:
        return value
    try:
        return st.secrets.get("SQLITE_CLOUD_CONNECTION_STRING", "")
    except StreamlitSecretNotFoundError:
        return ""


@st.cache_data(ttl=300, max_entries=4, show_spinner=False)
def load_cloud(url):
    try:
        return read_cloud_study(url)
    except Exception:
        # Provider exceptions may contain the secret URL. Never forward them.
        raise ValueError("Cloud data could not be loaded. Check the configured connection and database access.") from None


@st.cache_data(ttl=300, max_entries=4, show_spinner=False)
def load_local(path, modified_at):
    return read_local_study(path)


def render():
    st.title("Leap Study")
    st.write("Explore how scoring develops, then find players approaching their third or fourth qualifying season.")

    with st.sidebar:
        st.subheader("Player criteria")
        min_ppg = st.number_input("Minimum second-season PPG", min_value=0.0,
                                  value=10.0, step=0.5, key="leap_min_ppg",
                                  help="Required PPG in the second qualifying season, not a career average.")
        drop_pct = st.number_input("Early PPG drop-off threshold (%)", min_value=1.0,
                                   max_value=100.0, value=25.0, step=1.0, key="leap_drop",
                                   help="Exclude a player if PPG drops by this percentage or more between qualifying seasons 1–2 or 2–3.")
        min_games = st.number_input("Minimum games per season", min_value=1,
                                    value=25, step=1, key="leap_min_games",
                                    help="Seasons with fewer games are skipped before numbering a player's seasons.")
        st.subheader("Data")
        source = st.selectbox("Data source", ["SQLite Cloud", "Local database"], key="leap_source")
        if st.button("Refresh data", key="leap_refresh"):
            load_cloud.clear()
            load_local.clear()
    try:
        with st.spinner("Loading player histories…"):
            if source == "SQLite Cloud":
                url = connection_string()
                if not url:
                    st.info("Set SQLITE_CLOUD_CONNECTION_STRING in your environment or Streamlit secrets to load cloud data. You can also select Local database in the sidebar.")
                    return
                data, metadata, snapshot = load_cloud(url)
            else:
                path = PROJECT_DIR / "data/processed/leap_study.sqlite"
                data, metadata, snapshot = load_local(str(path), path.stat().st_mtime_ns)
    except Exception:
        st.error("Unable to load the selected data source. Check the database configuration and use Refresh data to retry.")
        return
    if data.empty:
        st.info("The selected database has no player histories yet.")
        return

    st.caption(f"{source} · {metadata['start_season']} through {metadata['through_season']} · regular season · data built {metadata.get('built_at', 'unknown')}")
    with st.spinner("Applying player criteria…"):
        decisions, audit = analyze_players(data, min_games=int(min_games),
                                           min_second_season_ppg=float(min_ppg),
                                           max_early_drop=float(drop_pct) / 100)
        eligible = audit.loc[audit["included"] & audit["season_qualifies"]].copy()
        candidates = rank_candidates(decisions, eligible, int(metadata["through_season"][:4]))
    complete = int((decisions.status == "included").sum())
    provisional = int((decisions.status == "included_pending_third_season").sum())
    cols = st.columns(4)
    for col, label, value in zip(cols, ["Players analyzed", "Pass all three seasons", "Provisional two-season players", "Upcoming candidates"],
                                  [len(decisions), complete, provisional, len(candidates)]):
        col.metric(label, f"{value:,}")

    st.subheader("Scoring growth")
    st.caption("Baseline is the first season meeting your games requirement. A ratio of 1.5 means a 50% scoring increase.")
    if eligible.empty:
        st.info("No players meet these criteria. Lower the scoring or games minimum, or increase the allowed decline threshold.")
    else:
        try:
            _, summary, zero_baselines = summarize_growth(eligible)
        except ValueError:
            st.info("The selected players have no positive first-season PPG to normalize. Adjust the criteria to plot growth.")
        else:
            peak = summary.loc[summary.mean_ratio.idxmax()]
            st.write(f"Highest observed mean: qualifying season **{int(peak.qualifying_season)}**, "
                     f"**+{peak.mean_percent_increase:.1f}%** over baseline. "
                     "The dashed line marks year four for comparison.")
            fig = create_growth_figure(summary, subtitle=f"{eligible.player_id.nunique():,} eligible players · minimum {min_games} games · includes provisional players")
            try:
                st.pyplot(fig)
                image = BytesIO()
                fig.savefig(image, format="png", dpi=180)
                st.download_button("Download plot", image.getvalue(), "ppg_growth.png", "image/png")
            finally:
                plt.close(fig)
            if zero_baselines:
                st.caption(f"Excluded {zero_baselines} players with zero baseline PPG from the growth plot.")
            st.download_button("Download plot data", summary.to_csv(index=False), "ppg_growth.csv", "text/csv")

    st.subheader("Players to watch")
    st.caption("Ranked by their latest qualifying-season PPG. Candidates finished exactly two or three qualifying seasons, with their latest in the final season of this dataset. Entering-third players still await their third-season decline check. These are research candidates, not forecasts.")
    if candidates.empty:
        st.info("No entering-third or entering-fourth candidates meet these criteria.")
    else:
        display = candidates[["rank", "player_name", "points_per_game", "games_played", "season", "entering_qualifying_season"]].copy()
        display["entering_qualifying_season"] = display.entering_qualifying_season.map({3: "3rd (provisional)", 4: "4th"})
        display.columns = ["Rank", "Player", "Latest PPG", "Games", "Latest season", "Entering qualifying season"]
        st.dataframe(display, hide_index=True,
                     column_config={"Latest PPG": st.column_config.NumberColumn(format="%.2f")})
        st.download_button("Download ranked candidates", candidates.to_csv(index=False), "leap_candidates.csv", "text/csv")
