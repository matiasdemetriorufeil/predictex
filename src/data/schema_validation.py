"""Standalone schema health check against a real PostgreSQL database.

Queries `information_schema` directly (never SQLAlchemy metadata/reflection of our own
models) so it verifies what is actually in the database, not what the ORM thinks should be
there. Intended to run manually or in CI/CD before Fase 2 ingestion starts.

Usage:
    uv run python -m src.data.schema_validation
"""

from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import dataclass, field

from sqlalchemy import Engine, text

from src.config import Settings
from src.db import engine as default_engine
from src.logging_config import setup_logging

logger = logging.getLogger(__name__)

SCHEMA = "public"

EXPECTED_TABLES: tuple[str, ...] = (
    "teams",
    "seasons",
    "venues",
    "matches",
    "season_teams",
    "team_external_ids",
    "match_external_ids",
    "team_season_stats_raw",
)

# (column_name, nullable) per table, matching docs/schema_core.md.
EXPECTED_COLUMNS: dict[str, tuple[tuple[str, bool], ...]] = {
    "teams": (
        ("id", False),
        ("official_name", False),
        ("short_name", False),
        ("city", True),
        ("state", True),
        ("founded_year", True),
        ("home_venue_id", True),
    ),
    "seasons": (
        ("id", False),
        ("year", False),
        ("start_date", False),
        ("end_date", True),
        ("status", False),
    ),
    "venues": (
        ("id", False),
        ("name", False),
        ("city", True),
        ("capacity", True),
        ("latitude", True),
        ("longitude", True),
        ("altitude_meters", True),
    ),
    "season_teams": (
        ("id", False),
        ("season_id", False),
        ("team_id", False),
        ("confirmed_at", True),
        ("source", True),
    ),
    "matches": (
        ("id", False),
        ("season_id", False),
        ("matchday", False),
        ("scheduled_at", False),
        ("home_team_id", False),
        ("away_team_id", False),
        ("venue_id", True),
        ("status", False),
        ("result_type", False),
        ("leg", False),
        ("replay_of_match_id", True),
        ("home_score", True),
        ("away_score", True),
    ),
    "team_external_ids": (
        ("id", False),
        ("team_id", False),
        ("source", False),
        ("external_id", False),
    ),
    "match_external_ids": (
        ("id", False),
        ("match_id", False),
        ("source", False),
        ("external_id", False),
    ),
    "team_season_stats_raw": (
        ("id", False),
        ("team_id", False),
        ("season_id", False),
        ("source", False),
        ("raw_json", False),
        ("fetched_at", False),
    ),
}

# (column_name, ref_table, ref_column) per table.
EXPECTED_FOREIGN_KEYS: dict[str, tuple[tuple[str, str, str], ...]] = {
    "teams": (("home_venue_id", "venues", "id"),),
    "season_teams": (
        ("season_id", "seasons", "id"),
        ("team_id", "teams", "id"),
    ),
    "matches": (
        ("season_id", "seasons", "id"),
        ("home_team_id", "teams", "id"),
        ("away_team_id", "teams", "id"),
        ("venue_id", "venues", "id"),
        ("replay_of_match_id", "matches", "id"),
    ),
    "team_external_ids": (("team_id", "teams", "id"),),
    "match_external_ids": (("match_id", "matches", "id"),),
    "team_season_stats_raw": (
        ("team_id", "teams", "id"),
        ("season_id", "seasons", "id"),
    ),
}

# Sets of columns covered by a UNIQUE constraint, per table.
EXPECTED_UNIQUE_CONSTRAINTS: dict[str, tuple[frozenset[str], ...]] = {
    "seasons": (frozenset({"year"}),),
    "season_teams": (frozenset({"season_id", "team_id"}),),
    "matches": (frozenset({"season_id", "matchday", "home_team_id", "away_team_id", "leg"}),),
    "team_external_ids": (
        frozenset({"team_id", "source"}),
        frozenset({"source", "external_id"}),
    ),
    "match_external_ids": (
        frozenset({"match_id", "source"}),
        frozenset({"source", "external_id"}),
    ),
    "team_season_stats_raw": (frozenset({"team_id", "season_id", "source"}),),
}


