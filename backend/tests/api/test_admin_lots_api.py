import json
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from tests.api.test_admin_categories_api import (
    DATABASE_URL,
    SeededAdminCategories,
    auth,
    cleanup_admin_categories,
    client_for,
    login,
    seed_admin_categories,
)

pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="DATABASE_URL is required for PostgreSQL integration tests",
)
LOTS = "/api/v1/admin/lots"
PHOTO = "https://example.test/photos/front%20view.jpg"


@pytest.fixture
def seeded() -> Iterator[SeededAdminCategories]:
    value = seed_admin_categories()
    try:
        yield value
    finally:
        cleanup_admin_categories((value.tenant_a, value.tenant_b))


def payload(category_id: UUID) -> dict[str, object]:
    return {
        "category_id": str(category_id),
        "name": "  Городской велосипед  ",
        "description": "Test description",
        "rental_unit": "day",
        "battery_type": "48v",
        "allowed_durations": [1, 7],
        "characteristics": {},
        "variants": [
            {"battery_count": 0, "price_tiers": [{"min_units": 1, "price_per_unit_minor": 4900}]},
            {
                "battery_count": 1,
                "price_tiers": [
                    {"min_units": 1, "price_per_unit_minor": 6500},
                    {"min_units": 7, "price_per_unit_minor": 4200},
                ],
            },
        ],
        "photos": [PHOTO],
    }


def create_lot(client: TestClient, headers: dict[str, str], category_id: UUID) -> dict[str, object]:
    response = client.post(LOTS, headers=headers, json=payload(category_id))
    assert response.status_code == 201, response.text
    assert response.headers["Cache-Control"] == "no-store"
    value: dict[str, object] = response.json()
    return value


def test_admin_lot_round_trip_and_variant_identity(seeded: SeededAdminCategories) -> None:
    with client_for(seeded.domain_a) as client:
        headers = auth(login(client, seeded.owner_a_email))
        first = create_lot(client, headers, seeded.active_category_id)
        second = create_lot(client, headers, seeded.active_category_id)
        assert first["name"] == "Городской велосипед"
        assert first["slug"] != second["slug"]
        assert str(first["slug"]).startswith("gorodskoy-velosiped-")
        assert first["status"] == "active"
        assert first["version"] == 1
        assert first["price_from"] == {
            "amount_minor": 4200,
            "per": "day",
            "at_units": 7,
            "battery_count": 1,
        }

        url = f"{LOTS}/{first['id']}"
        detail = client.get(url, headers=headers)
        assert detail.status_code == 200
        assert detail.headers["Cache-Control"] == "no-store"
        assert detail.json() == first
        old = {variant["battery_count"]: variant for variant in detail.json()["variants"]}

        filtered = client.get(
            LOTS,
            headers=headers,
            params={
                "category_id": str(seeded.active_category_id),
                "status": "active",
                "q": "ГОРОДСКОЙ",
                "limit": 1,
                "offset": 1,
            },
        )
        assert filtered.status_code == 200, filtered.text
        assert filtered.headers["Cache-Control"] == "no-store"
        assert filtered.json()["total"] == 2
        assert filtered.json()["items"][0]["id"] in {first["id"], second["id"]}
        literal_search = client.get(LOTS, headers=headers, params={"q": "%"})
        assert literal_search.json()["total"] == 0

        changed = client.patch(
            url,
            headers=headers,
            json={
                "version": 1,
                "status": "active",
                "variants": [
                    {
                        "battery_count": 2,
                        "is_active": False,
                        "price_tiers": [{"min_units": 1, "price_per_unit_minor": 3000}],
                    },
                    {
                        "battery_count": 1,
                        "price_tiers": [
                            {"min_units": 1, "price_per_unit_minor": 6200},
                            {"min_units": 7, "price_per_unit_minor": 4000},
                        ],
                    },
                ],
            },
        )
        assert changed.status_code == 200, changed.text
        assert changed.headers["Cache-Control"] == "no-store"
        data = changed.json()
        assert data["version"] == 2
        assert data["description"] == "Test description"
        assert data["photos"] == [PHOTO]
        assert data["status"] == "active"
        assert data["price_from"]["amount_minor"] == 4000
        assert [variant["battery_count"] for variant in data["variants"]] == [1, 2]
        assert data["variants"][0]["id"] == old[1]["id"]
        assert data["variants"][1]["id"] != old[0]["id"]
        public = client.get(f"/api/v1/public/lots/{first['slug']}")
        assert public.status_code == 200, public.text
        assert public.json() == data

        stale = client.patch(url, headers=headers, json={"version": 1, "name": "Stale"})
        assert stale.status_code == 409
        assert stale.json()["code"] == "stale_version"
        transition = client.patch(url, headers=headers, json={"version": 2, "status": "archived"})
        assert transition.status_code == 422
        assert "status" in transition.json()["fields"]

        explicit = payload(seeded.active_category_id) | {"slug": first["slug"]}
        duplicate = client.post(LOTS, headers=headers, json=explicit)
        assert duplicate.status_code == 409, duplicate.text
        assert duplicate.json()["code"] == "slug_taken"


