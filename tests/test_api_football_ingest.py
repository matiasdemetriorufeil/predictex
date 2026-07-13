import uuid
from datetime import date

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.data.models import Season, Team, TeamExternalId, TeamSeasonStatsRaw
from src.db import engine
from src.exceptions import DataValidationError
from src.ingestion.api_football_ingest import SOURCE, ingest_team_season_stats

# Synthetic season years distinct from real data (2003-2026) and from other tests' synthetic
# years (test_models.py uses 2099, test_football_data_mapper.py uses 2100).
TEST_SEASON_YEAR = 2101
MISSING_SEASON_YEAR = 2102


class _FakeAPIFootballClient:
    """Duck-typed stand-in for APIFootballClient - no network, canned responses."""

    def __init__(self, teams_response: list[dict], stats_by_team_id: dict[int, dict]) -> None:
        self._teams_response = teams_response
        self._stats_by_team_id = stats_by_team_id

    def get_teams(self, league_id: int, season: int) -> list[dict]:
        return self._teams_response

    def get_team_statistics(self, league_id: int, season: int, team_id: int) -> dict:
        return self._stats_by_team_id[team_id]


def _ensure_season(year: int) -> None:
    with Session(engine) as session:
        existing = session.execute(select(Season).where(Season.year == year)).scalar_one_or_none()
        if existing is None:
            session.add(Season(year=year, start_date=date(year, 4, 1), status="finished"))
            session.commit()


@pytest.mark.integration
def test_ingest_upserts_team_season_stats_idempotently():
    _ensure_season(TEST_SEASON_YEAR)
    suffix = uuid.uuid4().hex[:8]
    team_external_id = uuid.uuid4().int % 900_000_000 + 100_000_000
    team_name = f"FC Stats Test {suffix}"
    teams_response = [
        {"team": {"id": team_external_id, "name": team_name, "code": suffix[:3].upper()}}
    ]

    stats_v1 = {"form": "WWWWW", "fixtures": {"played": {"total": 10}}}
    first_client = _FakeAPIFootballClient(teams_response, {team_external_id: stats_v1})
    first_run = ingest_team_season_stats(first_client, 71, TEST_SEASON_YEAR, engine)

    assert first_run.teams_created == 1
    assert first_run.stats_created == 1
    assert first_run.stats_updated == 0

    stats_v2 = {"form": "LLLLL", "fixtures": {"played": {"total": 15}}}
    second_client = _FakeAPIFootballClient(teams_response, {team_external_id: stats_v2})
    second_run = ingest_team_season_stats(second_client, 71, TEST_SEASON_YEAR, engine)

    assert second_run.teams_created == 0  # already resolved via team_external_ids
    assert second_run.stats_created == 0
    assert second_run.stats_updated == 1

    with Session(engine) as session:
        stats_row = session.execute(
            select(TeamSeasonStatsRaw)
            .join(Team, Team.id == TeamSeasonStatsRaw.team_id)
            .join(TeamExternalId, TeamExternalId.team_id == Team.id)
            .where(
                TeamExternalId.external_id == str(team_external_id),
                TeamExternalId.source == SOURCE,
            )
        ).scalar_one()
        assert stats_row.raw_json == stats_v2


@pytest.mark.integration
def test_ingest_raises_data_validation_error_when_season_missing():
    client = _FakeAPIFootballClient([{"team": {"id": 1, "name": "Nonexistent"}}], {1: {}})

    with pytest.raises(DataValidationError):
        ingest_team_season_stats(client, 71, MISSING_SEASON_YEAR, engine)
