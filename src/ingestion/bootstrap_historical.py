"""Bootstrap historical Brasileirão match data from a public GitHub dataset.

Source: https://github.com/adaoduque/Brasileirao_Dataset
Loads `campeonato-brasileiro-full.csv` (closed/finished seasons) into the core schema
(Season, Team, Venue, Match, SeasonTeam). This is a one-time bootstrap for CLOSED seasons —
the current in-progress season is ingested separately via football-data.org in Paso 2.2, with
its own handling of scheduled-vs-played state.

Does not process the companion `campeonato-brasileiro-estatisticas-full.csv` (per-match
attack/defense stats) — that's a later ingestion step once we build those features.

Usage:
    uv run python -m src.ingestion.bootstrap_historical
"""

from __future__ import annotations

import argparse
import csv
import io
import logging
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from src.config import Settings
from src.data.models import Match, Season, SeasonTeam, Team, Venue
from src.db import engine as default_engine
from src.logging_config import setup_logging

logger = logging.getLogger(__name__)

MATCHES_CSV_URL = (
    "https://raw.githubusercontent.com/adaoduque/Brasileirao_Dataset/master/"
    "campeonato-brasileiro-full.csv"
)
# Confirmed to exist and be downloadable; intentionally not processed in this step.
STATISTICS_CSV_URL = (
    "https://raw.githubusercontent.com/adaoduque/Brasileirao_Dataset/master/"
    "campeonato-brasileiro-estatisticas-full.csv"
)

# The source CSV is not encoded as UTF-8 (verified by inspection: latin-1 decodes every
# team/venue name in the dataset correctly, including accented characters).
CSV_ENCODING = "latin-1"

BRAZIL_TZ = ZoneInfo("America/Sao_Paulo")
# A handful of the oldest fixtures in the dataset could plausibly be missing a recorded
# kickoff time; 16:00 is the most common Saturday/Sunday afternoon slot in this dataset.
# Used only as a documented fallback, never a silent guess baked into the data.
DEFAULT_KICKOFF_TIME = time(16, 0)

# Season ingested live via football-data.org (Paso 2.2), never through this bootstrap.
CURRENT_SEASON_YEAR = 2026

SOURCE_LABEL = "github_bootstrap_dataset"

# Verified empirically against the current dataset: no case/whitespace/punctuation
# variants of the same club were found (45 distinct team strings, no collisions after
# normalization). Left here as a hook for Fase 2.4 cross-source reconciliation, or in case
# a future refresh of the dataset introduces inconsistent spellings.
TEAM_NAME_ALIASES: dict[str, str] = {}


@dataclass
class ImportSummary:
    rows_processed: int = 0
    rows_excluded_current_season: int = 0
    seasons_created: int = 0
    teams_created: int = 0
    venues_created: int = 0
    matches_created: int = 0
    matches_skipped_existing: int = 0
    warnings: list[str] = field(default_factory=list)

    def add_warning(self, message: str) -> None:
        self.warnings.append(message)
        logger.warning(message)


@dataclass
class _ParsedRow:
    source_row_id: str
    year: int
    matchday: int
    scheduled_at: datetime
    home_team_name: str
    away_team_name: str
    home_state: str | None
    away_state: str | None
    venue_name: str
    home_score: int
    away_score: int


def _clean_text(value: str) -> str:
    return " ".join(value.split())


def _has_control_chars(value: str) -> bool:
    return any(ord(char) < 0x20 or 0x7F <= ord(char) <= 0x9F for char in value)


def _read_csv_text(csv_url: str) -> str:
    if csv_url.startswith(("http://", "https://")):
        with urllib.request.urlopen(csv_url) as response:
            raw_bytes = response.read()
    else:
        with open(csv_url, "rb") as csv_file:
            raw_bytes = csv_file.read()
    return raw_bytes.decode(CSV_ENCODING)


def confirm_statistics_csv_available(url: str = STATISTICS_CSV_URL) -> bool:
    """Confirm the companion per-match statistics CSV exists and is downloadable.

    Does not download its contents into memory or process them — that's a later ingestion
    step, once attack/defense features are built.
    """
    request = urllib.request.Request(url, method="HEAD")
    try:
        with urllib.request.urlopen(request) as response:
            available = response.status == 200
    except urllib.error.URLError:
        available = False

    if available:
        logger.info("Confirmed companion statistics CSV is reachable: %s", url)
    else:
        logger.warning("Companion statistics CSV could not be reached: %s", url)
    return available


