import json
import re
from hashlib import sha256
from typing import Annotated, Any
from uuid import UUID

from fastapi import Header, Response
from fastapi.encoders import jsonable_encoder

IfNoneMatch = Annotated[
    list[str] | None,
    Header(description="Return 304 when an entity tag matches the current representation."),
]

_CACHE_CONTROL = "public, max-age=60, stale-while-revalidate=300"
_ENTITY_TAG_ITEM = re.compile(r'[ \t]*(?:W/)?("[\x21\x23-\x7e\x80-\xff]*")[ \t]*(?:,|\Z)')
_EMPTY_LIST_ITEM = re.compile(r"[ \t]*(?:,|\Z)")

_CACHE_HEADERS = {
    "ETag": {"description": "Weak representation validator.", "schema": {"type": "string"}},
    "Cache-Control": {"schema": {"type": "string", "example": _CACHE_CONTROL}},
    "Vary": {"schema": {"type": "string", "example": "X-Tenant"}},
}
CATALOG_CACHE_RESPONSES: dict[int | str, dict[str, Any]] = {
    200: {"headers": _CACHE_HEADERS},
    304: {"description": "Not Modified", "headers": _CACHE_HEADERS},
}


def _matches_if_none_match(field: str, opaque_tag: str) -> bool:
    if field.strip(" \t") == "*":
        return True
    offset = 0
    matched = False
    while offset < len(field):
        tag = _ENTITY_TAG_ITEM.match(field, offset)
        if tag is not None:
            matched = matched or tag.group(1) == opaque_tag
            offset = tag.end()
            continue
        empty = _EMPTY_LIST_ITEM.match(field, offset)
        if empty is None:
            return False
        offset = empty.end()
    return matched


def catalog_cache_response(
    tenant_id: UUID,
    if_none_match: list[str] | None,
    response: Response,
    payload: object,
) -> Response | None:
    canonical = json.dumps(
        [str(tenant_id), jsonable_encoder(payload)],
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    opaque_tag = f'"{sha256(canonical.encode("ascii")).hexdigest()}"'
    headers = {"ETag": f"W/{opaque_tag}", "Cache-Control": _CACHE_CONTROL, "Vary": "X-Tenant"}
    if if_none_match and _matches_if_none_match(",".join(if_none_match), opaque_tag):
        return Response(status_code=304, headers=headers)
    response.headers.update(headers)
    return None
