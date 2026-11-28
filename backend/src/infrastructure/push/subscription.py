from __future__ import annotations

import base64
import binascii
import re

from cryptography.hazmat.primitives.asymmetric import ec

MAX_PUSH_ENDPOINT_LENGTH = 2048
WNS_HOST_SUFFIX = ".notify.windows.com"

# Match the complete URL so URL normalization cannot change the validated target.
_PUSH_ENDPOINT = re.compile(
    r"https://(?:fcm\.googleapis\.com/(?:fcm/send|wp)/[A-Za-z0-9_:-]+"
    r"|updates\.push\.services\.mozilla\.com/wpush/v[12]/[A-Za-z0-9_-]+={0,2}"
    r"|web\.push\.apple\.com/[A-Za-z0-9_-]+={0,2}"
    r"|[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
    rf"{re.escape(WNS_HOST_SUFFIX)}/w/\?token=(?:[A-Za-z0-9_.~+/=-]|%2[BbFf]|%3[Dd])+"
    r")"
)
_BASE64URL = re.compile(r"[A-Za-z0-9_-]+={0,2}")


def validate_push_subscription(endpoint: str, p256dh: str, auth: str) -> None:
    if len(endpoint) > MAX_PUSH_ENDPOINT_LENGTH or not _PUSH_ENDPOINT.fullmatch(endpoint):
        raise ValueError("Invalid push endpoint")

    try:
        point = _decode_key(p256dh, 65)
        if point[0] != 4:
            raise ValueError
        ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), point)
    except ValueError:
        raise ValueError("Invalid push p256dh key") from None

    try:
        _decode_key(auth, 16)
    except ValueError:
        raise ValueError("Invalid push auth secret") from None


def _decode_key(value: str, size: int) -> bytes:
    if len(value) > 4 * ((size + 2) // 3) or not _BASE64URL.fullmatch(value):
        raise ValueError("Invalid base64url key")
    unpadded = value.rstrip("=")
    try:
        raw = base64.b64decode(unpadded + "=" * (-len(unpadded) % 4), altchars=b"-_", validate=True)
    except binascii.Error:
        raise ValueError("Invalid base64url key") from None
    padded = base64.urlsafe_b64encode(raw).decode("ascii")
    if len(raw) != size or value not in (padded, padded.rstrip("=")):
        raise ValueError("Invalid base64url key")
    return raw