def test_lot_writes_are_owner_only_and_tenant_scoped(seeded: SeededAdminCategories) -> None:
    with client_for(seeded.domain_a) as client:
        headers = auth(login(client, seeded.owner_a_email))
        lot = create_lot(client, headers, seeded.active_category_id)
        url = f"{LOTS}/{lot['id']}"
        assert client.get(LOTS).status_code == 401
        admin = auth(login(client, seeded.admin_a_email))
        assert client.get(url, headers=admin).status_code == 403
        assert (
            client.post(LOTS, headers=admin, json=payload(seeded.active_category_id)).status_code
            == 403
        )
        user = auth(login(client, seeded.user_a_email))
        assert client.get(LOTS, headers=user).status_code == 403

    with client_for(seeded.domain_a, browser_headers=False) as client:
        missing_csrf = client.patch(url, headers=headers, json={"version": 1, "name": "New name"})
        assert missing_csrf.status_code == 403

    with client_for(seeded.domain_b) as client:
        foreign = auth(login(client, seeded.owner_b_email))
        assert client.get(LOTS, headers=foreign).json()["total"] == 0
        assert client.get(url, headers=foreign).status_code == 404
        patch = client.patch(url, headers=foreign, json={"version": 1, "name": "Hijack"})
        assert patch.status_code == 404
        wrong_category = client.post(LOTS, headers=foreign, json=payload(seeded.active_category_id))
        assert wrong_category.status_code == 404


