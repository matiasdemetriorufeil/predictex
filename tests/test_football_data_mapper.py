import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.data.models import MatchExternalId
from src.db import engine
from src.ingestion.football_data_mapper import SOURCE, import_matches

# Uses a synthetic season year so these tests never collide with real bootstrap (2003-2024),
# football-data.org (2025+), or test_models.py's own synthetic year (2099) in the shared dev DB.
TEST_SEASON_YEAR = 2100


def _unique_external_id() -> int:
    # Always novel, so re-running the suite against the same persistent dev DB doesn't turn a
    # "create" into an "update" from a previous run.
    return uuid.uuid4().int % 900_000_000 + 100_000_000


def _make_match(status: str, home_score: int | None = None, away_score: int | None = None) -> dict:
    suffix = uuid.uuid4().hex[:8]
    return {
        "id": _unique_external_id(),
        "utcDate": "2100-05-01T20:00:00Z",
        "status": status,
        "matchday": 1,
        "venue": f"Test Arena {suffix}",
        "homeTeam": {"id": _unique_external_id(), "name": f"FC Test Home {suffix}"},
        "awayTeam": {"id": _unique_external_id(), "name": f"FC Test Away {suffix}"},
        "score": {"fullTime": {"home": home_score, "away": away_score}},
    }


@pytest.mark.integration
def test_import_matches_upserts_same_match_on_second_run():
    scheduled_match = _make_match("SCHEDULED")
    external_id = str(scheduled_match["id"])

    first_run = import_matches([scheduled_match], TEST_SEASON_YEAR, engine)
    assert first_run.matches_created == 1
    assert first_run.matches_updated == 0

    finished_match = {
        **scheduled_match,
        "status": "FINISHED",
        "score": {"fullTime": {"home": 3, "away": 1}},
    }
    second_run = import_matches([finished_match], TEST_SEASON_YEAR, engine)
    assert second_run.matches_created == 0
    assert second_run.matches_updated == 1

    with Session(engine) as session:
        link = session.execute(
            select(MatchExternalId).where(
                MatchExternalId.source == SOURCE, MatchExternalId.external_id == external_id
            )
        ).scalar_one()
        match = link.match
        assert match.status == "finished"
        assert match.home_score == 3
        assert match.away_score == 1


@pytest.mark.integration
def test_import_matches_creates_team_and_warns_when_name_unmatched():
    match = _make_match("SCHEDULED")
    home_team_name = match["homeTeam"]["name"]

    summary = import_matches([match], TEST_SEASON_YEAR, engine)

    assert summary.teams_created == 2  # both home and away are brand-new synthetic teams
    assert any(home_team_name in warning for warning in summary.unmatched_team_warnings)
