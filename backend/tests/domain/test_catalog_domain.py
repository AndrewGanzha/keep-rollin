from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime
from typing import Any
from unittest.mock import ANY
from uuid import uuid4

import pytest
from pydantic import ValidationError

from src.domain.entities.category import Category
from src.domain.entities.characteristic import Characteristic
from src.domain.entities.lot import Lot
from src.domain.entities.lot_variant import LotVariant
from src.domain.exceptions import (
    CatalogDomainError,
    InvalidAllowedDurationsError,
    InvalidBatteryCountError,
    InvalidNameError,
    InvalidPriceTierError,
    InvalidSlugError,
)
from src.domain.value_objects.battery_count import BatteryCount
from src.domain.value_objects.duration import AllowedDurations
from src.domain.value_objects.limits import MAX_DATABASE_INTEGER
from src.domain.value_objects.name import EntityName
from src.domain.value_objects.price import PriceTier
from src.domain.value_objects.slug import Slug

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def test_slug_normalizes_valid_value() -> None:
    assert Slug.create("urban-1").value == "urban-1"


def test_slug_rejects_spaces_and_uppercase() -> None:
    with pytest.raises(InvalidSlugError):
        Slug.create("Urban 1")


def test_slug_accepts_task_defined_pattern() -> None:
    assert Slug.create("ebikes--city").value == "ebikes--city"
    assert Slug.create("-ebikes-").value == "-ebikes-"


def test_slug_validator_runs_on_direct_construction() -> None:
    with pytest.raises(ValidationError):
        Slug("invalid_slug")


def test_allowed_durations_must_be_sorted_and_unique() -> None:
    assert AllowedDurations.create([1, 3, 7]).value == [1, 3, 7]
    with pytest.raises(InvalidAllowedDurationsError):
        AllowedDurations.create([7, 1])
    with pytest.raises(InvalidAllowedDurationsError):
        AllowedDurations.create([1, 1])


def test_allowed_durations_rejects_coerced_types_and_protects_inner_list() -> None:
    with pytest.raises(InvalidAllowedDurationsError):
        AllowedDurations.create([True, "7"])

    durations = AllowedDurations.create([1, 7])
    exposed = durations.value
    exposed.clear()

    assert durations.value == [1, 7]


def test_scalar_value_objects_reject_coerced_types() -> None:
    with pytest.raises(InvalidSlugError):
        Slug.create(123)
    with pytest.raises(InvalidNameError):
        EntityName.create(123)
    with pytest.raises(InvalidBatteryCountError):
        BatteryCount.create(True)
    with pytest.raises(InvalidPriceTierError):
        PriceTier.create(True, 1000)


def test_price_tier_requires_positive_values() -> None:
    assert PriceTier.create(1, 40000).price_per_unit_minor == 40000
    with pytest.raises(InvalidPriceTierError):
        PriceTier.create(0, 40000)


def test_domain_bounds_match_database_limits() -> None:
    assert BatteryCount.create(0).value == 0
    assert BatteryCount.create(MAX_DATABASE_INTEGER).value == MAX_DATABASE_INTEGER
    assert PriceTier.create(1, 1).min_units == 1
    assert PriceTier.create(MAX_DATABASE_INTEGER, MAX_DATABASE_INTEGER).min_units == (
        MAX_DATABASE_INTEGER
    )

    with pytest.raises(InvalidBatteryCountError):
        BatteryCount.create(-1)
    with pytest.raises(InvalidBatteryCountError):
        BatteryCount.create(MAX_DATABASE_INTEGER + 1)
    with pytest.raises(InvalidPriceTierError):
        PriceTier.create(0, 1)
    with pytest.raises(InvalidPriceTierError):
        PriceTier.create(1, 0)
    with pytest.raises(InvalidPriceTierError):
        PriceTier.create(MAX_DATABASE_INTEGER + 1, 1)
    with pytest.raises(InvalidPriceTierError):
        PriceTier.create(1, MAX_DATABASE_INTEGER + 1)


