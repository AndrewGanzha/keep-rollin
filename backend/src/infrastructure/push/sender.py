from __future__ import annotations

import math
import socket
import time
from dataclasses import dataclass
from enum import StrEnum
from ipaddress import ip_address

import aiohttp
from cryptography.hazmat.primitives.asymmetric import ec
from py_vapid import Vapid, VapidException  # type: ignore[import-untyped]
from pywebpush import WebPusher, WebPushException  # type: ignore[import-untyped]
from yarl import URL

from src.infrastructure.push.subscription import (
    WNS_HOST_SUFFIX,
    _decode_key,
    validate_push_subscription,
)

# RFC 8291 requires a single record. Headers, the delimiter and the GCM tag
# consume 103 bytes of the provider's 4096-byte minimum supported message size.
_MAX_PLAINTEXT_BYTES = 3993
_VAPID_LIFETIME_SECONDS = 12 * 60 * 60
_CONTENT_ENCODING = "aes128gcm"


class PushSendKind(StrEnum):
    ACCEPTED = "accepted"
    GONE = "gone"
    RETRYABLE = "retryable"
    PERMANENT = "permanent"


@dataclass(frozen=True)
class PushSendResult:
    kind: PushSendKind
    status_code: int | None = None


class WebPushSender:
    def __init__(self, *, subject: str, timeout_seconds: float = 10.0) -> None:
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("Invalid Web Push timeout")
        self._subject = subject
        self._timeout = aiohttp.ClientTimeout(total=timeout_seconds)

    async def send(
        self,
        *,
        endpoint: str,
        p256dh: str,
        auth: str,
        vapid_private_key: str,
        payload: str,
        ttl: int,
    ) -> PushSendResult:
        try:
            validate_push_subscription(endpoint, p256dh, auth)
            plaintext = payload.encode("utf-8")
            if not plaintext or len(plaintext) > _MAX_PLAINTEXT_BYTES or ttl < 0:
                return PushSendResult(PushSendKind.PERMANENT)

            raw_key = _decode_key(vapid_private_key, 32)
            key = ec.derive_private_key(int.from_bytes(raw_key, "big"), ec.SECP256R1())
            # WNS's opaque query token can contain escaped base64 characters.
            url = URL(endpoint, encoded=True)
            is_wns = url.raw_authority.endswith(WNS_HOST_SUFFIX)
            # Worker settings validate the contact URI, including HTTPS paths.
            headers: dict[str, str] = Vapid(private_key=key, conf={"no-strict": True}).sign(
                {
                    "aud": str(url.origin()),
                    "sub": self._subject,
                    "exp": int(time.time()) + _VAPID_LIFETIME_SECONDS,
                }
            )
            if is_wns:
                headers["X-WNS-Type"] = "wns/raw"
            headers.update(
                {
                    "Content-Encoding": _CONTENT_ENCODING,
                    "Content-Type": "application/octet-stream",
                    "TTL": str(ttl),
                }
            )
            ciphertext: bytes = WebPusher(
                {"endpoint": endpoint, "keys": {"p256dh": p256dh, "auth": auth}},
                verbose=False,
            ).encode(plaintext, content_encoding=_CONTENT_ENCODING)["body"]
        except (ValueError, VapidException, WebPushException):
            return PushSendResult(PushSendKind.PERMANENT)

        # Use pywebpush for encryption and control the HTTP request here to
        # disable automatic redirects and avoid reading provider response bodies.
        try:
            async with (
                aiohttp.ClientSession(
                    connector=aiohttp.TCPConnector(socket_factory=_public_socket),
                    timeout=self._timeout,
                    trust_env=False,
                    auto_decompress=False,
                ) as client,
                client.post(
                    url, data=ciphertext, headers=headers, allow_redirects=False, ssl=True
                ) as response,
            ):
                return _classify(response.status, is_wns=is_wns)
        except (aiohttp.ClientError, TimeoutError):
            return PushSendResult(PushSendKind.RETRYABLE)


def _public_socket(
    address_info: tuple[int, int, int, str, tuple[str, int] | tuple[str, int, int, int]],
) -> socket.socket:
    family, kind, protocol, _, address = address_info
    ip = ip_address(address[0])
    if not ip.is_global or ip.is_multicast or ip.is_reserved:
        raise OSError("Invalid Web Push service address")
    return socket.socket(family, kind, protocol)


def _classify(status: int, *, is_wns: bool) -> PushSendResult:
    if 200 <= status <= 299:
        return PushSendResult(PushSendKind.ACCEPTED, status)
    if status in (404, 410):
        return PushSendResult(PushSendKind.GONE, status)
    if status in (408, 429) or 500 <= status <= 599 or (is_wns and status == 406):
        return PushSendResult(PushSendKind.RETRYABLE, status)
    return PushSendResult(PushSendKind.PERMANENT, status)
