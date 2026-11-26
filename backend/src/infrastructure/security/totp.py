from __future__ import annotations

import base64
import binascii
import hmac
import secrets
import struct
import time
from datetime import UTC, datetime
from hashlib import sha1
from urllib.parse import quote

CODE_DIGITS = 6
STEP_SECONDS = 30
SECRET_BYTES = 20


def generate_secret() -> str:
    """Return a fresh base32 TOTP secret without padding."""
    return base64.b32encode(secrets.token_bytes(SECRET_BYTES)).decode("ascii").rstrip("=")


def _decode_secret(secret: str) -> bytes:
    normalized = secret.strip().upper()
    padding = "=" * (-len(normalized) % 8)
    try:
        return base64.b32decode(normalized + padding)
    except (ValueError, binascii.Error) as exc:
        raise ValueError("invalid TOTP secret") from exc


def code_at(secret: str, *, timestamp: float, offset: int = 0) -> str:
    """RFC 6238 code for a fixed timestamp and step offset."""
    counter = int(timestamp // STEP_SECONDS) + offset
    digest = hmac.new(_decode_secret(secret), struct.pack(">Q", counter), sha1).digest()
    position = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[position : position + 4])[0] & 0x7FFFFFFF
    return str(value % (10**CODE_DIGITS)).zfill(CODE_DIGITS)


def current_step(timestamp: float | None = None) -> int:
    return int((time.time() if timestamp is None else timestamp) // STEP_SECONDS)


def normalize_code(code: str) -> str:
    normalized = code.strip().replace(" ", "")
    if len(normalized) != CODE_DIGITS or not normalized.isdigit():
        raise ValueError("code must contain six digits")
    return normalized


def verify_code(
    secret: str,
    code: str,
    *,
    timestamp: float | None = None,
    last_step: int | None = None,
) -> int | None:
    """Return the matched step, or None. Already used steps are rejected."""
    try:
        normalized = normalize_code(code)
    except ValueError:
        return None
    now = time.time() if timestamp is None else timestamp
    current = int(now // STEP_SECONDS)
    for offset in (0, -1, 1):
        step = current + offset
        if last_step is not None and step <= last_step:
            continue
        if hmac.compare_digest(code_at(secret, timestamp=now, offset=offset), normalized):
            return step
    return None


def build_otpauth_uri(*, secret: str, account: str, issuer: str) -> str:
    label = quote(f"{issuer}:{account}", safe="")
    return (
        f"otpauth://totp/{label}?secret={secret}&issuer={quote(issuer, safe='')}"
        f"&algorithm=SHA1&digits={CODE_DIGITS}&period={STEP_SECONDS}"
    )


def step_started_at(step: int) -> datetime:
    return datetime.fromtimestamp(step * STEP_SECONDS, tz=UTC)
