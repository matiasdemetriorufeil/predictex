from __future__ import annotations

import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Numeric,
    SmallInteger,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Venue(Base):
    __tablename__ = "venues"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    capacity: Mapped[int | None] = mapped_column(nullable=True)
    latitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6), nullable=True)
    longitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6), nullable=True)
    altitude_meters: Mapped[Decimal | None] = mapped_column(Numeric(6, 1), nullable=True)

    home_teams: Mapped[list[Team]] = relationship(back_populates="home_venue")
    matches: Mapped[list[Match]] = relationship(back_populates="venue")

    def __repr__(self) -> str:
        return f"Venue(id={self.id!r}, name={self.name!r}, city={self.city!r})"


class Team(Base):
    __tablename__ = "teams"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    official_name: Mapped[str] = mapped_column(String(150), nullable=False)
    short_name: Mapped[str] = mapped_column(String(50), nullable=False)
    city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    state: Mapped[str | None] = mapped_column(String(2), nullable=True)
    founded_year: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    home_venue_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("venues.id"), nullable=True, index=True
    )

    home_venue: Mapped[Venue | None] = relationship(back_populates="home_teams")
    external_ids: Mapped[list[TeamExternalId]] = relationship(
        back_populates="team", cascade="all, delete-orphan"
    )
    season_participations: Mapped[list[SeasonTeam]] = relationship(
        back_populates="team", cascade="all, delete-orphan"
    )
    home_matches: Mapped[list[Match]] = relationship(
        foreign_keys="Match.home_team_id", back_populates="home_team"
    )
    away_matches: Mapped[list[Match]] = relationship(
        foreign_keys="Match.away_team_id", back_populates="away_team"
    )

    def __repr__(self) -> str:
        return f"Team(id={self.id!r}, short_name={self.short_name!r})"


class Season(Base):
    __tablename__ = "seasons"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    year: Mapped[int] = mapped_column(SmallInteger, nullable=False, unique=True)
    start_date: Mapped[datetime.date] = mapped_column(Date, nullable=False)
    end_date: Mapped[datetime.date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)

    matches: Mapped[list[Match]] = relationship(
        back_populates="season", cascade="all, delete-orphan"
    )
    season_teams: Mapped[list[SeasonTeam]] = relationship(
        back_populates="season", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"Season(id={self.id!r}, year={self.year!r}, status={self.status!r})"


class SeasonTeam(Base):
    __tablename__ = "season_teams"
    __table_args__ = (UniqueConstraint("season_id", "team_id", name="uq_season_teams_season_team"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    season_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("seasons.id"), nullable=False, index=True
    )
    team_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("teams.id"), nullable=False, index=True
    )
    confirmed_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    source: Mapped[str | None] = mapped_column(String(30), nullable=True)

    season: Mapped[Season] = relationship(back_populates="season_teams")
    team: Mapped[Team] = relationship(back_populates="season_participations")

    def __repr__(self) -> str:
        return f"SeasonTeam(season_id={self.season_id!r}, team_id={self.team_id!r})"


class Match(Base):
    __tablename__ = "matches"
    __table_args__ = (
        UniqueConstraint(
            "season_id",
            "matchday",
            "home_team_id",
            "away_team_id",
            "leg",
            name="uq_matches_season_matchday_teams_leg",
        ),
        CheckConstraint("home_team_id <> away_team_id", name="ck_matches_home_away_distinct"),
        CheckConstraint(
            "status IN ('scheduled', 'finished', 'postponed', 'cancelled')",
            name="ck_matches_status_valid",
        ),
        CheckConstraint(
            "result_type IN ('played', 'awarded_home', 'awarded_away', 'annulled')",
            name="ck_matches_result_type_valid",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    season_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("seasons.id"), nullable=False, index=True
    )
    matchday: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    scheduled_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    home_team_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("teams.id"), nullable=False, index=True
    )
    away_team_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("teams.id"), nullable=False, index=True
    )
    venue_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("venues.id"), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="scheduled")
    result_type: Mapped[str] = mapped_column(String(20), nullable=False, default="played")
    leg: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    replay_of_match_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("matches.id"), nullable=True, index=True
    )
    home_score: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    away_score: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)

    season: Mapped[Season] = relationship(back_populates="matches")
    home_team: Mapped[Team] = relationship(
        foreign_keys=[home_team_id], back_populates="home_matches"
    )
    away_team: Mapped[Team] = relationship(
        foreign_keys=[away_team_id], back_populates="away_matches"
    )
    venue: Mapped[Venue | None] = relationship(back_populates="matches")
    replay_of: Mapped[Match | None] = relationship(remote_side=[id], back_populates="replays")
    replays: Mapped[list[Match]] = relationship(back_populates="replay_of")
    external_ids: Mapped[list[MatchExternalId]] = relationship(
        back_populates="match", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return (
            f"Match(id={self.id!r}, season_id={self.season_id!r}, matchday={self.matchday!r}, "
            f"home_team_id={self.home_team_id!r}, away_team_id={self.away_team_id!r})"
        )


class TeamExternalId(Base):
    __tablename__ = "team_external_ids"
    __table_args__ = (
        UniqueConstraint("team_id", "source", name="uq_team_external_ids_team_source"),
        UniqueConstraint("source", "external_id", name="uq_team_external_ids_source_external_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    team_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("teams.id"), nullable=False, index=True
    )
    source: Mapped[str] = mapped_column(String(30), nullable=False)
    external_id: Mapped[str] = mapped_column(String(50), nullable=False)

    team: Mapped[Team] = relationship(back_populates="external_ids")

    def __repr__(self) -> str:
        return (
            f"TeamExternalId(team_id={self.team_id!r}, source={self.source!r}, "
            f"external_id={self.external_id!r})"
        )


class MatchExternalId(Base):
    __tablename__ = "match_external_ids"
    __table_args__ = (
        UniqueConstraint("match_id", "source", name="uq_match_external_ids_match_source"),
        UniqueConstraint("source", "external_id", name="uq_match_external_ids_source_external_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    match_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("matches.id"), nullable=False, index=True
    )
    source: Mapped[str] = mapped_column(String(30), nullable=False)
    external_id: Mapped[str] = mapped_column(String(50), nullable=False)

    match: Mapped[Match] = relationship(back_populates="external_ids")

    def __repr__(self) -> str:
        return (
            f"MatchExternalId(match_id={self.match_id!r}, source={self.source!r}, "
            f"external_id={self.external_id!r})"
        )
