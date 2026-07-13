import datetime

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.data.models import Match, Season, SeasonTeam, Team, Venue
from src.db import engine


@pytest.fixture
def db_session():
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection)
    try:
        yield session
    finally:
        session.close()
        if transaction.is_active:
            transaction.rollback()
        connection.close()


@pytest.fixture
def sample_entities(db_session):
    season = Season(year=2099, start_date=datetime.date(2099, 4, 1), status="in_progress")
    venue = Venue(name="Test Arena", city="Test City")
    home_team = Team(official_name="Home FC", short_name="Home", city="Home City")
    away_team = Team(official_name="Away FC", short_name="Away", city="Away City")
    db_session.add_all([season, venue, home_team, away_team])
    db_session.flush()
    return season, venue, home_team, away_team


@pytest.mark.integration
def test_insert_and_read_match_with_relationships(db_session, sample_entities):
    season, venue, home_team, away_team = sample_entities

    match = Match(
        season_id=season.id,
        matchday=1,
        scheduled_at=datetime.datetime(2099, 4, 5, 20, 0, tzinfo=datetime.UTC),
        home_team_id=home_team.id,
        away_team_id=away_team.id,
        venue_id=venue.id,
    )
    season_team = SeasonTeam(season_id=season.id, team_id=home_team.id)
    db_session.add_all([match, season_team])
    db_session.flush()
    db_session.expire_all()

    fetched = db_session.get(Match, match.id)

    assert fetched is not None
    assert fetched.home_team.short_name == "Home"
    assert fetched.away_team.short_name == "Away"
    assert fetched.season.year == 2099
    assert fetched.venue.name == "Test Arena"
    assert fetched.status == "scheduled"
    assert fetched.result_type == "played"
    assert fetched.leg == 1


@pytest.mark.integration
def test_unique_constraint_rejects_duplicate_match(db_session, sample_entities):
    season, _venue, home_team, away_team = sample_entities
    scheduled_at = datetime.datetime(2099, 4, 5, 20, 0, tzinfo=datetime.UTC)

    db_session.add(
        Match(
            season_id=season.id,
            matchday=1,
            scheduled_at=scheduled_at,
            home_team_id=home_team.id,
            away_team_id=away_team.id,
        )
    )
    db_session.flush()

    db_session.add(
        Match(
            season_id=season.id,
            matchday=1,
            scheduled_at=scheduled_at,
            home_team_id=home_team.id,
            away_team_id=away_team.id,
        )
    )
    with pytest.raises(IntegrityError):
        db_session.flush()


@pytest.mark.integration
def test_check_constraint_rejects_team_playing_itself(db_session, sample_entities):
    season, _venue, home_team, _away_team = sample_entities

    db_session.add(
        Match(
            season_id=season.id,
            matchday=1,
            scheduled_at=datetime.datetime(2099, 4, 5, 20, 0, tzinfo=datetime.UTC),
            home_team_id=home_team.id,
            away_team_id=home_team.id,
        )
    )
    with pytest.raises(IntegrityError):
        db_session.flush()
