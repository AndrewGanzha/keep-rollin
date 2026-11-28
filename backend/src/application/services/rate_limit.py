from __future__ import annotations

import math
import threading
import time
from collections import OrderedDict, deque
from collections.abc import Callable


class SlidingWindowRateLimiter:
    """Thread-safe in-process sliding window limiter with bounded key storage."""

    def __init__(
        self,
        *,
        limit: int,
        window_seconds: int,
        max_keys: int = 10_000,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if limit < 1 or window_seconds < 1 or max_keys < 1:
            raise ValueError("rate limiter settings must be positive")
        self._limit = limit
        self._window = float(window_seconds)
        self._max_keys = max_keys
        self._clock = clock
        self._events: OrderedDict[str, deque[float]] = OrderedDict()
        self._lock = threading.Lock()

    def hit(self, key: str) -> int | None:
        """Record an attempt. Return Retry-After seconds when the limit is hit."""
        now = self._clock()
        with self._lock:
            events = self._events.get(key)
            if events is None:
                self._prune_expired(now)
                if len(self._events) >= self._max_keys:
                    return max(1, math.ceil(self._window))
                events = deque()
                self._events[key] = events
            else:
                self._events.move_to_end(key)
            cutoff = now - self._window
            while events and events[0] <= cutoff:
                events.popleft()
            if len(events) >= self._limit:
                retry_after = max(1, math.ceil(events[0] + self._window - now))
                return retry_after
            events.append(now)
            return None

    def _prune_expired(self, now: float) -> None:
        cutoff = now - self._window
        for key in list(self._events):
            events = self._events[key]
            while events and events[0] <= cutoff:
                events.popleft()
            if not events:
                del self._events[key]

    def reset(self) -> None:
        with self._lock:
            self._events.clear()
