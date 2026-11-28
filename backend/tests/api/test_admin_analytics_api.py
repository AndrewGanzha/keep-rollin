import asyncio
import csv
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from io import StringIO

import pytest
from sqlalchemy import update
from starlette.types import Message, Scope

from app.api import admin_analytics
from app.config import Settings
from app.db import create_engine, create_session_factory
from app.main import create_app
from src.infrastructure.postgres.models.lot_record import LotRecord
from src.infrastructure.security.token_service import JwtTokenService
from tests.api.auth_helpers import JWT_SECRET
from tests.api.test_admin_calendar_api import (
    DATABASE_URL,
    NOW,
    SeededCalendarAPI,
    auth,
    cleanup_calendar,
    client_for,
    login,
    seed_calendar,
)
from tests.api.test_admin_schedule_api import _rental

pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="PostgreSQL DATABASE_URL is required")
URL = "/api/v1/admin/analytics"
START = NOW + timedelta(days=2)
END = START + timedelta(days=3)
PERIOD = {"from": START.isoformat(), "to": END.isoformat()}


@pytest.fixture
def sample() -> Iterator[SeededCalendarAPI]:
    data = seed_calendar()

    async def add_rentals() -> None:
        assert DATABASE_URL
        engine = create_engine(DATABASE_URL)
        try:
            async with create_session_factory(engine).begin() as session:
                await session.execute(
                    update(LotRecord).where(LotRecord.id == data.lot_a_id).values(name="=1+1;Лот")
                )
                _rental(
                    session,
                    data,
                    data.lot_a_id,
                    data.owner_a_id,
                    START - timedelta(hours=12),
                    START + timedelta(hours=12),
                    "completed",
                )
                _rental(
                    session,
                    data,
                    data.lot_a_id,
                    data.owner_a_id,
                    START + timedelta(hours=1),
                    START + timedelta(days=1),
                    "completed",
                )
                _rental(
                    session,
                    data,
                    data.lot_a_id,
                    data.owner_a_id,
                    START + timedelta(days=1),
                    START + timedelta(days=2),
                    "booked",
                )
                _rental(
                    session,
                    data,
                    data.lot_a_id,
                    data.owner_a_id,
                    START + timedelta(days=2),
                    END,
                    "cancelled",
                )
                _rental(
                    session,
                    data,
                    data.lot_a_id,
                    data.owner_a_id,
                    END,
                    END + timedelta(hours=1),
                    "completed",
                )
        finally:
            await engine.dispose()

    try:
        asyncio.run(add_rentals())
        yield data
    finally:
        cleanup_calendar((data.tenant_a, data.tenant_b))


def staff_headers(sample: SeededCalendarAPI) -> dict[str, str]:
    token = JwtTokenService(secret=JWT_SECRET).create_access(
        user_id=sample.owner_a_id, tenant_id=sample.tenant_a, role="owner", token_version=1
    )
    return auth(token)


def test_reports_finance_utilization_compared_and_paged(sample: SeededCalendarAPI) -> None:
    staff = staff_headers(sample)
    with client_for(sample.domain_a) as client:
        summary = client.get(f"{URL}/summary", headers=staff, params=PERIOD)
        assert summary.status_code == 200, summary.text
        assert summary.headers["Cache-Control"] == "no-store"
        body = summary.json()
        assert (body["revenue_minor"], body["rentals_count"], body["cancelled_count"]) == (
            19000,
            3,
            1,
        )
        assert body["avg_rental_minor"] == 9500
        assert body["utilization_pct"] == 33.3  # one occupied day of three, including carry-in
        assert datetime.fromisoformat(body["from"]) == START

        for group in ("category", "lot", "day"):
            result = client.get(
                f"{URL}/revenue", headers=staff, params={**PERIOD, "group_by": group}
            )
            assert result.status_code == 200, result.text
            buckets = result.json()["buckets"]
            assert sum(bucket["revenue_minor"] for bucket in buckets) == 19000
            assert sum(bucket["rentals_count"] for bucket in buckets) == 3

        utilization = client.get(f"{URL}/utilization", headers=staff, params=PERIOD)
        assert utilization.status_code == 200, utilization.text
        assert utilization.json()["buckets"][0]["utilization_pct"] == 33.3

        category = client.get(
            f"{URL}/revenue",
            headers=staff,
            params={**PERIOD, "group_by": "category", "category_id": str(sample.category_a_id)},
        )
        assert category.status_code == 200, category.text
        assert [bucket["key"] for bucket in category.json()["buckets"]] == [
            str(sample.category_a_id)
        ]
        missing_category = client.get(
            f"{URL}/summary", headers=staff, params={**PERIOD, "category_id": str(sample.tenant_b)}
        )
        assert missing_category.status_code == 200, missing_category.text
        assert missing_category.json()["rentals_count"] == 0

        comparison = client.get(
            f"{URL}/compare",
            headers=staff,
            params={
                **PERIOD,
                "compare_from": (START - timedelta(days=10)).isoformat(),
                "compare_to": (START - timedelta(days=9)).isoformat(),
            },
        )
        assert comparison.status_code == 200, comparison.text
        assert comparison.json()["delta"]["revenue_minor"] == 19000
        assert comparison.json()["previous"]["utilization_pct"] == 0

        detail = client.get(
            f"{URL}/lots/{sample.lot_a_id}",
            headers=staff,
            params={**PERIOD, "limit": 1, "offset": 1},
        )
        assert detail.status_code == 200, detail.text
        assert detail.json()["rentals_total"] == 3
        assert len(detail.json()["rentals"]) == 1


