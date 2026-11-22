import asyncio
import time
from typing import cast

import asyncpg
import pytest

from app.db import database_ready


def test_database_ready_without_dsn() -> None:
    assert asyncio.run(database_ready(None, 0.1)) is False


def test_database_ready_enforces_one_overall_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def hanging_connect(*args: object, **kwargs: object) -> None:
        await asyncio.sleep(10)

    monkeypatch.setattr(asyncpg, "connect", hanging_connect)
    started = time.monotonic()

    result = asyncio.run(database_ready("postgresql://127.0.0.1:1/keep_rollin", 0.1))

    assert result is False
    assert time.monotonic() - started < 1.0


async def test_database_ready_times_out_against_silent_server() -> None:
    stop = asyncio.Event()

    async def silent_handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await stop.wait()
        writer.close()

    server = await asyncio.start_server(silent_handler, "127.0.0.1", 0)
    assert server.sockets is not None
    port = server.sockets[0].getsockname()[1]
    started = time.monotonic()

    try:
        result = await database_ready(
            f"postgresql://postgres@127.0.0.1:{port}/keep_rollin",
            0.2,
        )
    finally:
        stop.set()
        server.close()
        await server.wait_closed()

    assert result is False
    assert time.monotonic() - started < 1.0


async def test_database_ready_uses_one_deadline_for_connect_and_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class SlowConnection:
        async def execute(self, query: str) -> None:
            await asyncio.sleep(0.2)

        def terminate(self) -> None:
            pass

    async def slow_connect(*args: object, **kwargs: object) -> asyncpg.Connection:
        await asyncio.sleep(0.2)
        return cast(asyncpg.Connection, SlowConnection())

    monkeypatch.setattr(asyncpg, "connect", slow_connect)
    started = time.monotonic()

    result = await database_ready("postgresql://127.0.0.1:1/keep_rollin", 0.3)

    assert result is False
    assert time.monotonic() - started < 0.6


async def test_cancellation_terminates_an_open_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = asyncio.Event()

    class HangingConnection:
        terminated = False

        async def execute(self, query: str) -> None:
            started.set()
            await asyncio.sleep(10)

        def terminate(self) -> None:
            self.terminated = True

    connection = HangingConnection()

    async def connect_to_hanging_server(*args: object, **kwargs: object) -> asyncpg.Connection:
        return cast(asyncpg.Connection, connection)

    monkeypatch.setattr(asyncpg, "connect", connect_to_hanging_server)
    task = asyncio.create_task(database_ready("postgresql://127.0.0.1:1/keep_rollin", 10))
    await started.wait()
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    assert connection.terminated is True


async def test_database_ready_handles_an_unsupported_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def unsupported_connect(*args: object, **kwargs: object) -> None:
        raise NotImplementedError

    monkeypatch.setattr(asyncpg, "connect", unsupported_connect)

    result = await database_ready("postgresql://postgres@/keep_rollin", 0.1)

    assert result is False
