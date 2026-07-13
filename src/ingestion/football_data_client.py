"""HTTP client for football-data.org (v4 API).

Docs confirmed for Paso 2.2 against docs.football-data.org/general/v4/:
  - GET /v4/competitions/{code}/matches?season=YYYY returns {"matches": [...]}.
  - Auth via the `X-Auth-Token` header.
  - Free tier limit: 10 calls / 60 seconds.

Usage:
    uv run python -m src.ingestion.football_data_client --season 2025
    uv run python -m src.ingestion.football_data_client --season 2026
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from types import TracebackType

import httpx

from src.config import Settings
from src.db import engine as default_engine
from src.exceptions import ExternalAPIError, RateLimitExceededError
from src.ingestion.football_data_mapper import import_matches
from src.ingestion.rate_limiter import RateLimiter
from src.logging_config import setup_logging

logger = logging.getLogger(__name__)

BASE_URL = "https://api.football-data.org/v4"
DEFAULT_COMPETITION = "BSA"  # Campeonato Brasileiro Série A (confirmed via lookup_tables.html)

FREE_TIER_MAX_CALLS = 10
FREE_TIER_PERIOD_SECONDS = 60

MAX_ATTEMPTS = 3
RETRY_BACKOFF_SECONDS = 2.0


class FootballDataClient:
    def __init__(self, api_key: str | None = None, base_url: str = BASE_URL) -> None:
        self.api_key = api_key or Settings().football_data_api_key
        self.rate_limiter = RateLimiter(
            max_calls=FREE_TIER_MAX_CALLS, period_seconds=FREE_TIER_PERIOD_SECONDS
        )
        self._client = httpx.Client(
            base_url=base_url, headers={"X-Auth-Token": self.api_key}, timeout=30.0
        )

    def get_matches(self, competition: str, season: int) -> list[dict]:
        """Return the raw fixture/result objects for a competition's season."""
        payload = self._request(f"/competitions/{competition}/matches", params={"season": season})
        return payload.get("matches", [])

    def _request(self, path: str, params: dict) -> dict:
        for attempt in range(1, MAX_ATTEMPTS + 1):
            self.rate_limiter.wait_if_needed()
            try:
                response = self._client.get(path, params=params)
            except httpx.RequestError as exc:
                if attempt < MAX_ATTEMPTS:
                    wait_seconds = RETRY_BACKOFF_SECONDS * attempt
                    logger.warning(
                        "Network error calling %s (attempt %d/%d): %s. Retrying in %.1fs",
                        path,
                        attempt,
                        MAX_ATTEMPTS,
                        exc,
                        wait_seconds,
                    )
                    time.sleep(wait_seconds)
                    continue
                raise ExternalAPIError(
                    f"Network error calling football-data.org {path}",
                    context={"path": path, "params": params, "error": str(exc)},
                ) from exc
            else:
                if response.status_code == 429:
                    # Never retried automatically - we don't want to keep burning quota once
                    # we've already exceeded it.
                    raise RateLimitExceededError(
                        "football-data.org rate limit exceeded",
                        context={"path": path, "status_code": 429, "body": response.text},
                    )

                if response.status_code >= 500:
                    if attempt < MAX_ATTEMPTS:
                        wait_seconds = RETRY_BACKOFF_SECONDS * attempt
                        logger.warning(
                            "football-data.org server error %d calling %s "
                            "(attempt %d/%d). Retrying in %.1fs",
                            response.status_code,
                            path,
                            attempt,
                            MAX_ATTEMPTS,
                            wait_seconds,
                        )
                        time.sleep(wait_seconds)
                        continue
                    raise ExternalAPIError(
                        f"football-data.org server error {response.status_code}",
                        context={
                            "path": path,
                            "status_code": response.status_code,
                            "body": response.text,
                        },
                    )

                if response.status_code >= 400:
                    raise ExternalAPIError(
                        f"football-data.org client error {response.status_code}",
                        context={
                            "path": path,
                            "status_code": response.status_code,
                            "body": response.text,
                        },
                    )

                return response.json()

        raise ExternalAPIError(
            "football-data.org request failed after retries", context={"path": path}
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> FootballDataClient:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fetch and persist football-data.org fixtures/results for a BSA season."
    )
    parser.add_argument("--season", type=int, required=True, help="Season year, e.g. 2025.")
    parser.add_argument(
        "--competition",
        default=DEFAULT_COMPETITION,
        help=f"Competition code (default: {DEFAULT_COMPETITION}).",
    )
    args = parser.parse_args()

    setup_logging(Settings().log_level)

    with FootballDataClient() as client:
        raw_matches = client.get_matches(args.competition, args.season)

    logger.info(
        "Fetched %d raw matches for %s season %d", len(raw_matches), args.competition, args.season
    )

    summary = import_matches(raw_matches, args.season, default_engine)

    logger.info(
        "Import finished for season %d: %d matches created, %d matches updated, %d teams "
        "created, %d venues created, %d unmatched-team warnings.",
        args.season,
        summary.matches_created,
        summary.matches_updated,
        summary.teams_created,
        summary.venues_created,
        len(summary.unmatched_team_warnings),
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())
