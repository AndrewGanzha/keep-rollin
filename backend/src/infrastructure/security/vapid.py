from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec


@dataclass(frozen=True)
class VapidKeyPair:
    public_key: str
    private_key: str
    key_id: str


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def generate_vapid_keypair() -> VapidKeyPair:
    private_key: Any = ec.generate_private_key(ec.SECP256R1())
    private_value = private_key.private_numbers().private_value.to_bytes(32, "big")
    public_bytes = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint,
    )
    public_key = _b64url(public_bytes)
    key_id = hashlib.sha256(public_bytes).hexdigest()[:16]
    return VapidKeyPair(
        public_key=public_key,
        private_key=_b64url(private_value),
        key_id=key_id,
    )


def public_from_private(private_key: str) -> str:
    padded = private_key + "=" * (-len(private_key) % 4)
    value = int.from_bytes(base64.urlsafe_b64decode(padded.encode("ascii")), "big")
    private: Any = ec.derive_private_key(value, ec.SECP256R1())
    public_bytes = private.public_key().public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint,
    )
    return _b64url(public_bytes)