def test_value_object_text_boundaries_and_types() -> None:
    assert Slug.create("a").value == "a"
    assert Slug.create("a" * 80).value == "a" * 80
    assert EntityName.create("n").value == "n"
    assert EntityName.create("n" * 120).value == "n" * 120

    with pytest.raises(InvalidSlugError):
        Slug.create("a" * 81)
    with pytest.raises(InvalidSlugError):
        Slug.create(b"valid-slug")
    with pytest.raises(InvalidNameError):
        EntityName.create("")
    with pytest.raises(InvalidNameError):
        EntityName.create("n" * 121)
    with pytest.raises(InvalidNameError):
        EntityName.create({"name": "Urban"})


def test_allowed_durations_boundaries() -> None:
    assert AllowedDurations.create([1]).value == [1]
    assert AllowedDurations.create([365]).value == [365]

    with pytest.raises(InvalidAllowedDurationsError):
        AllowedDurations.create([])
    with pytest.raises(InvalidAllowedDurationsError):
        AllowedDurations.create([0])
    with pytest.raises(InvalidAllowedDurationsError):
        AllowedDurations.create([366])
    with pytest.raises(InvalidAllowedDurationsError):
        AllowedDurations.create([b"1"])


def test_copy_update_is_forbidden() -> None:
    battery = BatteryCount.create(1)
    durations = AllowedDurations.create([1])
    tier = PriceTier.create(1, 1000)

    with pytest.raises(TypeError):
        battery.model_copy(update={"root": -1})
    with pytest.raises(TypeError):
        durations.model_copy(update={"root": ()})
    with pytest.raises(TypeError):
        tier.model_copy(update={"price_per_unit_minor": 0})

    with pytest.raises(TypeError):
        battery.copy(update={"root": -1})
    with pytest.raises(TypeError):
        durations.copy(update={"root": ()})
    with pytest.raises(TypeError):
        tier.copy(update={"price_per_unit_minor": 0})
    with pytest.raises(TypeError):
        tier.copy(exclude={"price_per_unit_minor"})
    with pytest.raises(TypeError):
        durations.copy(exclude={"root"})


def test_model_validate_forces_strict_and_blocks_other_entrypoints() -> None:
    with pytest.raises(ValidationError):
        BatteryCount.model_validate(True, strict=False)
    with pytest.raises(TypeError):
        PriceTier.model_validate_strings({"min_units": "1", "price_per_unit_minor": "1000"})
    with pytest.raises(TypeError):
        PriceTier.model_validate_json('{"min_units": 1, "price_per_unit_minor": 1000}')


def test_model_construct_is_forbidden() -> None:
    with pytest.raises(TypeError):
        BatteryCount.model_construct(root=-1)
    with pytest.raises(TypeError):
        AllowedDurations.model_construct(root=())
    with pytest.raises(TypeError):
        PriceTier.model_construct(min_units=1, price_per_unit_minor=0)
    with pytest.raises(TypeError):
        BatteryCount.construct(root=-1)


def test_value_objects_are_immutable() -> None:
    durations = AllowedDurations.create([1, 7])
    with pytest.raises(AttributeError):
        durations.root.append(366)  # type: ignore[attr-defined]
    with pytest.raises(ValidationError):
        durations.root = (1,)  # type: ignore[misc]

    battery = BatteryCount.create(1)
    with pytest.raises(ValidationError):
        battery.root = -1  # type: ignore[misc]


def _variant(battery_count: int, tiers: list[tuple[int, int]], active: bool = True) -> LotVariant:
    return LotVariant(
        id=uuid4(),
        created_at=NOW,
        updated_at=NOW,
        battery_count=BatteryCount.create(battery_count),
        is_active=active,
        price_tiers=tuple(PriceTier.create(min_units, price) for min_units, price in tiers),
    )


