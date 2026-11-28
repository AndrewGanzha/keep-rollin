import csv
from collections.abc import AsyncGenerator, AsyncIterator
from datetime import UTC, datetime
from io import StringIO
from uuid import UUID

import pytest
from starlette.requests import ClientDisconnect
from starlette.types import Message

from app.api.admin_analytics import (
    CSV_BATCH_SIZE,
    CSV_HEADERS,
    AnalyticsCSVResponse,
    rental_report,
    spreadsheet_text,
)
from src.application.dtos.analytics_dto import AnalyticsExportRow


@pytest.mark.parametrize(
    "label",
    ["=1+1", "+1+1", "-1+1", "@SUM(1)", "  =1+1", "\tplain", "\ntext", "\uff1d1+1"],
)
def test_spreadsheet_text_preserves_inert_cell(label: str) -> None:
    assert spreadsheet_text(label) == "'" + label
    assert spreadsheet_text('Город;"Спорт"') == 'Город;"Спорт"'


async def test_large_report_emits_header_before_reads_and_keeps_batches_bounded() -> None:
    count = 50_123
    generated = 0
    timestamp = datetime(2025, 10, 26, tzinfo=UTC)
    name = '=1+1;"Лот"'
    category = "\r\n".join(("Категория", "Вторая строка"))

    async def rows() -> AsyncIterator[AnalyticsExportRow]:
        nonlocal generated
        for index in range(count):
            generated += 1
            yield AnalyticsExportRow(
                id=UUID(int=index),
                lot_name=name,
                category_name=category,
                start_time=timestamp,
                end_time=timestamp,
                status="completed",
                price_minor=42,
                currency="RUB",
            )

    report = rental_report(rows())
    head = await anext(report)
    assert head.startswith("\ufeff") and generated == 0
    assert next(csv.reader(StringIO(head[1:]), delimiter=";")) == list(CSV_HEADERS)

    emitted = 0
    async for chunk in report:
        batch = list(csv.reader(StringIO(chunk), delimiter=";"))
        assert 0 < len(batch) <= CSV_BATCH_SIZE
        assert batch[0][1:3] == ["'" + name, category]
        emitted += len(batch)
        assert emitted == generated
    assert emitted == count


async def test_csv_response_closes_body_when_client_disconnects() -> None:
    closed = False

    async def body() -> AsyncGenerator[str]:
        nonlocal closed
        try:
            yield "header"
            yield "data"
        finally:
            closed = True

    async def send(message: Message) -> None:
        if message.get("body") == b"data":
            raise OSError("client disconnected")

    async def receive() -> Message:
        raise AssertionError("ASGI 2.4 disconnects are reported by send")

    response = AnalyticsCSVResponse(body(), filename="analytics.csv")
    with pytest.raises(ClientDisconnect):
        await response({"type": "http", "asgi": {"spec_version": "2.4"}}, receive, send)
    assert closed
