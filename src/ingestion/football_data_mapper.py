"""Maps raw football-data.org match JSON into the core schema, as an upsert.

Does not persist the standings/table endpoint anywhere — per CLAUDE.md's anti-leakage rule,
a team's position at date X is derived from `matches` filtered by that date (Fase 5), never
stored as an external snapshot that can drift out of sync.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from src.data.models import Match, MatchExternalId, Season, Team, TeamExternalId, Venue

logger = logging.getLogger(__name__)

SOURCE = "football-data.org"

# Confirmed against docs.football-data.org/general/v4/lookup_tables.html. The task's original
# mapping covered 8 of the 11 real status values; EXTRA_TIME/PENALTY_SHOOTOUT/AWARDED below are
# the ones it didn't mention, bucketed to match the spirit of the given mapping.
API_STATUS_TO_MATCH_STATUS: dict[str, str] = {
    "SCHEDULED": "scheduled",
    "TIMED": "scheduled",
    "IN_PLAY": "scheduled",
    "PAUSED": "scheduled",
    "EXTRA_TIME": "scheduled",
    "PENALTY_SHOOTOUT": "scheduled",
    "FINISHED": "finished",
    # AWARDED = decided administratively (W.O.) rather than played out. This endpoint has no
    # further detail than the status itself, so result_type stays 'played' as instructed —
    # same documented limitation as the Fase 2.1 bootstrap, to revisit in Fase 4.
    "AWARDED": "finished",
    "POSTPONED": "postponed",
    "SUSPENDED": "cancelled",
    "CANCELLED": "cancelled",
}

# Statuses that mean "not concluded yet" - used to infer whether a season is still in progress.
_NON_TERMINAL_STATUSES = {"scheduled", "postponed"}


@dataclass
class ImportSummary:
    matches_created: int = 0
    matches_updated: int = 0
    teams_created: int = 0
    venues_created: int = 0
    unmatched_team_warnings: list[str] = field(default_factory=list)

    def add_unmatched_team_warning(self, message: str) -> None:
        self.unmatched_team_warnings.append(message)
        logger.warning(message)


def _clean_text(value: str) -> str:
    return " ".join(value.split())


def _resolve_team(
    session: Session,
    teams_by_external_id: dict[str, Team],
    teams_by_normalized_name: dict[str, Team],
    api_team: dict,
    summary: ImportSummary,
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
            f"No existing team matched football-data.org team {api_name!r} "
            f"(external_id={external_id}); creating a new Team. Cross-source name "
            "reconciliation is Paso 2.4, not resolved here with ad-hoc heuristics."
        )
        team = Team(official_name=api_name, short_name=api_team.get("shortName") or api_name)
        session.add(team)
        session.flush()
        summary.teams_created += 1
        teams_by_normalized_name[normalized_name] = team

    session.add(TeamExternalId(team_id=team.id, source=SOURCE, external_id=external_id))
    teams_by_external_id[external_id] = team
    return team


def _resolve_venue(
    session: Session,
    venues_by_name: dict[str, Venue],
    raw_venue_name: str | None,
    summary: ImportSummary,
) -> Venue | None:
    venue_name = _clean_text(raw_venue_name or "")
    if not venue_name:
        return None

    venue = venues_by_name.get(venue_name)
    if venue is None:
        venue = Venue(name=venue_name)
        session.add(venue)
        session.flush()
        summary.venues_created += 1
        venues_by_name[venue_name] = venue
    return venue


def _map_status(raw_status: str) -> str:
    status = API_STATUS_TO_MATCH_STATUS.get(raw_status)
    if status is None:
        logger.warning(
            "Unknown football-data.org match status %r, defaulting to 'scheduled'", raw_status
        )
        return "scheduled"
    return status


def import_matches(raw_matches: list[dict], season_year: int, engine: Engine) -> ImportSummary:
    """Upsert a list of raw football-data.org match dicts for one season into the core schema.

    Idempotent: re-running with the same (or updated) raw matches updates the existing Match
    rows in place (status, score, venue) instead of duplicating them, keyed first by
    match_external_ids and falling back to the matches natural key (season/matchday/teams/leg).
    """
    summary = ImportSummary()
    if not raw_matches:
        logger.warning("No matches to import for season %d.", season_year)
        return summary

    with Session(engine) as session:
        season = session.execute(
            select(Season).where(Season.year == season_year)
        ).scalar_one_or_none()

        match_dates = [
            datetime.fromisoformat(m["utcDate"].replace("Z", "+00:00")).date() for m in raw_matches
        ]
        start_date, end_date = min(match_dates), max(match_dates)
        is_in_progress = any(
            _map_status(m["status"]) in _NON_TERMINAL_STATUSES for m in raw_matches
        )
        season_status = "in_progress" if is_in_progress else "finished"

        if season is None:
            season = Season(
                year=season_year, start_date=start_date, end_date=end_date, status=season_status
            )
            session.add(season)
            session.flush()
        else:
            if season.start_date > start_date:
                season.start_date = start_date
            if season.end_date is None or season.end_date < end_date:
                season.end_date = end_date
            season.status = season_status

        teams_by_external_id = {
            tei.external_id: tei.team
            for tei in session.execute(
                select(TeamExternalId).where(TeamExternalId.source == SOURCE)
            ).scalars()
        }
        teams_by_normalized_name = {
            t.official_name.lower(): t for t in session.execute(select(Team)).scalars()
        }
        venues_by_name = {v.name: v for v in session.execute(select(Venue)).scalars()}
        matches_by_external_id: dict[str, Match] = {
            mei.external_id: mei.match
            for mei in session.execute(
                select(MatchExternalId).where(MatchExternalId.source == SOURCE)
            ).scalars()
        }
        matches_by_natural_key: dict[tuple[int, int, int, int, int], Match] = {
            (m.season_id, m.matchday, m.home_team_id, m.away_team_id, m.leg): m
            for m in session.execute(select(Match)).scalars()
        }

        for raw_match in raw_matches:
            external_id = str(raw_match["id"])
            matchday = raw_match.get("matchday")
            if matchday is None:
                logger.warning(
                    "football-data.org match external_id=%s has no matchday, skipping.",
                    external_id,
                )
                continue

            home_team = _resolve_team(
                session,
                teams_by_external_id,
                teams_by_normalized_name,
                raw_match["homeTeam"],
                summary,
            )
            away_team = _resolve_team(
                session,
                teams_by_external_id,
                teams_by_normalized_name,
                raw_match["awayTeam"],
                summary,
            )
            venue = _resolve_venue(session, venues_by_name, raw_match.get("venue"), summary)

            status = _map_status(raw_match["status"])
            scheduled_at = datetime.fromisoformat(raw_match["utcDate"].replace("Z", "+00:00"))
            full_time = (raw_match.get("score") or {}).get("fullTime") or {}
            home_score = full_time.get("home")
            away_score = full_time.get("away")

            existing_match = matches_by_external_id.get(external_id)
            if existing_match is None:
                natural_key = (season.id, matchday, home_team.id, away_team.id, 1)
                existing_match = matches_by_natural_key.get(natural_key)
                if existing_match is not None:
                    logger.warning(
                        "football-data.org match external_id=%s not linked yet, but a Match "
                        "already exists for natural key %s (likely a season-boundary overlap "
                        "with the Fase 2.1 bootstrap) - linking instead of inserting a duplicate.",
                        external_id,
                        natural_key,
                    )
                    session.add(
                        MatchExternalId(
                            match_id=existing_match.id, source=SOURCE, external_id=external_id
                        )
                    )
                    matches_by_external_id[external_id] = existing_match

            if existing_match is not None:
                existing_match.status = status
                existing_match.scheduled_at = scheduled_at
                existing_match.venue_id = venue.id if venue else None
                existing_match.home_score = home_score
                existing_match.away_score = away_score
                summary.matches_updated += 1
                continue

            match = Match(
                season_id=season.id,
                matchday=matchday,
                scheduled_at=scheduled_at,
                home_team_id=home_team.id,
                away_team_id=away_team.id,
                venue_id=venue.id if venue else None,
                status=status,
                result_type="played",
                leg=1,
                home_score=home_score,
                away_score=away_score,
            )
            session.add(match)
            session.flush()
            session.add(MatchExternalId(match_id=match.id, source=SOURCE, external_id=external_id))
            matches_by_external_id[external_id] = match
            matches_by_natural_key[(season.id, matchday, home_team.id, away_team.id, 1)] = match
            summary.matches_created += 1

        session.commit()

    return summary