def _parse_row(row: dict[str, str], summary: ImportSummary) -> _ParsedRow | None:
    source_row_id = row.get("ID", "?")

    def skip(reason: str) -> None:
        summary.add_warning(f"row ID={source_row_id}: skipped - {reason}")

    raw_date = (row.get("data") or "").strip()
    try:
        match_date = datetime.strptime(raw_date, "%d/%m/%Y").date()
    except ValueError:
        skip(f"invalid or missing date {raw_date!r}")
        return None

    raw_time = (row.get("hora") or "").strip()
    if raw_time:
        try:
            hour_str, minute_str = raw_time.split(":")
            match_time = time(int(hour_str), int(minute_str))
        except (ValueError, TypeError):
            skip(f"invalid hora {raw_time!r}")
            return None
    else:
        match_time = DEFAULT_KICKOFF_TIME

    scheduled_at = datetime.combine(match_date, match_time, tzinfo=BRAZIL_TZ)

    raw_matchday = (row.get("rodata") or "").strip()
    try:
        matchday = int(raw_matchday)
    except ValueError:
        skip(f"invalid matchday {raw_matchday!r}")
        return None

    home_team_name = TEAM_NAME_ALIASES.get(
        _clean_text(row.get("mandante") or ""), _clean_text(row.get("mandante") or "")
    )
    away_team_name = TEAM_NAME_ALIASES.get(
        _clean_text(row.get("visitante") or ""), _clean_text(row.get("visitante") or "")
    )
    venue_name = _clean_text(row.get("arena") or "")

    if not home_team_name or not away_team_name:
        skip("missing mandante/visitante team name")
        return None
    if home_team_name == away_team_name:
        skip(f"home and away team are the same ({home_team_name!r})")
        return None
    if not venue_name:
        skip("missing arena/venue name")
        return None
    if (
        _has_control_chars(home_team_name)
        or _has_control_chars(away_team_name)
        or _has_control_chars(venue_name)
    ):
        skip(
            "team or venue name contains invalid characters after decoding "
            "(likely a mixed-encoding source row)"
        )
        return None

    raw_home_score = (row.get("mandante_Placar") or "").strip()
    raw_away_score = (row.get("visitante_Placar") or "").strip()
    if not raw_home_score or not raw_away_score:
        skip("missing home/away score for a match expected to be finished")
        return None
    try:
        home_score = int(raw_home_score)
        away_score = int(raw_away_score)
    except ValueError:
        skip(f"non-numeric score ({raw_home_score!r}, {raw_away_score!r})")
        return None

    home_state = _clean_text(row.get("mandante_Estado") or "") or None
    away_state = _clean_text(row.get("visitante_Estado") or "") or None

    return _ParsedRow(
        source_row_id=source_row_id,
        year=match_date.year,
        matchday=matchday,
        scheduled_at=scheduled_at,
        home_team_name=home_team_name,
        away_team_name=away_team_name,
        home_state=home_state,
        away_state=away_state,
        venue_name=venue_name,
        home_score=home_score,
        away_score=away_score,
    )


