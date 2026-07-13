"""Generic sliding-window rate limiter, shared by every external API client."""

from __future__ import annotations

import logging
import time
from collections import deque

logger = logging.getLogger(__name__)


class RateLimiter:
    """Blocks callers so that at most `max_calls` happen within any `period_seconds` window."""

    def __init__(self, max_calls: int, period_seconds: int) -> None:
        self.max_calls = max_calls
        self.period_seconds = period_seconds
        self._call_timestamps: deque[float] = deque()

    def wait_if_needed(self) -> None:
        now = time.monotonic()
        self._evict_expired(now)

        if len(self._call_timestamps) >= self.max_calls:
            oldest_call = self._call_timestamps[0]
            wait_seconds = self.period_seconds - (now - oldest_call)
            if wait_seconds > 0:
                logger.debug(
                    "Rate limit reached (%d calls / %ds window), waiting %.2fs",
                    self.max_calls,
                    self.period_seconds,
                    wait_seconds,
                )
                time.sleep(wait_seconds)
            now = time.monotonic()
            self._evict_expired(now)

        self._call_timestamps.append(now)

    def _evict_expired(self, now: float) -> None:
        while self._call_timestamps and now - self._call_timestamps[0] >= self.period_seconds:
            self._call_timestamps.popleft()