@dataclass
class ValidationReport:
    passed: bool = True
    checks_run: int = 0
    errors: list[str] = field(default_factory=list)

    def add_error(self, message: str) -> None:
        self.errors.append(message)
        self.passed = False

    def record_check(self) -> None:
        self.checks_run += 1


def _fetch_existing_tables(conn) -> set[str]:
    rows = conn.execute(
        text(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = :schema AND table_type = 'BASE TABLE'"
        ),
        {"schema": SCHEMA},
    )
    return {row[0] for row in rows}


def _fetch_columns(conn, table_name: str) -> dict[str, bool]:
    rows = conn.execute(
        text(
            "SELECT column_name, is_nullable FROM information_schema.columns "
            "WHERE table_schema = :schema AND table_name = :table_name"
        ),
        {"schema": SCHEMA, "table_name": table_name},
    )
    return {row[0]: row[1] == "YES" for row in rows}


def _fetch_foreign_keys(conn, table_name: str) -> list[tuple[str, str, str]]:
    rows = conn.execute(
        text(
            """
            SELECT kcu.column_name, ccu.table_name AS ref_table, ccu.column_name AS ref_column
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
                ON tc.constraint_name = kcu.constraint_name
                AND tc.table_schema = kcu.table_schema
            JOIN information_schema.constraint_column_usage ccu
                ON ccu.constraint_name = tc.constraint_name
                AND ccu.table_schema = tc.table_schema
            WHERE tc.constraint_type = 'FOREIGN KEY'
                AND tc.table_schema = :schema
                AND tc.table_name = :table_name
            """
        ),
        {"schema": SCHEMA, "table_name": table_name},
    )
    return [(row[0], row[1], row[2]) for row in rows]


def _fetch_unique_constraints(conn, table_name: str) -> list[frozenset[str]]:
    rows = conn.execute(
        text(
            """
            SELECT tc.constraint_name, kcu.column_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
                ON tc.constraint_name = kcu.constraint_name
                AND tc.table_schema = kcu.table_schema
            WHERE tc.constraint_type = 'UNIQUE'
                AND tc.table_schema = :schema
                AND tc.table_name = :table_name
            """
        ),
        {"schema": SCHEMA, "table_name": table_name},
    )
    columns_by_constraint: dict[str, set[str]] = {}
    for constraint_name, column_name in rows:
        columns_by_constraint.setdefault(constraint_name, set()).add(column_name)
    return [frozenset(columns) for columns in columns_by_constraint.values()]


def _fetch_check_clauses(conn, table_name: str) -> list[str]:
    rows = conn.execute(
        text(
            """
            SELECT cc.check_clause
            FROM information_schema.table_constraints tc
            JOIN information_schema.check_constraints cc
                ON tc.constraint_name = cc.constraint_name
                AND tc.constraint_schema = cc.constraint_schema
            WHERE tc.constraint_type = 'CHECK'
                AND tc.table_schema = :schema
                AND tc.table_name = :table_name
            """
        ),
        {"schema": SCHEMA, "table_name": table_name},
    )
    return [row[0] for row in rows]


def _check_tables_exist(conn, report: ValidationReport) -> set[str]:
    existing_tables = _fetch_existing_tables(conn)
    for table_name in EXPECTED_TABLES:
        report.record_check()
        if table_name not in existing_tables:
            report.add_error(f"expected table '{table_name}' to exist, but it was not found")
    return existing_tables & set(EXPECTED_TABLES)


