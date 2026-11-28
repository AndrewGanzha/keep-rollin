import asyncio
from typing import cast

import anyio
from sqlalchemy.ext.asyncio import AsyncSession

from app.middleware import rollback_and_close


class SlowSession:
    def __init__(self) -> None:
        self.rolled_back = False
        self.closed = False
        self.started = asyncio.Event()

    async def rollback(self) -> None:
        self.started.set()
        await asyncio.sleep(0.05)
        self.rolled_back = True

    async def close(self) -> None:
        await asyncio.sleep(0.05)
        self.closed = True


async def test_rollback_and_close_survives_anyio_cancellation() -> None:
    session = SlowSession()

    async with anyio.create_task_group() as task_group:
        task_group.start_soon(rollback_and_close, cast(AsyncSession, session))
        await session.started.wait()
        task_group.cancel_scope.cancel()

    assert session.rolled_back is True
    assert session.closed is True
