from __future__ import annotations

import base64
import json
import logging
import socket
import time
from typing import TypedDict
from unittest.mock import MagicMock

import aiohttp
import http_ece  # type: ignore[import-untyped]
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from py_vapid import Vapid  # type: ignore[import-untyped]

from src.infrastructure.push.sender import PushSendKind, PushSendResult, WebPushSender
from src.infrastructure.push.subscription import validate_push_subscription
from src.infrastructure.security.vapid import generate_vapid_keypair, public_from_private

_AUTH = bytes(range(16))
_ENDPOINT = "https://fcm.googleapis.com/fcm/send/fixture:device"
_SUBJECT = "mailto:push@example.com"
_WNS_ORIGIN = "https://wns2-ln2p.notify.windows.com"
_WNS_ENDPOINT = f"{_WNS_ORIGIN}/w/?token=fixture%2btoken%2Fpart%3d"


class _SendOptions(TypedDict):
    endpoint: str
    p256dh: str
    auth: str
    vapid_private_key: str
    payload: str
    ttl: int


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


@pytest.fixture
def browser_key() -> ec.EllipticCurvePrivateKey:
    return ec.generate_private_key(ec.SECP256R1())


@pytest.fixture
def message(browser_key: ec.EllipticCurvePrivateKey) -> _SendOptions:
    browser_point = browser_key.public_key().public_bytes(
        serialization.Encoding.X962,  # type: ignore[arg-type]
        serialization.PublicFormat.UncompressedPoint,  # type: ignore[arg-type]
    )
    return {
        "endpoint": _ENDPOINT,
        "p256dh": _b64(browser_point),
        "auth": _b64(_AUTH),
        "vapid_private_key": generate_vapid_keypair().private_key,
        "payload": '{"title":"Прокат","url":"/account"}',
        "ttl": 3600,
    }


@pytest.fixture
def transport(monkeypatch: pytest.MonkeyPatch) -> tuple[MagicMock, MagicMock, MagicMock, MagicMock]:
    response = MagicMock(spec=aiohttp.ClientResponse)
    response.status = 201
    response.headers = {}
    client = MagicMock(spec=aiohttp.ClientSession)
    client.__aenter__.return_value = client
    client.post.return_value.__aenter__.return_value = response
    session_factory = MagicMock(return_value=client)
    connector_factory = MagicMock()
    monkeypatch.setattr(aiohttp, "ClientSession", session_factory)
    monkeypatch.setattr(aiohttp, "TCPConnector", connector_factory)
    return response, client, session_factory, connector_factory


@pytest.mark.parametrize(
    "endpoint",
    [
        _ENDPOINT,
        "https://fcm.googleapis.com/wp/fixture:device",
        "https://updates.push.services.mozilla.com/wpush/v1/fixture-token==",
        "https://updates.push.services.mozilla.com/wpush/v2/fixture-token",
        "https://web.push.apple.com/fixture-token",
        _WNS_ENDPOINT,
    ],
)
def test_provider_subscription_urls_accept_canonical_keys(
    message: _SendOptions, endpoint: str
) -> None:
    validate_push_subscription(endpoint, message["p256dh"], message["auth"])
    validate_push_subscription(endpoint, message["p256dh"] + "=", message["auth"] + "==")


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://fcm.googleapis.com/fcm/send/token",
        "https://fcm.googleapis.com.evil.example/fcm/send/token",
        "https://sub.fcm.googleapis.com/fcm/send/token",
        "https://fcm.googleapis.com@127.0.0.1/fcm/send/token",
        "https://user@fcm.googleapis.com/fcm/send/token",
        "https://fcm.googleapis.com:443/fcm/send/token",
        "https://fcm.googleapis.com./fcm/send/token",
        "https://fcm.googleapis.com/fcm/send",
        "https://fcm.googleapis.com/fcm/send/",
        "https://fcm.googleapis.com/fcm/send/token?",
        "https://fcm.googleapis.com/fcm/send/token#",
        "https://fcm.googleapis.com/fcm/send/token\n",
        "https://fcm.googleapis.com/fcm/send/token?secret",
        "https://fcm.googleapis.com/v1/projects/fixture/messages:send",
        "https://fcm.googleapis.com/fcm/send/../token",
        "https://fcm.googleapis.com/fcm/send/%2E%2E%2ftoken",
        "https://fcm.googleapis.com/fcm/send/fixture\\token",
        "https://fcm.googleapis.com/fcm/send/tokén",
        "https://fcm.googleapis.com/fcm/send/" + "t" * 2048,
        "https://updates.push.services.mozilla.com/m/token",
        "https://updates.push.services.mozilla.com/wpush/v3/token",
        "https://api.push.apple.com/3/device/token",
        "https://web.push.apple.com/3/device/token",
        "https://notify.windows.com/w/?token=fixture",
        "https://wns.region.notify.windows.com/w/?token=fixture",
        "https://wns.notify.windows.com.evil.example/w/?token=fixture",
        f"{_WNS_ORIGIN}/?token=fixture",
        f"{_WNS_ORIGIN}/w/?token=",
        f"{_WNS_ORIGIN}/w/?other=fixture",
        f"{_WNS_ORIGIN}/w/?token=fixture&token=second",
        f"{_WNS_ORIGIN}/w/?token=fixture%26token%3Dsecond",
        f"{_WNS_ORIGIN}/w/?token=fixture%0D%0A",
        f"{_WNS_ENDPOINT}#fragment",
    ],
)
def test_rejects_urls_outside_provider_policy(message: _SendOptions, endpoint: str) -> None:
    with pytest.raises(ValueError, match=r"^Invalid push endpoint$"):
        validate_push_subscription(endpoint, message["p256dh"], message["auth"])


