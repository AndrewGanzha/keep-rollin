from __future__ import annotations

import threading

from src.application.services.rate_limit import SlidingWindowRateLimiter


class FakeClock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


def test_limit_blocks_and_retry_after_expires() -> None:
    clock = FakeClock()
    limiter = SlidingWindowRateLimiter(limit=2, window_seconds=60, clock=clock)
    assert limiter.hit("a") is None
    clock.now += 10
    assert limiter.hit("a") is None
    assert limiter.hit("a") == 50
    clock.now += 50
    assert limiter.hit("a") is None


def test_keys_are_independent() -> None:
    clock = FakeClock()
    limiter = SlidingWindowRateLimiter(limit=1, window_seconds=60, clock=clock)
    assert limiter.hit("tenant-a:email") is None
    assert limiter.hit("tenant-b:email") is None
    assert limiter.hit("tenant-a:email") == 60
    assert limiter.hit("tenant-a:other") is None


def test_capacity_does_not_evict_active_bucket() -> None:
    clock = FakeClock()
    limiter = SlidingWindowRateLimiter(limit=5, window_seconds=60, max_keys=2, clock=clock)
    assert limiter.hit("active-1") is None
    assert limiter.hit("active-2") is None
    # A third active key is rejected instead of silently resetting an
    # existing bucket that is still inside its window.
    assert limiter.hit("new") == 60
    assert limiter.hit("active-1") is None
    assert limiter.hit("active-2") is None


def test_expired_buckets_are_reclaimed_at_capacity() -> None:
    clock = FakeClock()
    limiter = SlidingWindowRateLimiter(limit=5, window_seconds=60, max_keys=2, clock=clock)
    assert limiter.hit("old-1") is None
    assert limiter.hit("old-2") is None
    clock.now += 61
    assert limiter.hit("new") is None


def test_thread_safe_hits_do_not_exceed_limit() -> None:
    limiter = SlidingWindowRateLimiter(limit=50, window_seconds=60)
    results: list[int | None] = []
    lock = threading.Lock()

    def hit() -> None:
        result = limiter.hit("shared")
        with lock:
            results.append(result)

    threads = [threading.Thread(target=hit) for _ in range(100)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sum(result is None for result in results) == 50
    assert sum(result is not None for result in results) == 50