def import_historical_data(csv_url: str, engine: Engine) -> ImportSummary:
    """Import closed-season historical matches from the bootstrap CSV into the core schema.

    Idempotent: running it twice does not duplicate seasons, teams, venues, season_teams,
    or matches — existing rows are detected via the schema's natural keys/unique
    constraints and skipped, not re-inserted.
    """
    summary = ImportSummary()
    csv_text = _read_csv_text(csv_url)
    reader = csv.DictReader(io.StringIO(csv_text))

    parsed_rows: list[_ParsedRow] = []
    for row in reader:
        summary.rows_processed += 1
        parsed = _parse_row(row, summary)
        if parsed is None:
            continue
        if parsed.year >= CURRENT_SEASON_YEAR:
            logger.info(
                "row ID=%s: excluded - year %d is the current in-progress season, "
                "ingested separately via the live API in Paso 2.2",
                parsed.source_row_id,
                parsed.year,
            )
            summary.rows_excluded_current_season += 1
            continue
        parsed_rows.append(parsed)

    if not parsed_rows:
        logger.warning("No valid historical rows found to import.")
        return summary

    season_bounds: dict[int, tuple[date, date]] = {}
    for parsed in parsed_rows:
        match_date = parsed.scheduled_at.date()
        bounds = season_bounds.get(parsed.year)
        if bounds is None:
            season_bounds[parsed.year] = (match_date, match_date)
        else:
            season_bounds[parsed.year] = (
                min(bounds[0], match_date),
                max(bounds[1], match_date),
            )

    with Session(engine) as session:
        seasons_by_year = {s.year: s for s in session.execute(select(Season)).scalars()}
        teams_by_name = {t.official_name: t for t in session.execute(select(Team)).scalars()}
        venues_by_name = {v.name: v for v in session.execute(select(Venue)).scalars()}
        existing_match_keys = {
            (m.season_id, m.matchday, m.home_team_id, m.away_team_id, m.leg)
            for m in session.execute(select(Match)).scalars()
        }
        existing_season_team_keys = {
            (st.season_id, st.team_id) for st in session.execute(select(SeasonTeam)).scalars()
        }

        for parsed in parsed_rows:
            start_date, end_date = season_bounds[parsed.year]
            season = seasons_by_year.get(parsed.year)
            if season is None:
                season = Season(
                    year=parsed.year, start_date=start_date, end_date=end_date, status="finished"
                )
                session.add(season)
                session.flush()
                summary.seasons_created += 1
                seasons_by_year[parsed.year] = season
            else:
                # Keep bounds accurate no matter which subset of a season's matches was
                # imported first (e.g. a partial fixture run before the full dataset).
                if season.start_date > start_date:
                    season.start_date = start_date
                if season.end_date is None or season.end_date < end_date:
                    season.end_date = end_date

            # short_name mirrors official_name here: this dataset only has one name per
            # club, unlike football-data.org/API-Football which distinguish them (Fase 2.2/2.3).
            home_team = teams_by_name.get(parsed.home_team_name)
            if home_team is None:
                home_team = Team(
                    official_name=parsed.home_team_name,
                    short_name=parsed.home_team_name,
                    state=parsed.home_state,
                )
                session.add(home_team)
                session.flush()
                summary.teams_created += 1
                teams_by_name[parsed.home_team_name] = home_team

            away_team = teams_by_name.get(parsed.away_team_name)
            if away_team is None:
                away_team = Team(
                    official_name=parsed.away_team_name,
                    short_name=parsed.away_team_name,
                    state=parsed.away_state,
                )
                session.add(away_team)
                session.flush()
                summary.teams_created += 1
                teams_by_name[parsed.away_team_name] = away_team

            venue = venues_by_name.get(parsed.venue_name)
            if venue is None:
                venue = Venue(name=parsed.venue_name)
                session.add(venue)
                session.flush()
                summary.venues_created += 1
                venues_by_name[parsed.venue_name] = venue

            for team in (home_team, away_team):
                season_team_key = (season.id, team.id)
                if season_team_key not in existing_season_team_keys:
                    session.add(
                        SeasonTeam(season_id=season.id, team_id=team.id, source=SOURCE_LABEL)
                    )
                    existing_season_team_keys.add(season_team_key)

            match_key = (season.id, parsed.matchday, home_team.id, away_team.id, 1)
            if match_key in existing_match_keys:
                summary.matches_skipped_existing += 1
                continue

            session.add(
                Match(
                    season_id=season.id,
                    matchday=parsed.matchday,
                    scheduled_at=parsed.scheduled_at,
                    home_team_id=home_team.id,
                    away_team_id=away_team.id,
                    venue_id=venue.id,
                    status="finished",
                    # The dataset does not distinguish administrative results (W.O.) from
                    # played matches. Known limitation, to revisit in Fase 4 (data quality).
                    result_type="played",
                    leg=1,
                    home_score=parsed.home_score,
                    away_score=parsed.away_score,
                )
            )
            existing_match_keys.add(match_key)
            summary.matches_created += 1

        session.commit()

    return summary


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Bootstrap historical Brasileirão match data from the "
            "adaoduque/Brasileirao_Dataset GitHub CSV."
        )
    )
    parser.add_argument(
        "--csv-url",
        default=MATCHES_CSV_URL,
        help="Override the matches CSV source (URL or local file path).",
    )
    args = parser.parse_args()

    setup_logging(Settings().log_level)

    confirm_statistics_csv_available()

    summary = import_historical_data(args.csv_url, default_engine)

    logger.info(
        "Bootstrap import finished: %d seasons created, %d teams created, %d venues "
        "created, %d matches created, %d matches already existed (skipped), %d rows "
        "processed, %d rows excluded (current season), %d warnings.",
        summary.seasons_created,
        summary.teams_created,
        summary.venues_created,
        summary.matches_created,
        summary.matches_skipped_existing,
        summary.rows_processed,
        summary.rows_excluded_current_season,
        len(summary.warnings),
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())
