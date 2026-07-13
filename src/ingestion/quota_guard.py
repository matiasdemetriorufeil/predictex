"""Daily request quota guard for external APIs that report a remaining-quota header.

Distinct from `RateLimiter` (rate_limiter.py): that one paces calls within a per-minute
sliding window; this one tracks a per-day cap reported by the API itself and resets at
00:00 UTC, refusing to make another call once the remaining quota drops below a safety
buffer — before the call happens, not after.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime

from src.exceptions import RateLimitExceededError

logger = logging.getLogger(__name__)

DEFAULT_SAFETY_BUFFER = 10


class DailyQuotaGuard:
    def __init__(self, safety_buffer: int = DEFAULT_SAFETY_BUFFER) -> None:
        self.safety_buffer = safety_buffer
        self._remaining: int | None = None
        self._last_seen_date: date = self._today_utc()

    @staticmethod
    def _today_utc() -> date:
        return datetime.now(UTC).date()

    def _maybe_reset_for_new_day(self) -> None:
        today = self._today_utc()
        if today != self._last_seen_date:
            logger.info(
                "Daily quota window crossed 00:00 UTC; clearing last known remaining count."
            )
            self._remaining = None
            self._last_seen_date = today

    def check_before_request(self) -> None:
        """Raise RateLimitExceededError if the last known remaining quota is too low."""
        self._maybe_reset_for_new_day()
        if self._remaining is not None and self._remaining < self.safety_buffer:
            raise RateLimitExceededError(
                "Daily API quota safety buffer reached; refusing to make another call",
                context={"remaining": self._remaining, "safety_buffer": self.safety_buffer},
            )

    def update_from_remaining(self, remaining: int) -> None:
        """Record the remaining-quota value reported by the API after a successful call."""
        self._maybe_reset_for_new_day()
        self._remaining = remaining
        logger.info("Daily API quota remaining: %d", remaining)
