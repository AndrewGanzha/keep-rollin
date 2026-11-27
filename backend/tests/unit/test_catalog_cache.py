from uuid import UUID

import pytest
from fastapi import Response

from app.api.catalog_cache import catalog_cache_response

TENANT = UUID(int=1)


@pytest.mark.parametrize(
    ("field", "matches"),
    [
        ("*", True),
        ('W/"other,tag", {weak}', True),
        (", {strong}, \t,", True),
        ("{strong}", True),
        ('"", "other"', False),
        ("w/{strong}", False),
        ("bad, {strong}", False),
        ("{strong}, *", False),
        ('"x{hash}x"', False),
    ],
)
def test_catalog_if_none_match_entity_tag_lists(field: str, matches: bool) -> None:
    initial = Response()
    payload = {"name": "Metro"}
    assert catalog_cache_response(TENANT, None, initial, payload) is None
    tag = initial.headers["ETag"]
    conditions = [field.format(weak=tag, strong=tag[2:], hash=tag[3:-1])]
    conditional = catalog_cache_response(TENANT, conditions, Response(), payload)
    if matches:
        assert conditional is not None
        assert conditional.status_code == 304
        assert conditional.body == b""
    else:
        assert conditional is None


def test_catalog_etag_uses_canonical_mapping_and_tenant() -> None:
    response = Response()
    payload = {"string": "Сити", "attributes": {"width": 1, "height": 2}}
    catalog_cache_response(TENANT, None, response, payload)
    conditions = [response.headers["ETag"]]
    same_payload = {"attributes": {"height": 2, "width": 1}, "string": "Сити"}
    assert catalog_cache_response(TENANT, conditions, Response(), same_payload) is not None
    assert catalog_cache_response(UUID(int=2), conditions, Response(), payload) is None
