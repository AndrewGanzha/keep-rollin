from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import os
from collections.abc import Mapping

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

_PREFIX = "v1"
_NONCE_BYTES = 12
_SALT = b"keep-rollin:security:v1"


def derive_key(secret: str, *, info: str) -> bytes:
    """Derive a domain-separated 256-bit key from the configured root secret."""
    if not secret:
        raise ValueError("security secret must not be empty")
    return HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=_SALT,
        info=info.encode("utf-8"),
    ).derive(secret.encode("utf-8"))


def decode_key(value: str) -> bytes:
    """Decode a base64url-encoded 32-byte key."""
    padded = value + "=" * (-len(value) % 4)
    try:
        raw = base64.urlsafe_b64decode(padded.encode("ascii"))
    except (ValueError, binascii.Error) as exc:
        raise ValueError("security key must be base64url encoded") from exc
    if len(raw) != 32:
        raise ValueError("security key must contain exactly 32 bytes")
    return raw


class SecretBox:
    """Authenticated encryption bound to a specific storage context."""

    def __init__(self, keys: Mapping[str, str], *, primary_id: str) -> None:
        if primary_id not in keys:
            raise ValueError("primary secret key is missing")
        self._keys = {
            key_id: derive_key(secret, info=f"secret-box:{key_id}")
            for key_id, secret in keys.items()
        }
        self._aeads = {key_id: AESGCM(key) for key_id, key in self._keys.items()}
        self._primary_id = primary_id

    @classmethod
    def from_settings(
        cls,
        security_key: str,
        *,
        key_id: str = "primary",
        previous_keys: Mapping[str, str] | None = None,
    ) -> SecretBox:
        keys = {key_id: security_key}
        for previous_id, previous_key in (previous_keys or {}).items():
            keys[previous_id] = previous_key
        return cls(keys, primary_id=key_id)

    def encrypt(self, plaintext: str, *, context: str) -> str:
        key_id = self._primary_id
        nonce = os.urandom(_NONCE_BYTES)
        ciphertext = self._aeads[key_id].encrypt(
            nonce,
            plaintext.encode("utf-8"),
            context.encode("utf-8"),
        )
        payload = base64.urlsafe_b64encode(nonce + ciphertext).decode("ascii")
        return f"{_PREFIX}:{key_id}:{payload}"

    def decrypt(self, value: str, *, context: str) -> str:
        parts = value.split(":", 2)
        if len(parts) != 3 or parts[0] != _PREFIX:
            raise ValueError("unsupported secret format")
        key_id, encoded = parts[1], parts[2]
        aead = self._aeads.get(key_id)
        if aead is None:
            raise ValueError("unknown secret key")
        try:
            payload = base64.urlsafe_b64decode(encoded.encode("ascii"))
        except (ValueError, binascii.Error) as exc:
            raise ValueError("invalid secret encoding") from exc
        if len(payload) <= _NONCE_BYTES:
            raise ValueError("invalid secret payload")
        try:
            plaintext = aead.decrypt(
                payload[:_NONCE_BYTES],
                payload[_NONCE_BYTES:],
                context.encode("utf-8"),
            )
        except InvalidTag as exc:
            raise ValueError("secret authentication failed") from exc
        return plaintext.decode("utf-8")


class CodeHasher:
    """Keyed hash for one-time recovery codes."""

    def __init__(self, pepper: str) -> None:
        self._key = derive_key(pepper, info="recovery-codes")

    def hash(self, code: str) -> str:
        return hmac.new(self._key, code.encode("utf-8"), hashlib.sha256).hexdigest()
