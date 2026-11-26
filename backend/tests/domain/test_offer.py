from datetime import UTC, datetime
from uuid import uuid4

import pytest

from src.domain.entities.offer import OfferVersion
from src.domain.exceptions import CatalogDomainError

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _offer(**overrides: object) -> OfferVersion:
    values: dict[str, object] = {
        "id": uuid4(),
        "created_at": NOW,
        "updated_at": NOW,
        "version": 1,
        "title": "Offer",
        "body": "Terms",
        "status": "draft",
        "published_at": None,
    }
    values.update(overrides)
    return OfferVersion(**values)  # type: ignore[arg-type]


def test_offer_version_validates_fields() -> None:
    offer = _offer()
    assert offer.status == "draft"
    with pytest.raises(CatalogDomainError):
        _offer(version=0)
    with pytest.raises(CatalogDomainError):
        _offer(title="")
    with pytest.raises(CatalogDomainError):
        _offer(body="  ")
    with pytest.raises(CatalogDomainError):
        _offer(status="published")
