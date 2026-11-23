import asyncio
import os
import ssl
from urllib.parse import parse_qs, urlsplit, urlunsplit

import certifi
import pytest

from app.db import create_engine, database_ready, engine_ready, parse_dsn, split_dsn


def test_parse_dsn_moves_application_name_to_server_settings() -> None:
    parsed = parse_dsn(
        "postgresql://user:pass@127.0.0.1:5432/keep_rollin"
        "?sslmode=disable&application_name=keep-rollin"
    )

    assert parsed.ssl is False
    assert parsed.server_settings == {"application_name": "keep-rollin"}
    assert "sslmode" not in parsed.dsn
    assert "application_name" not in parsed.dsn


def test_split_dsn_translates_sslmode_disable() -> None:
    normalized, ssl_arg = split_dsn(
        "postgresql://user:pass@127.0.0.1:5432/keep_rollin"
        "?sslmode=disable&application_name=keep-rollin"
    )

    assert ssl_arg is False
    assert "sslmode" not in normalized
    assert "application_name" not in normalized


def test_split_dsn_translates_sslmode_require() -> None:
    normalized, ssl_arg = split_dsn(
        "postgresql://user:pass@127.0.0.1:5432/keep_rollin?sslmode=require"
    )

    assert isinstance(ssl_arg, ssl.SSLContext)
    assert ssl_arg.verify_mode == ssl.CERT_NONE
    assert "sslmode" not in normalized


def test_split_dsn_keeps_allow_and_prefer_modes() -> None:
    for mode in ("allow", "prefer"):
        _normalized, ssl_arg = split_dsn(
            f"postgresql://user:pass@127.0.0.1:5432/keep_rollin?sslmode={mode}"
        )
        assert ssl_arg == mode


def test_split_dsn_rejects_unknown_sslmode() -> None:
    with pytest.raises(ValueError, match="unsupported sslmode"):
        split_dsn("postgresql://user:pass@127.0.0.1:5432/keep_rollin?sslmode=typo")


def test_invalid_dsn_error_does_not_include_password() -> None:
    with pytest.raises(ValueError) as error:
        parse_dsn("postgresql://user:supersecret@[::1:5432/keep_rollin")

    assert "supersecret" not in str(error.value)


def test_require_with_root_certificate_verifies_ca() -> None:
    parsed = parse_dsn(
        "postgresql://user:pass@127.0.0.1:5432/keep_rollin"
        f"?sslmode=require&sslrootcert={certifi.where()}"
    )

    assert isinstance(parsed.ssl, ssl.SSLContext)
    assert parsed.ssl.verify_mode == ssl.CERT_REQUIRED


def test_require_with_root_certificate_from_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PGSSLROOTCERT", certifi.where())
    parsed = parse_dsn("postgresql://user:pass@127.0.0.1:5432/keep_rollin?sslmode=require")

    assert isinstance(parsed.ssl, ssl.SSLContext)
    assert parsed.ssl.verify_mode == ssl.CERT_REQUIRED


def test_allow_or_prefer_rejects_tls_context_parameters() -> None:
    with pytest.raises(ValueError, match="not supported"):
        parse_dsn(
            "postgresql://user:pass@127.0.0.1:5432/keep_rollin"
            "?sslmode=prefer&ssl_min_protocol_version=TLSv1.3"
        )


def test_tls_minimum_version_is_applied() -> None:
    parsed = parse_dsn(
        "postgresql://user:pass@127.0.0.1:5432/keep_rollin"
        f"?sslmode=verify-full&sslrootcert={certifi.where()}"
        "&ssl_min_protocol_version=TLSv1.3"
    )

    assert isinstance(parsed.ssl, ssl.SSLContext)
    assert parsed.ssl.minimum_version == ssl.TLSVersion.TLSv1_3


def test_unsupported_tls_query_parameter_is_rejected() -> None:
    with pytest.raises(ValueError, match="sslcrl"):
        parse_dsn(
            "postgresql://user:pass@127.0.0.1:5432/keep_rollin?sslmode=require&sslcrl=revoked.pem"
        )


def test_verify_full_from_environment_checks_hostname(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PGSSLMODE", "verify-full")
    monkeypatch.setenv("PGSSLROOTCERT", certifi.where())
    parsed = parse_dsn("postgresql://user:pass@127.0.0.1:5432/keep_rollin")

    assert isinstance(parsed.ssl, ssl.SSLContext)
    assert parsed.ssl.check_hostname is True
    assert parsed.ssl.verify_mode == ssl.CERT_REQUIRED


def test_tls_minimum_version_from_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PGSSLMINPROTOCOLVERSION", "TLSv1.3")
    monkeypatch.setenv("PGSSLROOTCERT", certifi.where())
    parsed = parse_dsn("postgresql://user:pass@127.0.0.1:5432/keep_rollin?sslmode=verify-full")

    assert isinstance(parsed.ssl, ssl.SSLContext)
    assert parsed.ssl.minimum_version == ssl.TLSVersion.TLSv1_3


def test_options_is_a_server_setting() -> None:
    parsed = parse_dsn(
        "postgresql://user:pass@127.0.0.1:5432/keep_rollin?options=-c%20statement_timeout%3D1000"
    )

    assert parsed.server_settings["options"] == "-c statement_timeout=1000"
    assert "options" not in parsed.dsn


def test_empty_authority_moves_host_into_netloc() -> None:
    parsed = parse_dsn("postgresql:///keep_rollin?host=127.0.0.1&port=5432")

    assert parsed.dsn == "postgresql://127.0.0.1:5432/keep_rollin"


@pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="DATABASE_URL is required")
def test_engine_accepts_empty_authority_uri() -> None:
    parsed = urlsplit(os.environ["DATABASE_URL"])
    database = parsed.path.lstrip("/")
    user = f"&user={parsed.username}" if parsed.username else ""
    dsn = (
        f"postgresql:///{database}?host={parsed.hostname}"
        f"&port={parsed.port or 5432}{user}"
    )

    async def check() -> bool:
        engine = create_engine(dsn)
        try:
            return await engine_ready(engine, 2.0)
        finally:
            await engine.dispose()

    assert asyncio.run(check()) is True


@pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="DATABASE_URL is required")
def test_database_ready_accepts_sslmode_disable() -> None:
    dsn = os.environ["DATABASE_URL"]
    parsed = urlsplit(dsn)
    query = parse_qs(parsed.query)
    query["sslmode"] = ["disable"]
    dsn_with_sslmode = urlunsplit(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            "&".join(f"{key}={value[0]}" for key, value in query.items()),
            parsed.fragment,
        )
    )

    assert asyncio.run(database_ready(dsn_with_sslmode, 2.0)) is True