def _lot(
    variants: list[LotVariant],
    status: str = "active",
    characteristics: Any = None,
    photos: Any = None,
    battery_type: str | None = "48v",
    currency: str = "RUB",
) -> Lot:
    return Lot(
        id=uuid4(),
        created_at=NOW,
        updated_at=NOW,
        slug=Slug.create("urban-1"),
        name=EntityName.create("Urban 1"),
        description=None,
        category_id=uuid4(),
        photos=() if photos is None else photos,
        characteristics={} if characteristics is None else characteristics,
        rental_unit="day",
        battery_type=battery_type,
        variants=tuple(variants),
        allowed_durations=AllowedDurations.create([1, 7]),
        status=status,  # type: ignore[arg-type]
        version=1,
        currency=currency,
    )


def test_price_from_uses_cheapest_active_tier_and_tie_breaks() -> None:
    lot = _lot(
        [
            _variant(1, [(1, 50000), (7, 40000)]),
            _variant(2, [(1, 70000), (7, 60000)]),
        ]
    )

    price = lot.price_from()

    assert price is not None
    assert price.amount_minor == 40000
    assert price.at_units == 7
    assert price.battery_count == 1


def test_price_from_tie_breaks_by_at_units_then_battery_count() -> None:
    cheapest_units = _lot(
        [
            _variant(1, [(1, 50000), (7, 40000)]),
            _variant(2, [(1, 40000)]),
        ]
    )
    cheapest_battery = _lot(
        [
            _variant(2, [(1, 40000)]),
            _variant(1, [(1, 40000)]),
        ]
    )

    first = cheapest_units.price_from()
    second = cheapest_battery.price_from()

    assert first is not None
    assert (first.amount_minor, first.at_units, first.battery_count) == (40000, 1, 2)
    assert second is not None
    assert (second.amount_minor, second.at_units, second.battery_count) == (40000, 1, 1)


def test_price_from_ignores_inactive_variants() -> None:
    lot = _lot(
        [
            _variant(1, [(1, 50000), (7, 40000)]),
            _variant(2, [(1, 10000), (7, 9000)], active=False),
        ]
    )

    price = lot.price_from()

    assert price is not None
    assert price.amount_minor == 40000


def test_lot_rejects_growing_price_tiers() -> None:
    with pytest.raises(CatalogDomainError):
        _lot([_variant(1, [(1, 40000), (7, 50000)])])


def test_aggregate_rejects_non_boolean_is_active() -> None:
    with pytest.raises(CatalogDomainError):
        LotVariant(
            id=uuid4(),
            created_at=NOW,
            updated_at=NOW,
            battery_count=BatteryCount.create(1),
            is_active="false",  # type: ignore[arg-type]
            price_tiers=(PriceTier.create(1, 50000),),
        )


def test_variant_validates_its_own_tiers() -> None:
    with pytest.raises(CatalogDomainError):
        _variant(1, [])
    with pytest.raises(CatalogDomainError):
        _variant(1, [(7, 40000), (1, 50000)])
    with pytest.raises(CatalogDomainError):
        _variant(1, [(1, 40000), (1, 30000)])
    with pytest.raises(CatalogDomainError):
        _variant(1, [(1, 40000), (7, 50000)])


def test_lot_rejects_first_tier_that_does_not_match_minimum_duration() -> None:
    with pytest.raises(CatalogDomainError):
        _lot([_variant(1, [(7, 40000)])])


def test_lot_rejects_duplicate_battery_counts() -> None:
    with pytest.raises(CatalogDomainError):
        _lot([_variant(1, [(1, 40000)]), _variant(1, [(1, 40000)])])


def test_lot_rejects_battery_variant_without_battery_type() -> None:
    with pytest.raises(CatalogDomainError):
        _lot([_variant(1, [(1, 40000)])], battery_type=None)


