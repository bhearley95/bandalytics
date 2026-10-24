"""Reusable access to NBA.com player statistics through nba_api."""

from dataclasses import dataclass
from datetime import date, datetime
from math import isfinite
from numbers import Integral
from typing import Literal

import pandas as pd
from nba_api.stats.endpoints.playergamelog import PlayerGameLog
from nba_api.stats.endpoints.commonallplayers import CommonAllPlayers
from nba_api.stats.endpoints.leaguedashplayerstats import LeagueDashPlayerStats
from nba_api.stats.static import players

SeasonType = Literal["Regular Season", "Playoffs", "Pre Season", "All-Star"]


class NBAQueryError(RuntimeError):
    """NBA.com could not provide a complete, valid query result."""


@dataclass(frozen=True)
class PointsSummary:
    player_id: int
    start_date: date
    end_date: date
    games_played: int
    total_points: int
    points_per_game: float | None


def _date(value: date | str) -> date:
    if isinstance(value, datetime):
        raise TypeError("Use a date or YYYY-MM-DD string, not a datetime")
    return date.fromisoformat(value) if isinstance(value, str) else value


class NBAClient:
    """Query inclusive calendar date ranges; regular season is the default.

    Names must match one player exactly (case insensitive). Use search_players
    for partial names, then pass a player ID when names are ambiguous.
    """

    def __init__(self, *, timeout: float = 30, proxy: str | None = None):
        if not isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout must be a finite positive number")
        self.timeout = timeout
        self.proxy = proxy

    def get_player_directory(self, season: str) -> dict:
        """Return the historical NBA player directory, including debut years."""
        try:
            return CommonAllPlayers(
                season=season, is_only_current_season=0, league_id="00",
                timeout=self.timeout, proxy=self.proxy,
            ).get_dict()
        except Exception as exc:
            raise NBAQueryError("Failed to retrieve the NBA player directory") from exc

    def get_league_season_totals(self, season: str) -> dict:
        """Return raw regular-season totals for all players, across all teams."""
        try:
            return LeagueDashPlayerStats(
                season=season, season_type_all_star="Regular Season",
                per_mode_detailed="Totals", league_id_nullable="00",
                timeout=self.timeout, proxy=self.proxy,
            ).get_dict()
        except Exception as exc:
            raise NBAQueryError(f"Failed to retrieve league totals for {season}") from exc

    def search_players(self, name: str) -> list[dict]:
        """Search the package's local player directory, including retired players."""
        if not isinstance(name, str) or not name.strip():
            raise ValueError("name must be a nonempty string")
        query = name.strip().casefold()
        return [p.copy() for p in players.get_players() if query in p["full_name"].casefold()]

    def resolve_player_id(self, player: int | str) -> int:
        if isinstance(player, Integral) and not isinstance(player, bool) and player > 0:
            return int(player)
        if not isinstance(player, str) or not player.strip():
            raise ValueError("player must be a positive ID or full name")
        matches = [p for p in self.search_players(player)
                   if p["full_name"].casefold() == player.strip().casefold()]
        if len(matches) != 1:
            raise ValueError(f"Expected one exact player match for {player!r}; found {len(matches)}. "
                             "Use search_players() and pass an ID.")
        return matches[0]["id"]

    def get_player_game_logs(
        self, player: int | str, start_date: date | str, end_date: date | str,
        *, season_type: SeasonType = "Regular Season",
    ) -> pd.DataFrame:
        """Return game statistics sorted oldest first, including both boundary dates.

        Queries each potentially overlapping season, including the previous
        calendar year's season to cover playoffs and delayed seasons. NBA.com
        failures raise NBAQueryError instead of returning partial results.
        """
        start, end = _date(start_date), _date(end_date)
        if not isinstance(start, date) or not isinstance(end, date):
            raise TypeError("Dates must be date objects or YYYY-MM-DD strings")
        if start > end:
            raise ValueError("start_date must be on or before end_date")
        if season_type not in ("Regular Season", "Playoffs", "Pre Season", "All-Star"):
            raise ValueError(f"Unsupported season_type: {season_type!r}")
        player_id = self.resolve_player_id(player)
        frames = []
        for year in range(start.year - 1, end.year + 1):
            season = f"{year}-{(year + 1) % 100:02d}"
            try:
                frame = PlayerGameLog(
                    player_id=player_id, season=season,
                    season_type_all_star=season_type,
                    date_from_nullable=start.strftime("%m/%d/%Y"),
                    date_to_nullable=end.strftime("%m/%d/%Y"),
                    timeout=self.timeout, proxy=self.proxy,
                ).get_data_frames()[0].copy()
                if not {"GAME_DATE", "Game_ID", "PTS"}.issubset(frame.columns):
                    raise ValueError("Missing expected game log columns")
                frame["GAME_DATE"] = pd.to_datetime(
                    frame["GAME_DATE"], format="%b %d, %Y", errors="raise")
                if frame["GAME_DATE"].isna().any():
                    raise ValueError("Missing game dates")
                frame = frame.loc[frame["GAME_DATE"].dt.date.between(start, end)].copy()
                frame["SEASON"] = season
                frames.append(frame)
            except Exception as exc:
                raise NBAQueryError(
                    f"Failed to retrieve player {player_id}, season {season}, "
                    f"{season_type}, {start} through {end}"
                ) from exc
        result = pd.concat(frames, ignore_index=True)
        return (result.drop_duplicates(subset=["Game_ID"])
                .sort_values(["GAME_DATE", "Game_ID"]).reset_index(drop=True))

    def get_points_summary(
        self, player: int | str, start_date: date | str, end_date: date | str,
        *, season_type: SeasonType = "Regular Season",
    ) -> PointsSummary:
        """Summarize points in games returned for the requested date range."""
        player_id = self.resolve_player_id(player)
        games = self.get_player_game_logs(player_id, start_date, end_date, season_type=season_type)
        try:
            points = pd.to_numeric(games["PTS"], errors="raise")
            if points.isna().any() or (points < 0).any() or (points % 1 != 0).any():
                raise ValueError("Invalid points values")
            total = int(points.sum())
        except (ValueError, TypeError, OverflowError) as exc:
            raise NBAQueryError("NBA.com returned invalid points values") from exc
        count = len(games)
        return PointsSummary(player_id, _date(start_date), _date(end_date), count,
                             total, total / count if count else None)
