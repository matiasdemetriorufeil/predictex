import pytest

from src.data import schema_validation
from src.db import engine


@pytest.mark.integration
def test_validate_schema_passes_on_real_database():
    report = schema_validation.validate_schema(engine)

    assert report.passed is True
    assert report.checks_run > 0
    assert report.errors == []


@pytest.mark.integration
def test_validate_schema_detects_missing_table(monkeypatch):
    monkeypatch.setattr(
        schema_validation,
        "EXPECTED_TABLES",
        (*schema_validation.EXPECTED_TABLES, "this_table_does_not_exist"),
    )

    report = schema_validation.validate_schema(engine)

    assert report.passed is False
    assert any("this_table_does_not_exist" in error for error in report.errors)


@pytest.mark.integration
def test_validate_schema_detects_unexpected_column(monkeypatch):
    bogus_columns = {
        **schema_validation.EXPECTED_COLUMNS,
        "teams": (
            *schema_validation.EXPECTED_COLUMNS["teams"],
            ("this_column_does_not_exist", False),
        ),
    }
    monkeypatch.setattr(schema_validation, "EXPECTED_COLUMNS", bogus_columns)

    report = schema_validation.validate_schema(engine)

    assert report.passed is False
    assert any("this_column_does_not_exist" in error for error in report.errors)