def test_analytics_authorization_validation_and_empty_window(sample: SeededCalendarAPI) -> None:
    with client_for(sample.domain_a) as client:
        staff = staff_headers(sample)
        rider = auth(login(client, sample.user_a_email))
        assert client.get(f"{URL}/summary", params=PERIOD).status_code == 401
        assert client.get(f"{URL}/summary", headers=rider, params=PERIOD).status_code == 403
        assert (
            client.get(
                f"{URL}/export", headers=rider, params={**PERIOD, "report": "rentals"}
            ).status_code
            == 403
        )
        assert (
            client.get(f"{URL}/lots/{sample.lot_b_id}", headers=staff, params=PERIOD).status_code
            == 404
        )
        assert (
            client.get(
                f"{URL}/revenue", headers=staff, params={**PERIOD, "group_by": "week"}
            ).status_code
            == 422
        )
        assert (
            client.get(
                f"{URL}/summary", headers=staff, params={**PERIOD, "from": "2026-01-01"}
            ).status_code
            == 422
        )
        assert (
            client.get(
                f"{URL}/summary", headers=staff, params={**PERIOD, "from": "1790000100"}
            ).status_code
            == 422
        )
        long_range = {**PERIOD, "to": (START + timedelta(days=367)).isoformat()}
        assert client.get(f"{URL}/summary", headers=staff, params=long_range).status_code == 422
        start = datetime(2020, 1, 1, tzinfo=UTC)
        zero = client.get(
            f"{URL}/summary",
            headers=staff,
            params={"from": start.isoformat(), "to": (start + timedelta(days=1)).isoformat()},
        )
        assert zero.status_code == 200, zero.text
        assert (
            zero.json()["revenue_minor"]
            == zero.json()["rentals_count"]
            == zero.json()["utilization_pct"]
            == 0
        )


def test_csv_download_is_utf8_excel_dialect_and_tenant_scoped(sample: SeededCalendarAPI) -> None:
    with client_for(sample.domain_a) as client:
        response = client.get(
            f"{URL}/export", headers=staff_headers(sample), params={**PERIOD, "report": "rentals"}
        )
        assert response.status_code == 200, response.text
        assert response.headers["Content-Type"] == "text/csv; charset=utf-8"
        assert response.headers["Content-Disposition"].startswith("attachment;")
        assert response.headers["Cache-Control"] == "no-store"
        assert "Content-Length" not in response.headers
        assert response.content.startswith(b"\xef\xbb\xbf")
        rows = list(csv.reader(StringIO(response.content.decode("utf-8-sig")), delimiter=";"))
        assert rows[0][0] == "ID аренды"
        assert len(rows) == 4
        assert {row[1] for row in rows[1:]} == {"'=1+1;Лот"}
        assert "@" not in response.text


async def test_http_stream_sends_first_chunk_before_producing_the_rest(
    sample: SeededCalendarAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert DATABASE_URL
    first_sent = asyncio.Event()
    received: list[bytes] = []

    async def slow_report(*_args: object) -> AsyncIterator[str]:
        yield "first"
        await first_sent.wait()
        yield "second"

    async def send(message: Message) -> None:
        if message["type"] == "http.response.body" and message.get("body"):
            received.append(message["body"])
            first_sent.set()

    async def receive() -> Message:
        await asyncio.Future()
        raise AssertionError("Unexpected receive completion")

    monkeypatch.setattr(admin_analytics, "export_body", slow_report)
    app = create_app(
        Settings(
            _env_file=None,
            database_url=DATABASE_URL,
            app_env="test",
            database_role="keep_rollin_app",
            jwt_secret=JWT_SECRET,
        )
    )
    query = f"from={START:%Y-%m-%d}T00:00:00Z&to={END:%Y-%m-%d}T00:00:00Z&report=rentals"
    scope: Scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.4"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "https",
        "path": f"{URL}/export",
        "query_string": query.encode(),
        "client": ("127.0.0.1", 50001),
        "headers": [
            (b"host", sample.domain_a.encode()),
            (b"authorization", staff_headers(sample)["Authorization"].encode()),
        ],
    }
    async with app.router.lifespan_context(app):
        await asyncio.wait_for(app(scope, receive, send), timeout=10)
    assert received == [b"first", b"second"]
