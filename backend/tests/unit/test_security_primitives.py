from __future__ import annotations

import time
from datetime import UTC, datetime

import pytest

from src.infrastructure.security import totp
from src.infrastructure.security.mfa_codes import generate_recovery_codes, normalize_recovery_code
from src.infrastructure.security.secret_box import CodeHasher, SecretBox


def test_rfc6238_vectors() -> None:
    secret = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"
    vectors = {
        59: "287082",
        1_111_111_109: "081804",
        1_111_111_111: "050471",
        1_234_567_890: "005924",
        2_000_000_000: "279037",
        20_000_000_000: "353130",
    }
    for timestamp, expected in vectors.items():
        assert totp.code_at(secret, timestamp=timestamp) == expected


def test_verify_accepts_one_step_window_and_rejects_replay() -> None:
    secret = totp.generate_secret()
    now = time.time()
    current = totp.current_step(now)
    previous_code = totp.code_at(secret, timestamp=now, offset=-1)
    assert totp.verify_code(secret, previous_code, timestamp=now) == current - 1
    assert totp.verify_code(secret, previous_code, timestamp=now, last_step=current - 1) is None

    current_code = totp.code_at(secret, timestamp=now)
    matched = totp.verify_code(secret, current_code, timestamp=now)
    assert matched == current
    assert totp.verify_code(secret, current_code, timestamp=now, last_step=matched) is None


def test_verify_rejects_malformed_and_invalid_secret_codes() -> None:
    secret = totp.generate_secret()
    assert totp.verify_code(secret, "12345") is None
    assert totp.verify_code(secret, "abcdef") is None
    assert totp.verify_code(secret, "١٢٣٤٥٦") is None
    with pytest.raises(ValueError):
        totp.code_at("not-base32", timestamp=time.time())


def test_otpauth_uri_contains_issuer_and_secret() -> None:
    uri = totp.build_otpauth_uri(secret="ABC234", account="owner@example.com", issuer="Keep Rollin")
    assert uri.startswith("otpauth://totp/Keep%20Rollin%3Aowner%40example.com?")
    assert "secret=ABC234" in uri
    assert "issuer=Keep%20Rollin" in uri
    assert "period=30" in uri


def test_secret_box_round_trip_and_tamper_detection() -> None:
    box = SecretBox.from_settings("x" * 32)
    encrypted = box.encrypt("JBSWY3DPEHPK3PXP", context="totp:tenant:user")
    assert encrypted.startswith("v1:primary:")
    assert "JBSWY3DPEHPK3PXP" not in encrypted
    assert box.decrypt(encrypted, context="totp:tenant:user") == "JBSWY3DPEHPK3PXP"
    with pytest.raises(ValueError):
        box.decrypt(encrypted, context="totp:other:user")
    with pytest.raises(ValueError):
        box.decrypt(encrypted[:-2] + "AA", context="totp:tenant:user")
    with pytest.raises(ValueError):
        box.decrypt("v1:primary:not-base64", context="totp:tenant:user")


def test_secret_box_key_rotation_uses_old_key_for_old_ciphertext() -> None:
    old_box = SecretBox.from_settings("o" * 32, key_id="old")
    encrypted = old_box.encrypt("secret", context="vapid:tenant")
    rotated = SecretBox.from_settings(
        "n" * 32,
        key_id="new",
        previous_keys={"old": "o" * 32},
    )
    assert rotated.decrypt(encrypted, context="vapid:tenant") == "secret"
    assert rotated.encrypt("secret", context="vapid:tenant").startswith("v1:new:")


def test_recovery_codes_are_unique_normalized_and_keyed() -> None:
    codes = generate_recovery_codes()
    assert len(codes) == 10
    assert len(set(codes)) == 10
    hasher = CodeHasher("pepper-" + "x" * 32)
    normalized = normalize_recovery_code(codes[0])
    digest = hasher.hash(normalized)
    assert len(digest) == 64
    assert digest != hasher.hash(normalize_recovery_code(codes[1]))
    assert digest != CodeHasher("other-" + "x" * 32).hash(normalized)
    with pytest.raises(ValueError):
        normalize_recovery_code("too-short")


def test_step_started_at_is_utc() -> None:
    moment = totp.step_started_at(20_000_000)
    assert moment.tzinfo is UTC
    assert moment == datetime.fromtimestamp(20_000_000 * 30, tz=UTC)
