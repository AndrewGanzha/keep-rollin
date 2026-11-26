from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, cast
from uuid import UUID, uuid4

import jwt

from src.application.services.auth import AccessClaims
from src.domain.entities.user_account import InvalidTokenError, TokenExpiredError, UserRole

MfaPurpose = Literal["login", "enroll"]


@dataclass(frozen=True)
class MfaClaims:
    sub: UUID
    tnt: UUID
    ver: int
    jti: UUID
    purpose: MfaPurpose


class JwtTokenService:
    def __init__(
        self,
        *,
        secret: str,
        algorithm: str = "HS256",
        access_ttl_seconds: int = 900,
        mfa_ttl_seconds: int = 300,
    ) -> None:
        self._secret = secret
        self._algorithm = algorithm
        self._access_ttl_seconds = access_ttl_seconds
        self._mfa_ttl_seconds = mfa_ttl_seconds

    @property
    def expires_in(self) -> int:
        return self._access_ttl_seconds

    @property
    def mfa_expires_in(self) -> int:
        return self._mfa_ttl_seconds

    def create_access(
        self,
        *,
        user_id: UUID,
        tenant_id: UUID,
        role: UserRole,
        token_version: int,
    ) -> str:
        now = datetime.now(UTC)
        payload = {
            "sub": str(user_id),
            "tnt": str(tenant_id),
            "role": role,
            "ver": token_version,
            "jti": str(uuid4()),
            "typ": "access",
            "iat": now,
            "exp": now + timedelta(seconds=self._access_ttl_seconds),
        }
        return cast(str, jwt.encode(payload, self._secret, algorithm=self._algorithm))

    def create_mfa(
        self,
        *,
        user_id: UUID,
        tenant_id: UUID,
        token_version: int,
        jti: UUID,
        purpose: MfaPurpose,
    ) -> str:
        now = datetime.now(UTC)
        payload = {
            "sub": str(user_id),
            "tnt": str(tenant_id),
            "ver": token_version,
            "jti": str(jti),
            "purpose": purpose,
            "typ": "mfa",
            "iat": now,
            "exp": now + timedelta(seconds=self._mfa_ttl_seconds),
        }
        return cast(str, jwt.encode(payload, self._secret, algorithm=self._algorithm))

    def decode_access(self, token: str) -> AccessClaims:
        try:
            payload: dict[str, Any] = jwt.decode(
                token,
                self._secret,
                algorithms=[self._algorithm],
                options={"require": ["sub", "tnt", "role", "ver", "jti", "exp"]},
            )
            token_type = payload.get("typ")
            if token_type is not None and token_type != "access":
                raise InvalidTokenError("Access token is invalid")
            return AccessClaims(
                sub=UUID(str(payload["sub"])),
                tnt=UUID(str(payload["tnt"])),
                role=cast(UserRole, str(payload["role"])),
                ver=int(payload["ver"]),
                jti=str(payload["jti"]),
            )
        except jwt.ExpiredSignatureError as exc:
            raise TokenExpiredError("Access token expired") from exc
        except (jwt.PyJWTError, ValueError, KeyError, TypeError) as exc:
            raise InvalidTokenError("Access token is invalid") from exc

    def decode_mfa(self, token: str) -> MfaClaims:
        try:
            payload: dict[str, Any] = jwt.decode(
                token,
                self._secret,
                algorithms=[self._algorithm],
                options={
                    "require": [
                        "sub",
                        "tnt",
                        "ver",
                        "jti",
                        "purpose",
                        "typ",
                        "exp",
                    ]
                },
            )
            if payload.get("typ") != "mfa":
                raise InvalidTokenError("MFA token is invalid")
            purpose = str(payload["purpose"])
            if purpose not in ("login", "enroll"):
                raise InvalidTokenError("MFA token is invalid")
            return MfaClaims(
                sub=UUID(str(payload["sub"])),
                tnt=UUID(str(payload["tnt"])),
                ver=int(payload["ver"]),
                jti=UUID(str(payload["jti"])),
                purpose=cast(MfaPurpose, purpose),
            )
        except jwt.ExpiredSignatureError as exc:
            raise TokenExpiredError("MFA token expired") from exc
        except InvalidTokenError:
            raise
        except (jwt.PyJWTError, ValueError, KeyError, TypeError) as exc:
            raise InvalidTokenError("MFA token is invalid") from exc
