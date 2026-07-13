"""Orchestrates API-Football team-season-statistics ingestion (Paso 2.3).

Fetches all teams for a league's season in one call, matches each against existing `teams`
by name (same criterion as football_data_mapper.py: case-insensitive, trimmed), links via
`team_external_ids` (source='api-football'), creates a new Team + logs a warning when
unmatched (cross-source reconciliation is Paso 2.4, not resolved here), then fetches and
upserts each team's aggregated season statistics as raw JSON into `team_season_stats_raw`.

Does not fetch lineups-per-fixture or per-match statistics - out of scope until quota
handling for hundreds of calls/day is revisited (not before Fase 6).

Usage:
    uv run python -m src.ingestion.api_football_ingest --season 2023
    uv run python -m src.ingestion.api_football_ingest --season 2024
"""

from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from src.config import Settings
from src.data.models import Season, Team, TeamExternalId, TeamSeasonStatsRaw
from src.db import engine as default_engine
from src.exceptions import DataValidationError
from src.ingestion.api_football_client import APIFootballClient
from src.ingestion.constants import BSA_API_FOOTBALL_LEAGUE_ID
from src.logging_config import setup_logging

logger = logging.getLogger(__name__)

SOURCE = "api-football"


def _clean_text(value: str) -> str:
    return " ".join(value.split())


@dataclass
class IngestSummary:
    teams_created: int = 0
    stats_created: int = 0
    stats_updated: int = 0
    unmatched_team_warnings: list[str] = field(default_factory=list)

    def add_unmatched_team_warning(self, message: str) -> None:
        self.unmatched_team_warnings.append(message)
        logger.warning(message)


def _resolve_team(
    session: Session,
    teams_by_external_id: dict[str, Team],
    teams_by_normalized_name: dict[str, Team],
    api_team: dict,
    summary: IngestSummary,
) -> Team:
    external_id = str(api_team["id"])
    existing = teams_by_external_id.get(external_id)
    if existing is not None:
        return existing

    api_name = _clean_text(api_team.get("name") or "")
    normalized_name = api_name.lower()
    team = teams_by_normalized_name.get(normalized_name)

    if team is None:
        summary.add_unmatched_team_warning(
            f"No existing team matched API-Football team {api_name!r} "
            f"(external_id={external_id}); creating a new Team. Cross-source name "
            "reconciliation is Paso 2.4, not resolved here with ad-hoc heuristics."
        )
        team = Team(official_name=api_name, short_name=api_team.get("code") or api_name)
        session.add(team)
        session.flush()
        summary.teams_created += 1
        teams_by_normalized_name[normalized_name] = team

    session.add(TeamExternalId(team_id=team.id, source=SOURCE, external_id=external_id))
    teams_by_external_id[external_id] = team
    return team


def ingest_team_season_stats(
    client: APIFootballClient, league_id: int, season_year: int, engine: Engine
) -> IngestSummary:
    """Fetch and upsert aggregated team-season statistics for one league season.

    Idempotent: re-running updates the existing `team_season_stats_raw` row (raw_json,
    fetched_at) in place instead of duplicating it, keyed by (team_id, season_id, source).
    """
    summary = IngestSummary()

    raw_teams = client.get_teams(league_id, season_year)
    if not raw_teams:
        logger.warning(
            "No teams returned by API-Football for league %d season %d", league_id, season_year
        )
        return summary

    with Session(engine) as session:
        season = session.execute(
            select(Season).where(Season.year == season_year)
        ).scalar_one_or_none()
        if season is None:
            raise DataValidationError(
                f"Season {season_year} does not exist yet in the database - ingest fixtures "
                "for it first (Paso 2.1 bootstrap or Paso 2.2 football-data.org client) "
                "before fetching team statistics.",
                context={"season_year": season_year},
            )

        teams_by_external_id = {
            tei.external_id: tei.team
            for tei in session.execute(
                select(TeamExternalId).where(TeamExternalId.source == SOURCE)
            ).scalars()
        }
        teams_by_normalized_name = {
            t.official_name.lower(): t for t in session.execute(select(Team)).scalars()
        }
        existing_stats_by_key = {
            (s.team_id, s.season_id, s.source): s
            for s in session.execute(
                select(TeamSeasonStatsRaw).where(TeamSeasonStatsRaw.season_id == season.id)
            ).scalars()
        }

        for raw_team_entry in raw_teams:
            api_team = raw_team_entry.get("team") or {}
            team = _resolve_team(
                session, teams_by_external_id, teams_by_normalized_name, api_team, summary
            )

            raw_stats = client.get_team_statistics(league_id, season_year, api_team["id"])
            if not raw_stats:
                logger.warning(
                    "No statistics returned by API-Football for team_id=%s (season %d)",
                    api_team.get("id"),
                    season_year,
                )
                continue

            fetched_at = datetime.now(UTC)
            key = (team.id, season.id, SOURCE)
            existing_stats = existing_stats_by_key.get(key)
            if existing_stats is not None:
                existing_stats.raw_json = raw_stats
                existing_stats.fetched_at = fetched_at
                summary.stats_updated += 1
            else:
                new_stats = TeamSeasonStatsRaw(
                    team_id=team.id,
                    season_id=season.id,
                    source=SOURCE,
                    raw_json=raw_stats,
                    fetched_at=fetched_at,
                )
                session.add(new_stats)
                existing_stats_by_key[key] = new_stats
                summary.stats_created += 1

        session.commit()

    return summary


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fetch and persist API-Football aggregated team-season statistics."
    )
    parser.add_argument("--season", type=int, required=True, help="Season year, e.g. 2024.")
    parser.add_argument(
        "--league-id",
        type=int,
        default=BSA_API_FOOTBALL_LEAGUE_ID,
        help=f"API-Football league ID (default: {BSA_API_FOOTBALL_LEAGUE_ID}, Série A).",
    )
    args = parser.parse_args()

    setup_logging(Settings().log_level)

    with APIFootballClient() as client:
        summary = ingest_team_season_stats(client, args.league_id, args.season, default_engine)

    logger.info(
        "Ingest finished for season %d: %d teams created, %d stats created, %d stats "
        "updated, %d unmatched-team warnings.",
        args.season,
        summary.teams_created,
        summary.stats_created,
        summary.stats_updated,
        len(summary.unmatched_team_warnings),
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())
