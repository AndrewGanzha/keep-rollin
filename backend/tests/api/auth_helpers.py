from __future__ import annotations

import time
from typing import Any, cast
from uuid import UUID

from fastapi.testclient import TestClient

from src.infrastructure.security.secret_box import SecretBox
from src.infrastructure.security.totp import code_at

JWT_SECRET = "test-secret-keep-rollin-0123456789abcdef"
MFA_SECRET = "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP"
PASSWORD = "Bike-Rider-2026!"


def mfa_secret_enc(tenant_id: UUID, user_id: UUID, secret: str = MFA_SECRET) -> str:
    box = SecretBox.from_settings(JWT_SECRET)
    return box.encrypt(secret, context=f"mfa:{tenant_id}:{user_id}")


def enable_mfa(user: Any, *, secret: str = MFA_SECRET) -> None:
    user.mfa_enabled = True
    user.mfa_secret_enc = mfa_secret_enc(user.tenant_id, user.id, secret)
    user.mfa_recovery_hashes = []
    user.mfa_failed_attempts = 0
    user.mfa_failure_window_started_at = None
    user.mfa_locked_until = None
    user.mfa_last_step = None


def totp_now(secret: str = MFA_SECRET) -> str:
    return code_at(secret, timestamp=time.time())


def login_with_mfa(
    client: TestClient,
    email: str,
    *,
    password: str = PASSWORD,
    secret: str = MFA_SECRET,
) -> dict[str, Any]:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    if payload.get("mfa_setup_required"):
        setup = client.post(
            "/api/v1/auth/mfa/setup",
            json={"mfa_token": payload["mfa_token"]},
        )
        assert setup.status_code == 200, setup.text
        enrollment_secret = setup.json()["secret"]
        confirm = client.post(
            "/api/v1/auth/mfa/confirm",
            json={
                "mfa_token": payload["mfa_token"],
                "code": code_at(enrollment_secret, timestamp=time.time()),
            },
        )
        assert confirm.status_code == 200, confirm.text
        return cast(dict[str, Any], confirm.json())
    if payload.get("mfa_required"):
        verify = client.post(
            "/api/v1/auth/mfa/verify",
            json={"mfa_token": payload["mfa_token"], "code": totp_now(secret)},
        )
        assert verify.status_code == 200, verify.text
        return cast(dict[str, Any], verify.json())
    return cast(dict[str, Any], payload)
