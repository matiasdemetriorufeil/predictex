"""HTTP client for API-Football / API-Sports (v3.football.api-sports.io).

Confirmed for Paso 2.3 with a real call against GET /leagues?country=Brazil:
  - Auth via the `x-apisports-key` header.
  - Per-minute limit reported via `x-ratelimit-limit` / `x-ratelimit-remaining`
    (free tier: 10/min — reuses the same `RateLimiter` shape as Paso 2.2).
  - Per-day quota reported via `x-ratelimit-requests-limit` /
    `x-ratelimit-requests-remaining` (free tier: 100/day — tracked by `DailyQuotaGuard`).
"""

from __future__ import annotations

import logging
import time
from types import TracebackType

import httpx

from src.config import Settings
from src.exceptions import ExternalAPIError, RateLimitExceededError
from src.ingestion.quota_guard import DailyQuotaGuard
from src.ingestion.rate_limiter import RateLimiter

logger = logging.getLogger(__name__)

BASE_URL = "https://v3.football.api-sports.io"

PER_MINUTE_MAX_CALLS = 10
PER_MINUTE_PERIOD_SECONDS = 60
DAILY_QUOTA_REMAINING_HEADER = "x-ratelimit-requests-remaining"
DAILY_SAFETY_BUFFER = 10

MAX_ATTEMPTS = 3
RETRY_BACKOFF_SECONDS = 2.0


class APIFootballClient:
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = BASE_URL,
        daily_safety_buffer: int = DAILY_SAFETY_BUFFER,
    ) -> None:
        self.api_key = api_key or Settings().api_football_key
        self.rate_limiter = RateLimiter(
            max_calls=PER_MINUTE_MAX_CALLS, period_seconds=PER_MINUTE_PERIOD_SECONDS
        )
        self.quota_guard = DailyQuotaGuard(safety_buffer=daily_safety_buffer)
        self._client = httpx.Client(
            base_url=base_url, headers={"x-apisports-key": self.api_key}, timeout=30.0
        )

    def get_teams(self, league_id: int, season: int) -> list[dict]:
        """Return all teams for a league's season in a single call (not per-team)."""
        payload = self._request("/teams", params={"league": league_id, "season": season})
        return payload.get("response", [])

    def get_team_statistics(self, league_id: int, season: int, team_id: int) -> dict:
        """Return aggregated season statistics for a single team (one call per team)."""
        payload = self._request(
            "/teams/statistics",
            params={"league": league_id, "season": season, "team": team_id},
        )
        return payload.get("response", {})

    def _request(self, path: str, params: dict) -> dict:
        self.quota_guard.check_before_request()

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
                    f"Network error calling API-Football {path}",
                    context={"path": path, "params": params, "error": str(exc)},
                ) from exc
            else:
                if response.status_code == 429:
                    # Never retried automatically - don't keep burning quota once exceeded.
                    raise RateLimitExceededError(
                        "API-Football rate limit exceeded",
                        context={"path": path, "status_code": 429, "body": response.text},
                    )

                if response.status_code >= 500:
                    if attempt < MAX_ATTEMPTS:
                        wait_seconds = RETRY_BACKOFF_SECONDS * attempt
                        logger.warning(
                            "API-Football server error %d calling %s "
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
                        f"API-Football server error {response.status_code}",
                        context={
                            "path": path,
                            "status_code": response.status_code,
                            "body": response.text,
                        },
                    )

                if response.status_code >= 400:
                    raise ExternalAPIError(
                        f"API-Football client error {response.status_code}",
                        context={
                            "path": path,
                            "status_code": response.status_code,
                            "body": response.text,
                        },
                    )

                remaining_header = response.headers.get(DAILY_QUOTA_REMAINING_HEADER)
                if remaining_header is not None:
                    self.quota_guard.update_from_remaining(int(remaining_header))

                payload = response.json()
                # API-Football can return HTTP 200 with an application-level error body
                # (e.g. invalid parameters) - surface those instead of an empty response.
                errors = payload.get("errors")
                if errors:
                    raise ExternalAPIError(
                        f"API-Football returned application-level errors for {path}",
                        context={"path": path, "params": params, "errors": errors},
                    )

                return payload

        raise ExternalAPIError("API-Football request failed after retries", context={"path": path})

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> APIFootballClient:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()
