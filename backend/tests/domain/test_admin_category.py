from datetime import UTC, datetime
from uuid import uuid4

import pytest

from src.domain.entities.category import Category
from src.domain.exceptions import CatalogDomainError
from src.domain.value_objects.name import EntityName
from src.domain.value_objects.slug import Slug

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _category(version: int = 1) -> Category:
    return Category(
        id=uuid4(),
        created_at=NOW,
        updated_at=NOW,
        name=EntityName.create("E-bikes"),
        slug=Slug.create("ebikes"),
        description=None,
        is_archived=False,
        version=version,
    )


def test_category_version_defaults_to_one() -> None:
    category = Category(
        id=uuid4(),
        created_at=NOW,
        updated_at=NOW,
        name=EntityName.create("E-bikes"),
        slug=Slug.create("ebikes"),
        description=None,
        is_archived=False,
    )

    assert category.version == 1


def test_category_version_must_be_positive() -> None:
    assert _category(version=2).version == 2
    with pytest.raises(CatalogDomainError):
        _category(version=0)
    with pytest.raises(CatalogDomainError):
        _category(version=True)
