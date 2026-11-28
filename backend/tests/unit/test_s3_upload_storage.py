from traceback import format_exception
from unittest.mock import Mock
from urllib.parse import parse_qs, urlsplit

import boto3
import pytest
from botocore.stub import Stubber

from app.config import Settings
from src.application.services.uploads import PreparedUpload, StorageUnavailableError
from src.infrastructure.storage.s3 import build_upload_storage


@pytest.fixture
def settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "local-test-key")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "local-test-secret")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "local-test-session")
    monkeypatch.setenv("AWS_EC2_METADATA_DISABLED", "true")
    return Settings(
        _env_file=None,
        s3_endpoint_url="http://127.0.0.1:9901",
        s3_region="us-west-2",
        s3_public_bucket="public-uploads",
        s3_private_bucket="private-uploads",
        s3_public_base_url="https://images.example.test/root/",
        s3_presign_ttl_seconds=130,
    )


def test_storage_with_incomplete_or_unsafe_configuration_is_unavailable(settings: Settings) -> None:
    for update in (
        {"s3_public_bucket": None},
        {"s3_private_bucket": "public-uploads"},
        {"s3_endpoint_url": "http://user:secret@storage.example.test"},
        {"s3_public_base_url": "https://images.example.test?token=secret"},
        {"s3_public_base_url": None},
    ):
        with pytest.raises(StorageUnavailableError, match=r"^Upload storage is unavailable$"):
            build_upload_storage(settings.model_copy(update=update))


async def test_put_and_delete_route_to_separate_buckets(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    session = boto3.Session(region_name=settings.s3_region)
    client = session.client("s3", endpoint_url=settings.s3_endpoint_url)
    client_factory = Mock(return_value=client)
    monkeypatch.setattr(session, "client", client_factory)
    monkeypatch.setattr(boto3, "Session", Mock(return_value=session))
    storage = build_upload_storage(settings)
    client_factory.assert_not_called()
    key = "tenant/lot/photo.png"
    image = PreparedUpload(b"fixture bytes", "image/png", "png")

    with Stubber(client) as stubber:
        for bucket in ("public-uploads", "private-uploads"):
            stubber.add_response(
                "put_object",
                {},
                {
                    "Bucket": bucket,
                    "Key": key,
                    "Body": image.data,
                    "ContentType": image.content_type,
                },
            )
            stubber.add_response("delete_object", {}, {"Bucket": bucket, "Key": key})
        for public in (True, False):
            await storage.put(key, image, public=public)
            await storage.delete(key, public=public)
        stubber.assert_no_pending_responses()

    client_factory.assert_called_once()
    config = client_factory.call_args.kwargs["config"]
    assert config.connect_timeout == 2
    assert config.read_timeout == 5
    assert config.retries["total_max_attempts"] == 2


@pytest.mark.parametrize(
    ("public", "bucket"), [(True, "public-uploads"), (False, "private-uploads")]
)
async def test_presigned_get_uses_configured_endpoint_and_bucket(
    settings: Settings, public: bool, bucket: str
) -> None:
    storage = build_upload_storage(settings)
    key = "tenant/photo 100%.jpg"
    signed = urlsplit(await storage.signed_url(key, public=public))
    assert signed.netloc == "127.0.0.1:9901"
    assert signed.path == f"/{bucket}/tenant/photo%20100%25.jpg"
    query = parse_qs(signed.query)
    assert query["X-Amz-Algorithm"] == ["AWS4-HMAC-SHA256"]
    assert query["X-Amz-Expires"] == ["130"]
    assert query["X-Amz-Credential"][0].endswith("/us-west-2/s3/aws4_request")
    assert query["X-Amz-Security-Token"] == ["local-test-session"]
    assert len(query["X-Amz-Signature"][0]) == 64
    assert query.get("response-content-disposition") == (None if public else ["attachment"])
    assert query.get("response-cache-control") == (None if public else ["no-store"])
    assert storage.public_url(key) == "https://images.example.test/root/tenant/photo%20100%25.jpg"


async def test_s3_failure_omits_storage_error_and_keys(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    session = boto3.Session(region_name=settings.s3_region)
    client = session.client("s3", endpoint_url=settings.s3_endpoint_url)
    monkeypatch.setattr(session, "client", Mock(return_value=client))
    monkeypatch.setattr(boto3, "Session", Mock(return_value=session))
    storage = build_upload_storage(settings)

    with Stubber(client) as stubber:
        stubber.add_client_error(
            "delete_object",
            service_error_code="AccessDenied",
            service_message="internal data",
            http_status_code=403,
            expected_params={"Bucket": "private-uploads", "Key": "private-key"},
        )
        with pytest.raises(
            StorageUnavailableError, match=r"^Upload storage is unavailable$"
        ) as raised:
            await storage.delete("private-key", public=False)
        stubber.assert_no_pending_responses()

    formatted = "".join(format_exception(raised.value))
    assert "internal data" not in formatted
    assert "AccessDenied" not in formatted