def test_lot_bookable_requires_active_status_and_variant() -> None:
    assert _lot([_variant(1, [(1, 40000), (7, 40000)])]).is_bookable is True

    inactive_variant_lot = _lot([_variant(1, [(1, 40000), (7, 40000)], active=False)])
    assert inactive_variant_lot.is_bookable is False
    assert inactive_variant_lot.price_from() is None

    assert _lot([_variant(1, [(1, 40000), (7, 40000)])], status="maintenance").is_bookable is False


def test_lot_collections_are_immutable_after_validation() -> None:
    lot = _lot([_variant(1, [(1, 50000)])])

    with pytest.raises(AttributeError):
        lot.variants.append(lot.variants[0])  # type: ignore[attr-defined]
    with pytest.raises(AttributeError):
        lot.variants[0].price_tiers.append(lot.variants[0].price_tiers[0])  # type: ignore[attr-defined]
    with pytest.raises(FrozenInstanceError):
        lot.variants = ()  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        lot.variants[0].price_tiers = ()  # type: ignore[misc]
    with pytest.raises(TypeError):
        lot.characteristics["speed"] = 25  # type: ignore[index]


def test_lot_rejects_nested_or_boolean_characteristics() -> None:
    invalid_payloads = (
        {"speed": [25]},
        {"speed": {"value": 25}},
        {"speed": True},
        {1: "value"},
        {"speed": float("nan")},
        {"speed": float("inf")},
        {"speed": float("-inf")},
    )

    for payload in invalid_payloads:
        with pytest.raises(CatalogDomainError):
            _lot([_variant(1, [(1, 50000)])], characteristics=payload)


def test_lot_rejects_wrong_scalar_and_collection_types() -> None:
    with pytest.raises(CatalogDomainError):
        _lot([_variant(1, [(1, 50000)])], battery_type=["48v"])  # type: ignore[arg-type]
    with pytest.raises(CatalogDomainError):
        _lot([_variant(1, [(1, 50000)])], currency="rub")
    with pytest.raises(CatalogDomainError):
        _lot([_variant(1, [(1, 50000)])], currency="123")
    with pytest.raises(CatalogDomainError):
        _lot([_variant(1, [(1, 50000)])], currency="РУБ")
    with pytest.raises(CatalogDomainError):
        _lot([_variant(1, [(1, 50000)])], currency="R$B")
    with pytest.raises(CatalogDomainError):
        _lot([_variant(1, [(1, 50000)])], characteristics=[])
    with pytest.raises(CatalogDomainError):
        Lot(
            id=uuid4(),
            created_at=NOW,
            updated_at=NOW,
            slug=Slug.create("urban-1"),
            name=EntityName.create("Urban 1"),
            description=[],  # type: ignore[arg-type]
            category_id=uuid4(),
            photos=(),
            characteristics={},
            rental_unit="day",
            battery_type="48v",
            variants=(_variant(1, [(1, 50000)]),),
            allowed_durations=AllowedDurations.create([1, 7]),
            status="active",
            version=1,
            currency="RUB",
        )
    with pytest.raises(CatalogDomainError):
        Lot(
            id=uuid4(),
            created_at=NOW,
            updated_at=NOW,
            slug=Slug.create("urban-1"),
            name=EntityName.create("Urban 1"),
            description=None,
            category_id=uuid4(),
            photos=(),
            characteristics={},
            rental_unit="day",
            battery_type="48v",
            variants=5,  # type: ignore[arg-type]
            allowed_durations=AllowedDurations.create([1, 7]),
            status="active",
            version=1,
            currency="RUB",
        )


def test_entity_rejects_invalid_identity_types() -> None:
    lot = _lot([_variant(1, [(1, 50000)])])
    with pytest.raises(CatalogDomainError):
        replace(lot, id=[])  # type: ignore[arg-type]
    with pytest.raises(CatalogDomainError):
        replace(lot, created_at="now")  # type: ignore[arg-type]
    with pytest.raises(CatalogDomainError):
        replace(lot, category_id=[])  # type: ignore[arg-type]


