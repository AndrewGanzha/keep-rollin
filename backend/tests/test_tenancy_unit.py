from app.tenancy import normalize_host, normalize_platform_domain


def test_normalize_host_lowercases_and_strips_port() -> None:
    assert normalize_host("Tenant-A.TEST:3000") == "tenant-a.test"


def test_normalize_host_strips_trailing_dot_and_spaces() -> None:
    assert normalize_host(" Tenant-A.TEST. ") == "tenant-a.test"


def test_normalize_host_keeps_ipv6_brackets() -> None:
    assert normalize_host("[::1]:8000") == "[::1]"


def test_normalize_host_strips_dot_after_port() -> None:
    assert normalize_host("Tenant-A.Platform.Test.:443") == "tenant-a.platform.test"


def test_normalize_platform_domain_strips_leading_dot() -> None:
    assert normalize_platform_domain(".Platform.Test.") == "platform.test"