def _check_columns(conn, table_name: str, report: ValidationReport) -> None:
    actual_columns = _fetch_columns(conn, table_name)
    for column_name, expected_nullable in EXPECTED_COLUMNS.get(table_name, ()):
        report.record_check()
        if column_name not in actual_columns:
            report.add_error(
                f"expected column '{table_name}.{column_name}' to exist, but it was not found"
            )
            continue
        actual_nullable = actual_columns[column_name]
        if actual_nullable != expected_nullable:
            report.add_error(
                f"expected '{table_name}.{column_name}' to be "
                f"{'nullable' if expected_nullable else 'NOT NULL'}, "
                f"but found {'nullable' if actual_nullable else 'NOT NULL'}"
            )


def _check_foreign_keys(conn, table_name: str, report: ValidationReport) -> None:
    actual_fks = _fetch_foreign_keys(conn, table_name)
    for column_name, ref_table, ref_column in EXPECTED_FOREIGN_KEYS.get(table_name, ()):
        report.record_check()
        match = next((fk for fk in actual_fks if fk[0] == column_name), None)
        if match is None:
            report.add_error(
                f"expected foreign key on '{table_name}.{column_name}' "
                f"-> '{ref_table}.{ref_column}', but no foreign key was found on that column"
            )
        elif (match[1], match[2]) != (ref_table, ref_column):
            report.add_error(
                f"expected foreign key on '{table_name}.{column_name}' to reference "
                f"'{ref_table}.{ref_column}', but it references '{match[1]}.{match[2]}'"
            )


def _check_unique_constraints(conn, table_name: str, report: ValidationReport) -> None:
    actual_unique_sets = _fetch_unique_constraints(conn, table_name)
    for expected_columns in EXPECTED_UNIQUE_CONSTRAINTS.get(table_name, ()):
        report.record_check()
        if expected_columns not in actual_unique_sets:
            columns_repr = ", ".join(sorted(expected_columns))
            report.add_error(
                f"expected a UNIQUE constraint on '{table_name}' covering columns "
                f"({columns_repr}), but no such constraint was found"
            )


def _check_matches_home_away_check_constraint(conn, report: ValidationReport) -> None:
    report.record_check()
    check_clauses = _fetch_check_clauses(conn, "matches")
    has_home_away_check = any(
        "home_team_id" in clause and "away_team_id" in clause and ("<>" in clause or "!=" in clause)
        for clause in check_clauses
    )
    if not has_home_away_check:
        report.add_error(
            "expected a CHECK constraint on 'matches' enforcing home_team_id <> away_team_id, "
            f"but none of the existing CHECK constraints matched (found: {check_clauses!r})"
        )


def validate_schema(engine: Engine) -> ValidationReport:
    """Validate the real database schema against docs/schema_core.md.

    Queries `information_schema` directly against the given engine — it does not rely on
    SQLAlchemy model metadata, so it also catches drift between the ORM models and what was
    actually applied to the database (e.g. a migration that was never run).
    """
    report = ValidationReport()

    with engine.connect() as conn:
        existing_expected_tables = _check_tables_exist(conn, report)

        for table_name in sorted(existing_expected_tables):
            _check_columns(conn, table_name, report)
            _check_foreign_keys(conn, table_name, report)
            _check_unique_constraints(conn, table_name, report)

        if "matches" in existing_expected_tables:
            _check_matches_home_away_check_constraint(conn, report)

    return report


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Validate that the real database schema matches docs/schema_core.md "
            "before starting data ingestion."
        )
    )
    parser.parse_args()

    setup_logging(Settings().log_level)

    report = validate_schema(default_engine)

    if report.passed:
        logger.info("Schema validation PASSED (%d checks run).", report.checks_run)
    else:
        logger.error(
            "Schema validation FAILED (%d checks run, %d errors):",
            report.checks_run,
            len(report.errors),
        )
        for error_message in report.errors:
            logger.error("  - %s", error_message)

    return 0 if report.passed else 1


if __name__ == "__main__":
    sys.exit(main())