def test_direct_construction_rejects_untyped_inputs() -> None:
    with pytest.raises(ValidationError):
        AllowedDurations({1, 7})  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        BatteryCount(True)


def test_literal_fields_reject_mock_any() -> None:
    lot = _lot([_variant(1, [(1, 50000)])])
    characteristic = _characteristic(("blue",))

    with pytest.raises(CatalogDomainError):
        replace(lot, status=ANY)
    with pytest.raises(CatalogDomainError):
        replace(lot, rental_unit=ANY)
    with pytest.raises(CatalogDomainError):
        replace(characteristic, type=ANY)


def test_variant_rejects_non_sequence_price_tiers() -> None:
    with pytest.raises(CatalogDomainError):
        LotVariant(
            id=uuid4(),
            created_at=NOW,
            updated_at=NOW,
            battery_count=BatteryCount.create(1),
            is_active=True,
            price_tiers=5,  # type: ignore[arg-type]
        )


def test_characteristic_rejects_invalid_fields() -> None:
    invalid_values = (
        {"code": "color"},
        {"name": "Color"},
        {"type": "bad"},
        {"unit": 1},
        {"is_required": "yes"},
        {"is_archived": "no"},
        {"sort": "1"},
    )
    for override in invalid_values:
        values: dict[str, Any] = {
            "id": uuid4(),
            "created_at": NOW,
            "updated_at": NOW,
            "code": Slug.create("color"),
            "name": EntityName.create("Color"),
            "type": "select",
            "unit": None,
            "is_required": False,
            "options": ("blue",),
            "sort": 1,
            "is_archived": False,
        }
        values.update(override)
        with pytest.raises(CatalogDomainError):
            Characteristic(**values)


def test_lot_rejects_non_sequence_or_non_string_photos() -> None:
    for payload in ("https://example.com/photo.jpg", {"url": "photo"}, [["photo"]]):
        with pytest.raises(CatalogDomainError):
            _lot([_variant(1, [(1, 50000)])], photos=payload)

    source = ["https://example.com/photo.jpg"]
    lot = _lot([_variant(1, [(1, 50000)])], photos=source)
    source.append("https://example.com/other.jpg")
    assert lot.photos == ("https://example.com/photo.jpg",)


def _characteristic(options: Any) -> Characteristic:
    return Characteristic(
        id=uuid4(),
        created_at=NOW,
        updated_at=NOW,
        code=Slug.create("color"),
        name=EntityName.create("Color"),
        type="select",
        unit=None,
        is_required=False,
        options=options,
        sort=1,
        is_archived=False,
    )


def test_category_rejects_invalid_characteristics_collection() -> None:
    with pytest.raises(CatalogDomainError):
        Category(
            id=uuid4(),
            created_at=NOW,
            updated_at=NOW,
            name=EntityName.create("E-bikes"),
            slug=Slug.create("ebikes"),
            description=None,
            is_archived=False,
            characteristics=5,  # type: ignore[arg-type]
        )
    with pytest.raises(CatalogDomainError):
        Category(
            id=uuid4(),
            created_at=NOW,
            updated_at=NOW,
            name=EntityName.create("E-bikes"),
            slug=Slug.create("ebikes"),
            description=None,
            is_archived=False,
            characteristics=(object(),),  # type: ignore[arg-type]
        )


def test_characteristic_rejects_non_sequence_or_non_string_options() -> None:
    for payload in ("blue", {"blue": False}, [["blue"]]):
        with pytest.raises(CatalogDomainError):
            _characteristic(payload)

    source = ["blue"]
    characteristic = _characteristic(source)
    source.append("red")
    assert characteristic.options == ("blue",)
    assert _characteristic(("blue", "red")).options == ("blue", "red")