@pytest.mark.parametrize("point", [b"\x04" + b"\0" * 64, b"\x03" + b"\0" * 64, b"\0" * 33])
def test_rejects_invalid_p256_points(message: _SendOptions, point: bytes) -> None:
    with pytest.raises(ValueError, match=r"^Invalid push p256dh key$"):
        validate_push_subscription(_ENDPOINT, _b64(point), message["auth"])


@pytest.mark.parametrize("auth", ["", "[secret]", _b64(bytes(15)), _b64(bytes(17)), "A" * 21 + "B"])
def test_rejects_invalid_auth_secret(message: _SendOptions, auth: str) -> None:
    with pytest.raises(ValueError, match=r"^Invalid push auth secret$"):
        validate_push_subscription(_ENDPOINT, message["p256dh"], auth)


async def test_sends_actual_vapid_signature_and_encrypted_browser_payload(
    message: _SendOptions,
    browser_key: ec.EllipticCurvePrivateKey,
    transport: tuple[MagicMock, MagicMock, MagicMock, MagicMock],
) -> None:
    response, client, session_factory, connector_factory = transport
    sender = WebPushSender(subject=_SUBJECT, timeout_seconds=3.5)

    assert await sender.send(**message) == PushSendResult(PushSendKind.ACCEPTED, 201)

    assert str(client.post.call_args.args[0]) == _ENDPOINT
    request = client.post.call_args.kwargs
    assert request["allow_redirects"] is False
    assert request["ssl"] is True
    assert session_factory.call_args.kwargs["trust_env"] is False
    assert session_factory.call_args.kwargs["timeout"].total == 3.5
    assert connector_factory.call_args.kwargs["socket_factory"] is not None
    client.post.return_value.__aenter__.assert_awaited_once()
    client.post.return_value.__aexit__.assert_awaited_once()
    response.read.assert_not_called()
    response.text.assert_not_called()
    response.json.assert_not_called()

    headers = request["headers"]
    assert headers["TTL"] == str(message["ttl"])
    assert headers["Content-Type"] == "application/octet-stream"
    assert headers["Content-Encoding"] == "aes128gcm"
    assert "X-WNS-Type" not in headers
    authorization = headers["Authorization"]
    assert Vapid.verify(authorization)
    token, public_key = authorization.removeprefix("vapid t=").split(",k=")
    assert public_key == public_from_private(message["vapid_private_key"])
    claims_segment = token.split(".")[1]
    claims = json.loads(base64.urlsafe_b64decode(claims_segment + "=" * (-len(claims_segment) % 4)))
    assert claims["aud"] == "https://fcm.googleapis.com"
    assert claims["sub"] == _SUBJECT
    assert time.time() < claims["exp"] < time.time() + 86400

    body = request["data"]
    plaintext = message["payload"].encode("utf-8")
    assert plaintext not in body
    decrypted = http_ece.decrypt(
        body, private_key=browser_key, auth_secret=_AUTH, version="aes128gcm"
    )
    assert decrypted == plaintext


async def test_sends_wns_raw_web_push_with_the_original_encoded_token(
    message: _SendOptions,
    browser_key: ec.EllipticCurvePrivateKey,
    transport: tuple[MagicMock, MagicMock, MagicMock, MagicMock],
) -> None:
    response, client, _, _ = transport
    response.status = 200
    options: _SendOptions = {**message, "endpoint": _WNS_ENDPOINT}
    contact = "https://example.com:8443/contact"
    sender = WebPushSender(subject=contact)

    assert await sender.send(**options) == PushSendResult(PushSendKind.ACCEPTED, 200)

    url = client.post.call_args.args[0]
    assert str(url) == _WNS_ENDPOINT
    request = client.post.call_args.kwargs
    assert request["allow_redirects"] is False
    assert request["ssl"] is True
    headers = request["headers"]
    assert headers["X-WNS-Type"] == "wns/raw"
    assert headers["Content-Type"] == "application/octet-stream"
    authorization = headers["Authorization"]
    assert Vapid.verify(authorization)
    claims_segment = authorization.split(".")[1]
    claims = json.loads(base64.urlsafe_b64decode(claims_segment + "=" * (-len(claims_segment) % 4)))
    assert claims["aud"] == _WNS_ORIGIN
    assert claims["sub"] == contact
    decrypted = http_ece.decrypt(
        request["data"], private_key=browser_key, auth_secret=_AUTH, version="aes128gcm"
    )
    assert decrypted == options["payload"].encode("utf-8")


