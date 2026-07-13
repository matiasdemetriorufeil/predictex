import pytest

from src.db import engine
from src.ingestion.bootstrap_historical import import_historical_data

FIXTURE_PATH = "tests/fixtures/sample_matches.csv"


@pytest.mark.integration
def test_import_handles_missing_score_as_warning_not_crash():
    summary = import_historical_data(FIXTURE_PATH, engine)

    assert summary.rows_processed == 90
    assert any("ID=11" in warning and "score" in warning for warning in summary.warnings), (
        summary.warnings
    )


@pytest.mark.integration
def test_import_is_idempotent_on_second_run():
    import_historical_data(FIXTURE_PATH, engine)
    second_run = import_historical_data(FIXTURE_PATH, engine)

    assert second_run.matches_created == 0
    assert second_run.seasons_created == 0
    assert second_run.teams_created == 0
    assert second_run.venues_created == 0
    # 90 rows in the fixture, one has a missing score and is skipped as malformed on
    # every run; the other 89 must all be recognized as already-imported this time.
    assert second_run.matches_skipped_existing == 89
