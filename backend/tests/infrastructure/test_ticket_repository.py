import os
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql.ranges import Range
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db import configure_session, create_engine, create_session_factory
from app.models import Tenant, User
from src.infrastructure.postgres.models.category_record import CategoryRecord
from src.infrastructure.postgres.models.file_record import FileRecord
from src.infrastructure.postgres.models.lot_record import LotRecord
from src.infrastructure.postgres.models.occupancy_record import OccupancyRecord
from src.infrastructure.postgres.models.rental_record import RentalRecord
from src.infrastructure.postgres.models.ticket_record import TicketAttachmentRecord, TicketRecord
from src.infrastructure.postgres.repositories.file_repository import FileRepository
from src.infrastructure.postgres.repositories.ticket_repository import TicketRepository

DATABASE_URL = os.getenv("DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="PostgreSQL is required")
NOW = datetime(2026, 11, 28, 12, tzinfo=UTC)


@dataclass(frozen=True)
class TenantData:
    id: UUID
    user_id: UUID
    other_user_id: UUID
    lot_id: UUID
    rental_id: UUID


@pytest.fixture
async def seeded() -> AsyncIterator[
    tuple[async_sessionmaker[AsyncSession], TenantData, TenantData]
]:
    assert DATABASE_URL is not None
    engine = create_engine(DATABASE_URL)
    sessions = create_session_factory(engine)
    tenants: list[TenantData] = []
    try:
        async with sessions.begin() as session:
            for _ in range(2):
                tenant = TenantData(uuid4(), uuid4(), uuid4(), uuid4(), uuid4())
                tenants.append(tenant)
                slug = f"tickets-{tenant.id.hex[:12]}"
                session.add(Tenant(id=tenant.id, slug=slug, name=slug, domain=f"{slug}.test"))
                await session.flush()
                category_id = uuid4()
                session.add(
                    CategoryRecord(id=category_id, tenant_id=tenant.id, name=slug, slug=slug)
                )
                for index, user_id in enumerate((tenant.user_id, tenant.other_user_id)):
                    session.add(
                        User(
                            id=user_id,
                            tenant_id=tenant.id,
                            name=f"Renter {index}",
                            email=f"renter-{index}@{slug}.test",
                        )
                    )
                await session.flush()
                session.add(
                    LotRecord(
                        id=tenant.lot_id,
                        tenant_id=tenant.id,
                        category_id=category_id,
                        slug=slug,
                        name=slug,
                        rental_unit="hour",
                        allowed_durations=[1],
                        status="active",
                    )
                )
                await session.flush()
                occupancy_id = uuid4()
                end = NOW + timedelta(hours=1)
                session.add(
                    OccupancyRecord(
                        id=occupancy_id,
                        tenant_id=tenant.id,
                        lot_id=tenant.lot_id,
                        kind="booking",
                        period=Range(NOW, end, bounds="[)"),
                        ref_id=tenant.rental_id,
                        created_by=tenant.user_id,
                    )
                )
                await session.flush()
                session.add(
                    RentalRecord(
                        id=tenant.rental_id,
                        tenant_id=tenant.id,
                        user_id=tenant.user_id,
                        lot_id=tenant.lot_id,
                        occupancy_id=occupancy_id,
                        variant_id=uuid4(),
                        battery_count=0,
                        start_time=NOW,
                        end_time=end,
                        price_minor=10_000,
                        currency="RUB",
                        status="active",
                        cancellation_deadline=NOW - timedelta(days=1),
                    )
                )
        yield sessions, tenants[0], tenants[1]
    finally:
        async with sessions.begin() as session:
            await session.execute(
                delete(Tenant).where(Tenant.id.in_([item.id for item in tenants]))
            )
        await engine.dispose()


def _scope(session: AsyncSession, tenant: TenantData) -> None:
    configure_session(session, tenant_id=tenant.id, database_role="keep_rollin_app")


def _ticket(tenant: TenantData, created_at: datetime = NOW) -> TicketRecord:
    return TicketRecord(
        id=uuid4(),
        tenant_id=tenant.id,
        rental_id=tenant.rental_id,
        category="battery",
        description="The battery will not charge.",
        created_at=created_at,
    )


def _photo(
    tenant: TenantData,
    *,
    user_id: UUID | None = None,
    purpose: str = "ticket_photo",
    ready: bool = True,
    purging: bool = False,
) -> FileRecord:
    file_id = uuid4()
    return FileRecord(
        id=file_id,
        tenant_id=tenant.id,
        uploaded_by=user_id or tenant.user_id,
        purpose=purpose,
        object_key=f"{tenant.id}/{file_id}.jpg",
        content_type="image/jpeg",
        size_bytes=123,
        created_at=NOW - timedelta(days=2),
        is_ready=ready,
        is_purging=purging,
    )


async def test_ticket_reads_and_period_counts_are_scoped(
    seeded: tuple[async_sessionmaker[AsyncSession], TenantData, TenantData],
) -> None:
    sessions, first, second = seeded
    later = NOW + timedelta(days=1)
    own = [_ticket(first), _ticket(first), _ticket(first, later)]
    other_tenant = _ticket(second)
    async with sessions.begin() as session:
        _scope(session, first)
        repo = TicketRepository(session)
        for ticket in own:
            await repo.add(ticket)
    async with sessions.begin() as session:
        _scope(session, second)
        await TicketRepository(session).add(other_tenant)
        assert await TicketRepository(session).lock(own[0].id) is None
        assert list(await session.scalars(select(TicketRecord.id))) == [other_tenant.id]
    async with sessions.begin() as session:
        _scope(session, first)
        repo = TicketRepository(session)
        assert await repo.get_details(other_tenant.id) is None
        assert await repo.get_details(own[0].id, user_id=first.other_user_id) is None
        assert await repo.list_for_rental(first.rental_id, user_id=first.other_user_id) == []
        details = await repo.get_details(own[0].id, user_id=first.user_id)
        assert details is not None
        ticket, lot, user = details
        assert (ticket.id, lot.id, user.id) == (own[0].id, first.lot_id, first.user_id)
        listings = await repo.list_for_rental(first.rental_id, user_id=first.user_id)
        assert [item[0].id for item in listings] == [
            own[2].id,
            *sorted((own[0].id, own[1].id), reverse=True),
        ]
        page, count = await repo.list_page(
            limit=1,
            offset=1,
            status="submitted",
            lot_id=first.lot_id,
            rental_id=first.rental_id,
            user_id=first.user_id,
            created_from=NOW,
            created_to=later,
        )
        assert count == 2
        assert [item[0].id for item in page] == [min(own[0].id, own[1].id)]
        assert await repo.count_for_rental(first.rental_id, start=NOW, end=later) == 2


async def test_private_photo_links_are_eligible_ordered_and_protected_from_orphan_claim(
    seeded: tuple[async_sessionmaker[AsyncSession], TenantData, TenantData],
) -> None:
    sessions, first, second = seeded
    left, right, orphan = _photo(first), _photo(first), _photo(first)
    invalid = [
        _photo(first, user_id=first.other_user_id),
        _photo(first, purpose="verification_passport"),
        _photo(first, ready=False),
        _photo(first, ready=False, purging=True),
        _photo(second),
    ]
    async with sessions.begin() as session:
        session.add_all([left, right, orphan, *invalid])

    ticket = _ticket(first)
    async with sessions.begin() as writer:
        _scope(writer, first)
        repo = TicketRepository(writer)
        eligible = await repo.lock_photo_ids(
            first.user_id, [right.id, *[item.id for item in invalid], left.id, uuid4()]
        )
        assert eligible == {left.id, right.id}
        async with sessions.begin() as cleaner:
            _scope(cleaner, first)
            locked = await FileRepository(cleaner).lock_orphans(NOW, limit=100)
            assert {item.id for item in locked} == {orphan.id, *[item.id for item in invalid[:4]]}
        await repo.add(ticket, file_ids=[right.id, left.id])

    async with sessions.begin() as session:
        _scope(session, first)
        photos = await TicketRepository(session).photos_for_tickets([ticket.id])
        assert [item.id for item in photos[ticket.id]] == [right.id, left.id]
        files = FileRepository(session)
        assert await files.count_orphans(NOW) == 5
        locked = await files.lock_orphans(NOW, limit=100)
        assert {item.id for item in locked} == {orphan.id, *[item.id for item in invalid[:4]]}
    async with sessions.begin() as session:
        _scope(session, second)
        assert await TicketRepository(session).photos_for_tickets([ticket.id]) == {}
        assert list(await session.scalars(select(TicketAttachmentRecord.file_id))) == []


@pytest.mark.parametrize("foreign_reference", ["rental", "file"])
async def test_ticket_foreign_keys_reject_cross_tenant_links(
    seeded: tuple[async_sessionmaker[AsyncSession], TenantData, TenantData],
    foreign_reference: str,
) -> None:
    sessions, first, second = seeded
    photo = _photo(second)
    async with sessions.begin() as session:
        session.add(photo)

    ticket = _ticket(first)
    file_ids = []
    if foreign_reference == "rental":
        ticket.rental_id = second.rental_id
        constraint = "fk_ticket_tenant_id_rental"
    else:
        file_ids = [photo.id]
        constraint = "fk_ticket_attachment_tenant_id_file"
    async with sessions() as session:
        _scope(session, first)
        await TicketRepository(session).add(ticket, file_ids=file_ids)
        with pytest.raises(IntegrityError, match=constraint):
            await session.commit()
