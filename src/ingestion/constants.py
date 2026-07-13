"""Shared constants for external data source ingestion."""

# API-Football (v3.football.api-sports.io) league ID for Campeonato Brasileiro Série A.
# Confirmed on 2026-07-13 via a single real call to GET /leagues?country=Brazil (Paso 2.3) —
# the response entry with league.name == "Serie A" has league.id == 71. Not assumed from
# memory: API-Football's numeric league IDs are provider-specific and unrelated to
# football-data.org's "BSA" competition code used in Paso 2.2.
BSA_API_FOOTBALL_LEAGUE_ID = 71
