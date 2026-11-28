from collections.abc import Iterator
from datetime import timedelta
from uuid import uuid4

import pytest

from src.application.services.audit import AuditEntry
from src.infrastructure.postgres.repositories.audit_repository import AuditRepository
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

pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="DATABASE_URL is required for PostgreSQL integration tests",
)

SETTINGS = "/api/v1/admin/settings"
CATEGORIES = "/api/v1/admin/categories"
OFFERS = "/api/v1/admin/offers"
AUDIT_LOG = "/api/v1/admin/audit-log"
CLIENT_IP = "203.0.113.11"


@pytest.fixture
def seeded() -> Iterator[SeededCalendarAPI]:
    value = seed_calendar()
    try:
        yield value
    finally:
        cleanup_calendar((value.tenant_a, value.tenant_b))


def test_staff_mutations_record_exact_safe_metadata(seeded: SeededCalendarAPI) -> None:
    with client_for(seeded.domain_a, client_host=CLIENT_IP) as client:
        owner = auth(login(client, seeded.owner_a_email))
        admin = auth(login(client, seeded.admin_a_email))
        settings_payload = {
            "version": 1,
            "logo_url": "https://example.test/private-logo-name",
            "policies": {"booking_horizon_days": 42},
        }
        settings = client.patch(
            SETTINGS,
            headers={**owner, "X-Request-Id": "staff-audit-settings"},
            json=settings_payload,
        )
        assert settings.status_code == 200, settings.text
        assert settings.headers["X-Request-Id"] == "staff-audit-settings"

        created_category = client.post(
            CATEGORIES,
            headers=owner,
            json={"name": "Private category name", "slug": "private-category-slug"},
        )
        assert created_category.status_code == 201, created_category.text
        category = created_category.json()
        category_path = f"{CATEGORIES}/{category['id']}"
        updated_category = client.patch(
            category_path,
            headers=owner,
            json={
                "version": category["version"],
                "description": "Private category description",
                "is_archived": True,
            },
        )
        assert updated_category.status_code == 200, updated_category.text
        characteristics = client.put(
            f"{category_path}/characteristics",
            headers=owner,
            json={
                "version": updated_category.json()["version"],
                "items": [
                    {
                        "code": "private-characteristic-code",
                        "name": "Private characteristic name",
                        "type": "select",
                        "options": ["Private option"],
                    }
                ],
            },
        )
        assert characteristics.status_code == 200, characteristics.text

        created_offer = client.post(
            OFFERS, headers=owner, json={"title": "Private title", "body": "Private offer body"}
        )
        assert created_offer.status_code == 201, created_offer.text
        offer = created_offer.json()
        offer_path = f"{OFFERS}/{offer['id']}"
        updated_offer = client.patch(offer_path, headers=owner, json={"title": "Updated title"})
        assert updated_offer.status_code == 200, updated_offer.text
        published_offer = client.post(f"{offer_path}/publish", headers=owner)
        assert published_offer.status_code == 200, published_offer.text

        start = NOW + timedelta(days=30)
        blocks = f"/api/v1/admin/lots/{seeded.lot_a_id}/blocks"
        created_block = client.post(
            blocks,
            headers=admin,
            json={
                "start_time": start.isoformat(),
                "end_time": (start + timedelta(hours=1)).isoformat(),
                "reason": "Private block reason",
            },
        )
        assert created_block.status_code == 201, created_block.text
        block_id = created_block.json()["id"]
        released_block = client.delete(f"{blocks}/{block_id}", headers=admin)
        assert released_block.status_code == 204, released_block.text

        assert client.delete(f"{blocks}/{block_id}", headers=admin).status_code == 204
        assert client.delete(f"{blocks}/{uuid4()}", headers=admin).status_code == 404
        assert client.patch(SETTINGS, headers=owner, json=settings_payload).status_code == 409
        assert client.patch(SETTINGS, headers=admin, json=settings_payload).status_code == 403
        assert client.get(AUDIT_LOG, headers=admin).status_code == 403

        log = client.get(AUDIT_LOG, headers=owner)
        assert log.status_code == 200, log.text

    items = log.json()["items"]
    by_request = {row["request_id"]: row for row in items}
    assert len(by_request) == len(items) == 9
    expectations = [
        (
            settings,
            "settings.updated",
            "tenant_settings",
            str(seeded.tenant_a),
            {"changed_fields": ["logo_url", "policies"]},
        ),
        (created_category, "category.created", "category", category["id"], {"is_archived": False}),
        (
            updated_category,
            "category.updated",
            "category",
            category["id"],
            {"changed_fields": ["description", "is_archived"], "is_archived": True},
        ),
        (
            characteristics,
            "category.characteristics_updated",
            "category",
            category["id"],
            {"count": 1},
        ),
        (created_offer, "offer.created", "offer", offer["id"], {"version": offer["version"]}),
        (updated_offer, "offer.updated", "offer", offer["id"], {"version": offer["version"]}),
        (published_offer, "offer.published", "offer", offer["id"], {"version": offer["version"]}),
        (created_block, "lot.blocked", "lot_block", block_id, {}),
        (released_block, "lot.unblocked", "lot_block", block_id, {}),
    ]
    for response, action, entity_type, entity_id, metadata in expectations:
        row = by_request[response.headers["X-Request-Id"]]
        assert row["action"] == action
        assert row["entity_type"] == entity_type
        assert row["entity_id"] == entity_id
        assert row["metadata"] == metadata
        assert row["ip"] == CLIENT_IP
        if entity_type == "lot_block":
            assert row["actor_id"] == str(seeded.admin_a_id)
            assert row["actor_role"] == "admin"
        else:
            assert row["actor_id"] == str(seeded.owner_a_id)
            assert row["actor_role"] == "owner"

    with client_for(seeded.domain_b) as client:
        foreign = auth(login(client, seeded.owner_b_email))
        foreign_log = client.get(AUDIT_LOG, headers=foreign)
        assert foreign_log.status_code == 200, foreign_log.text
        assert foreign_log.json()["items"] == []


def test_failed_audit_insert_rolls_back_staff_mutation(
    seeded: SeededCalendarAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    insert = AuditRepository.add

    async def insert_and_fail(repository: AuditRepository, entry: AuditEntry) -> None:
        await insert(repository, entry)
        raise RuntimeError("test failure after flushing audit insert")

    monkeypatch.setattr(AuditRepository, "add", insert_and_fail)
    with client_for(seeded.domain_a) as client:
        owner = auth(login(client, seeded.owner_a_email))
        original = client.get(SETTINGS, headers=owner)
        assert original.status_code == 200, original.text
        changed = client.patch(
            SETTINGS,
            headers=owner,
            json={
                "version": original.json()["version"],
                "primary_color": "#123456",
                "currency": "EUR",
            },
        )
        assert changed.status_code == 500, changed.text
        current = client.get(SETTINGS, headers=owner)
        assert current.status_code == 200, current.text
        assert current.json() == original.json()
        log = client.get(AUDIT_LOG, headers=owner)
        assert log.status_code == 200, log.text
        assert log.json()["items"] == []