def test_lot_validation_reports_precise_fields(seeded: SeededAdminCategories) -> None:
    category_id = seeded.active_category_id
    request = payload(category_id)
    variants = [
        {
            "battery_count": 1,
            "price_tiers": [
                {"min_units": 1, "price_per_unit_minor": 6000},
                {"min_units": 2, "price_per_unit_minor": 6500},
                {"min_units": 2, "price_per_unit_minor": 5500},
            ],
        },
        {"battery_count": 1, "price_tiers": [{"min_units": 1, "price_per_unit_minor": 5500}]},
    ]
    cases: list[tuple[dict[str, object], str]] = [
        ({"characteristics": {"unknown": "text"}}, "characteristics.unknown"),
        ({"characteristics": {"power": True}}, "characteristics.power"),
        ({"characteristics": {"power": "100"}}, "characteristics.power"),
        ({"characteristics": {"drive": "unknown"}}, "characteristics.drive"),
        ({"characteristics": {"label": "  "}}, "characteristics.label"),
        ({"characteristics": {"label": "good\x00label"}}, "characteristics.label"),
        ({"allowed_durations": [1, True]}, "allowed_durations.1"),
        ({"allowed_durations": [1, 1]}, "allowed_durations.1"),
        ({"allowed_durations": [2, 7]}, "variants.0.price_tiers.0.min_units"),
        ({"battery_type": "  "}, "battery_type"),
        ({"variants": variants}, "variants.0.price_tiers.1.price_per_unit_minor"),
        ({"variants": variants}, "variants.0.price_tiers.2.min_units"),
        ({"variants": variants}, "variants.1.battery_count"),
        (
            {
                "variants": [
                    {
                        "battery_count": 0,
                        "price_tiers": [
                            {"min_units": 1, "price_per_unit_minor": 0},
                        ],
                    }
                ]
            },
            "variants.0.price_tiers.0.price_per_unit_minor",
        ),
        ({"photos": [123]}, "photos.0"),
        ({"photos": ["https:/example.test/image.jpg"]}, "photos.0"),
        ({"photos": [PHOTO] * 11}, "photos"),
        ({"photos": [], "file_ids": []}, "file_ids"),
        (
            {"photos": ["https://private.example.test/document.jpg?X-Amz-Signature=fake"]},
            "photos.0",
        ),
        ({"description": "\ud800"}, "description"),
        ({"battery_type": "\ud800"}, "battery_type"),
        ({"characteristics": {"label": "\ud800"}}, "characteristics.label"),
        ({"characteristics": {"\ud800": "corrupt key"}}, "characteristics"),
        ({"status": "maintenance"}, "status"),
        ({"category_id": str(seeded.archived_category_id)}, "category_id"),
    ]
    with client_for(seeded.domain_a) as client:
        headers = auth(login(client, seeded.owner_a_email))
        define = client.put(
            f"/api/v1/admin/categories/{category_id}/characteristics",
            headers=headers,
            json={
                "version": 1,
                "items": [
                    {"code": "power", "name": "Power", "type": "number", "is_required": True},
                    {"code": "label", "name": "Label", "type": "text", "is_required": True},
                    {"code": "drive", "name": "Drive", "type": "select", "options": ["chain"]},
                ],
            },
        )
        assert define.status_code == 200, define.text
        missing = client.post(LOTS, headers=headers, json=request)
        assert missing.status_code == 422
        assert set(missing.json()["fields"]) == {"characteristics.power", "characteristics.label"}

        valid_characteristics = {"power": 100.5, "label": "Test", "drive": "chain"}
        request["characteristics"] = valid_characteristics
        for invalid, field in cases:
            response = client.post(
                LOTS,
                headers=headers | {"Content-Type": "application/json"},
                content=json.dumps(request | invalid),
            )
            assert response.status_code == 422, (field, response.text)
            assert field in response.json()["fields"], (field, response.text)

        nonfinite = client.post(
            LOTS,
            headers=headers | {"Content-Type": "application/json"},
            content=json.dumps(request).replace("100.5", "1e999"),
        )
        assert nonfinite.status_code == 422
        assert "characteristics.power" in nonfinite.json()["fields"]

        create = client.post(LOTS, headers=headers, json=request | {"status": "archived"})
        assert create.status_code == 201, create.text
        assert create.json()["status"] == "archived"
        assert create.json()["characteristics"] == valid_characteristics
        assert client.get(f"/api/v1/public/lots/{create.json()['slug']}").status_code == 404
        url = f"{LOTS}/{create.json()['id']}"

        archive = client.put(
            f"/api/v1/admin/categories/{category_id}/characteristics",
            headers=headers,
            json={
                "version": 2,
                "items": [
                    {
                        "code": "drive",
                        "name": "Drive",
                        "type": "select",
                        "options": ["chain", "belt"],
                        "is_archived": True,
                    }
                ],
            },
        )
        assert archive.status_code == 200, archive.text
        unchanged = {"power": 120, "label": "Edited"}
        updated = client.patch(
            url, headers=headers, json={"version": 1, "characteristics": unchanged}
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["characteristics"] == unchanged | {"drive": "chain"}

        new_archive_value = {"version": 2, "characteristics": unchanged | {"drive": "belt"}}
        declined = client.patch(url, headers=headers, json=new_archive_value)
        assert declined.status_code == 422
        assert "characteristics.drive" in declined.json()["fields"]

        bad_file = client.patch(
            url, headers=headers, json={"version": 2, "file_ids": [str(uuid4())]}
        )
        assert bad_file.status_code == 404
        preserved = client.get(url, headers=headers)
        assert preserved.json()["version"] == 2
        assert preserved.json()["photos"] == [PHOTO]


def test_concurrent_admin_lot_updates_have_one_winner(seeded: SeededAdminCategories) -> None:
    with client_for(seeded.domain_a) as client:
        headers = auth(login(client, seeded.owner_a_email))
        lot = create_lot(client, headers, seeded.active_category_id)
        url = f"{LOTS}/{lot['id']}"

        def change_name(name: str) -> tuple[int, str]:
            response = client.patch(url, headers=headers, json={"version": 1, "name": name})
            return response.status_code, response.text

        with ThreadPoolExecutor(max_workers=2) as requests:
            results = list(requests.map(change_name, ["One", "Two"]))

        assert sorted(result[0] for result in results) == [200, 409], results
        assert client.get(url, headers=headers).json()["version"] == 2
