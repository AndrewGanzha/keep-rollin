"""S3 and S3-compatible object storage for uploads."""

import asyncio
from collections.abc import Callable
from threading import BoundedSemaphore, Lock
from typing import TYPE_CHECKING
from urllib.parse import quote, urlsplit

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from app.config import Settings
from src.application.services.uploads import PreparedUpload, StorageUnavailableError, UploadStorage

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client
    from mypy_boto3_s3.type_defs import GetObjectRequestTypeDef

_STORAGE_SLOTS = BoundedSemaphore(4)


def build_upload_storage(settings: Settings) -> UploadStorage:
    public_bucket = settings.s3_public_bucket
    private_bucket = settings.s3_private_bucket
    public_base_url = settings.s3_public_base_url
    endpoint_url = settings.s3_endpoint_url
    if (
        not public_bucket
        or not private_bucket
        or public_bucket == private_bucket
        or not public_base_url
        or not _is_http_url(public_base_url)
        or (endpoint_url is not None and not _is_http_url(endpoint_url))
    ):
        raise StorageUnavailableError("Upload storage is unavailable")

    return _S3UploadStorage(
        settings,
        public_bucket=public_bucket,
        private_bucket=private_bucket,
        public_base_url=public_base_url,
    )


def _is_http_url(value: str) -> bool:
    try:
        url = urlsplit(value)
        return (
            url.scheme in ("http", "https")
            and bool(url.hostname)
            and url.port != 0
            and url.username is None
            and not url.query
            and not url.fragment
        )
    except ValueError:
        return False


class _S3UploadStorage:
    def __init__(
        self,
        settings: Settings,
        *,
        public_bucket: str,
        private_bucket: str,
        public_base_url: str,
    ) -> None:
        self._public_bucket = public_bucket
        self._private_bucket = private_bucket
        self._public_base_url = public_base_url.rstrip("/")
        self._endpoint_url = settings.s3_endpoint_url
        self._region = settings.s3_region
        self._presign_ttl = settings.s3_presign_ttl_seconds
        self._client: S3Client | None = None
        self._client_lock = Lock()

    def _get_client(self) -> "S3Client":
        with self._client_lock:
            if self._client is None:
                session = boto3.Session(region_name=self._region)
                self._client = session.client(
                    "s3",
                    endpoint_url=self._endpoint_url,
                    config=Config(
                        signature_version="s3v4",
                        connect_timeout=2,
                        read_timeout=5,
                        retries={"mode": "standard", "total_max_attempts": 2},
                        s3={"addressing_style": "path" if self._endpoint_url else "auto"},
                        request_checksum_calculation="when_required",
                        response_checksum_validation="when_required",
                    ),
                )
            return self._client

    def _bucket(self, public: bool) -> str:
        return self._public_bucket if public else self._private_bucket

    def _run[T](self, operation: Callable[["S3Client"], T]) -> T:
        if not _STORAGE_SLOTS.acquire(blocking=False):
            raise StorageUnavailableError("Upload storage is unavailable")
        try:
            return operation(self._get_client())
        except (BotoCoreError, ClientError, OSError, ValueError):
            raise StorageUnavailableError("Upload storage is unavailable") from None
        finally:
            _STORAGE_SLOTS.release()

    async def put(self, key: str, upload: PreparedUpload, *, public: bool) -> None:
        await asyncio.to_thread(
            self._run,
            lambda client: client.put_object(
                Bucket=self._bucket(public),
                Key=key,
                Body=upload.data,
                ContentType=upload.content_type,
            ),
        )

    async def signed_url(self, key: str, *, public: bool) -> str:
        params: GetObjectRequestTypeDef = {"Bucket": self._bucket(public), "Key": key}
        if not public:
            params["ResponseContentDisposition"] = "attachment"
            params["ResponseCacheControl"] = "no-store"
        return await asyncio.to_thread(
            self._run,
            lambda client: client.generate_presigned_url(
                "get_object",
                Params=params,
                ExpiresIn=self._presign_ttl,
                HttpMethod="GET",
            ),
        )

    async def delete(self, key: str, *, public: bool) -> None:
        await asyncio.to_thread(
            self._run,
            lambda client: client.delete_object(Bucket=self._bucket(public), Key=key),
        )

    def public_url(self, key: str) -> str:
        return f"{self._public_base_url}/{quote(key, safe='/')}"
