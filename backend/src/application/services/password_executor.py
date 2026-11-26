"""Bounded execution of CPU-heavy password hashing work."""

import asyncio
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from weakref import WeakKeyDictionary

from src.domain.entities.user_account import AuthBusyError

_PASSWORD_WORKERS = 2
_PASSWORD_SEMAPHORES: WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Semaphore] = (
    WeakKeyDictionary()
)
_PASSWORD_EXECUTOR = ThreadPoolExecutor(
    max_workers=_PASSWORD_WORKERS,
    thread_name_prefix="password-hash",
)


def _semaphore_for_running_loop() -> asyncio.Semaphore:
    loop = asyncio.get_running_loop()
    semaphore = _PASSWORD_SEMAPHORES.get(loop)
    if semaphore is None:
        semaphore = asyncio.Semaphore(_PASSWORD_WORKERS)
        _PASSWORD_SEMAPHORES[loop] = semaphore
    return semaphore


async def run_password_work[T](
    operation: Callable[[], T],
    *,
    timeout_seconds: float,
) -> T:
    """Run password work with a bounded wait instead of an unbounded queue."""
    semaphore = _semaphore_for_running_loop()
    try:
        await asyncio.wait_for(semaphore.acquire(), timeout=timeout_seconds)
    except TimeoutError as exc:
        raise AuthBusyError("password work capacity is saturated") from exc
    future = asyncio.get_running_loop().run_in_executor(_PASSWORD_EXECUTOR, operation)
    try:
        result = await asyncio.shield(future)
    except asyncio.CancelledError:
        future.add_done_callback(lambda _: semaphore.release())
        raise
    except BaseException:
        semaphore.release()
        raise
    else:
        semaphore.release()
        return result
