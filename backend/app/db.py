import asyncio
import contextlib

import asyncpg


async def database_ready(dsn: str | None, timeout_seconds: float) -> bool:
    """Return True when a real SELECT 1 succeeds within one overall deadline."""
    if not dsn:
        return False

    connection: asyncpg.Connection | None = None
    try:
        async with asyncio.timeout(timeout_seconds):
            connection = await asyncpg.connect(dsn, timeout=timeout_seconds)
            await connection.execute("SELECT 1")
    except Exception:
        # Readiness fails closed for every driver or transport error. CancelledError
        # is a BaseException and still propagates to the caller.
        return False
    finally:
        if connection is not None:
            with contextlib.suppress(Exception):
                connection.terminate()

    return True