@pytest.mark.parametrize(
    ("status", "kind"),
    [
        (202, PushSendKind.ACCEPTED),
        (204, PushSendKind.ACCEPTED),
        (302, PushSendKind.PERMANENT),
        (400, PushSendKind.PERMANENT),
        (403, PushSendKind.PERMANENT),
        (404, PushSendKind.GONE),
        (406, PushSendKind.PERMANENT),
        (408, PushSendKind.RETRYABLE),
        (410, PushSendKind.GONE),
        (413, PushSendKind.PERMANENT),
        (429, PushSendKind.RETRYABLE),
        (500, PushSendKind.RETRYABLE),
        (503, PushSendKind.RETRYABLE),
    ],
)
async def test_classifies_provider_status_without_reading_body(
    message: _SendOptions,
    transport: tuple[MagicMock, MagicMock, MagicMock, MagicMock],
    status: int,
    kind: PushSendKind,
) -> None:
    response, client, _, _ = transport
    response.status = status
    response.headers = {"Location": "http://127.0.0.1/"}
    assert await WebPushSender(subject=_SUBJECT).send(**message) == PushSendResult(kind, status)
    client.post.assert_called_once()
    response.read.assert_not_called()
    response.text.assert_not_called()
    response.json.assert_not_called()


async def test_classifies_wns_provider_throttling_as_retryable(
    message: _SendOptions,
    transport: tuple[MagicMock, MagicMock, MagicMock, MagicMock],
) -> None:
    response, _, _, _ = transport
    response.status = 406
    options: _SendOptions = {**message, "endpoint": _WNS_ENDPOINT}
    sender = WebPushSender(subject=_SUBJECT)
    response.headers = {"Retry-After": "provider may echo a token here"}
    assert await sender.send(**options) == PushSendResult(PushSendKind.RETRYABLE, 406)


@pytest.mark.parametrize("error", [TimeoutError, aiohttp.ClientConnectionError])
async def test_network_failures_return_safe_retry_result(
    message: _SendOptions,
    transport: tuple[MagicMock, MagicMock, MagicMock, MagicMock],
    caplog: pytest.LogCaptureFixture,
    error: type[Exception],
) -> None:
    _, client, _, _ = transport
    client.post.return_value.__aenter__.side_effect = error(_ENDPOINT)
    with caplog.at_level(logging.DEBUG):
        result = await WebPushSender(subject=_SUBJECT).send(**message)
    assert result == PushSendResult(PushSendKind.RETRYABLE)
    assert _ENDPOINT not in caplog.text
    assert message["vapid_private_key"] not in caplog.text
    assert message["payload"] not in caplog.text


async def test_invalid_input_never_reaches_network(
    message: _SendOptions,
    transport: tuple[MagicMock, MagicMock, MagicMock, MagicMock],
) -> None:
    _, _, session_factory, _ = transport
    sender = WebPushSender(subject=_SUBJECT)
    expected = PushSendResult(PushSendKind.PERMANENT)
    bad_endpoint: _SendOptions = {**message, "endpoint": "http://127.0.0.1"}
    bad_auth: _SendOptions = {**message, "auth": "invalid"}
    zero_key: _SendOptions = {**message, "vapid_private_key": _b64(bytes(32))}
    file_key: _SendOptions = {**message, "vapid_private_key": "local-vapid.pem"}
    large_payload: _SendOptions = {**message, "payload": "я" * 1997}
    for options in (bad_endpoint, bad_auth, zero_key, file_key, large_payload):
        assert await sender.send(**options) == expected
    session_factory.assert_not_called()


@pytest.mark.parametrize(
    "target", ["127.0.0.1", "169.254.169.254", "100.64.1.2", "::1", "::ffff:127.0.0.1", "ff02::1"]
)
async def test_connector_rejects_non_public_resolved_address(
    message: _SendOptions,
    transport: tuple[MagicMock, MagicMock, MagicMock, MagicMock],
    target: str,
) -> None:
    _, _, _, connector_factory = transport
    assert (await WebPushSender(subject=_SUBJECT).send(**message)).kind == PushSendKind.ACCEPTED
    socket_factory = connector_factory.call_args.kwargs["socket_factory"]
    with pytest.raises(OSError, match=r"^Invalid Web Push service address$"):
        socket_factory((socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (target, 443)))
