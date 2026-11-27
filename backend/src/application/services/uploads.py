"""Content validation and the storage interface for uploaded files."""

import re
from collections.abc import Buffer
from dataclasses import dataclass
from io import BytesIO
from struct import error as StructError
from threading import BoundedSemaphore
from typing import Literal, Protocol

from PIL import Image, ImageOps
from pypdf import PdfReader
from pypdf.errors import PyPdfError

type UploadPurpose = Literal[
    "lot_photo",
    "ticket_photo",
    "verification_passport",
    "verification_registration",
    "verification_selfie",
]

MAX_DOCUMENT_BYTES = 10 * 1024 * 1024
MAX_PHOTO_BYTES = 5 * 1024 * 1024
_MAX_IMAGE_PIXELS = 24_000_000
_CONTENT_SLOTS = BoundedSemaphore(2)
_IMAGE_TYPES = {
    "image/jpeg": ("JPEG", "jpg"),
    "image/png": ("PNG", "png"),
    "image/webp": ("WEBP", "webp"),
}
_PNG_END = b"\x00\x00\x00\x00IEND\xaeB`\x82"
_PDF_HEADER = re.compile(rb"%PDF-(?:1\.[0-7]|2\.0)(?:\r\n?|\n)")


class InvalidUploadError(ValueError):
    """Upload does not match its declared type or purpose."""


class UploadTooLargeError(ValueError):
    """Upload exceeds the byte limit for its purpose."""


class StorageUnavailableError(RuntimeError):
    """Upload processing or object storage is unavailable."""


@dataclass(frozen=True, slots=True)
class PreparedUpload:
    data: bytes
    content_type: str
    extension: str


class UploadStorage(Protocol):
    async def put(self, key: str, upload: PreparedUpload, *, public: bool) -> None: ...

    async def signed_url(self, key: str, *, public: bool) -> str: ...

    async def delete(self, key: str, *, public: bool) -> None: ...

    def public_url(self, key: str) -> str: ...


def prepare_upload(
    data: bytes, declared_type: str | None, purpose: UploadPurpose
) -> PreparedUpload:
    is_photo = purpose in ("lot_photo", "ticket_photo")
    byte_limit = MAX_PHOTO_BYTES if is_photo else MAX_DOCUMENT_BYTES
    if len(data) > byte_limit:
        raise UploadTooLargeError("Upload exceeds the size limit")

    mime = (declared_type or "").partition(";")[0].strip().lower()
    is_pdf = mime == "application/pdf" and purpose in (
        "verification_passport",
        "verification_registration",
    )
    if not is_pdf and (mime not in _IMAGE_TYPES or (mime == "image/webp" and not is_photo)):
        raise InvalidUploadError("Invalid upload content")

    if not _CONTENT_SLOTS.acquire(blocking=False):
        raise StorageUnavailableError("Upload processing is unavailable")
    try:
        if is_pdf:
            _validate_pdf(data)
            return PreparedUpload(data, mime, "pdf")

        image_format, extension = _IMAGE_TYPES[mime]
        image_data = _prepare_image(data, image_format, byte_limit)
        return PreparedUpload(image_data, mime, extension)
    finally:
        _CONTENT_SLOTS.release()


def _validate_pdf(data: bytes) -> None:
    if not _PDF_HEADER.match(data) or not data.rstrip(b"\x00\t\n\f\r ").endswith(b"%%EOF"):
        raise InvalidUploadError("Invalid upload content")

    try:
        with PdfReader(BytesIO(data), strict=True, xref_stream_maximum_entries=50_000) as document:
            # Walk page references without rendering or decoding page content streams.
            if document.is_encrypted or len(document.pages) == 0:
                raise InvalidUploadError("Invalid upload content")
    except (
        PyPdfError,
        AttributeError,
        OSError,
        StructError,
        ValueError,
        TypeError,
        LookupError,
        RecursionError,
        OverflowError,
    ):
        raise InvalidUploadError("Invalid upload content") from None


class _BoundedImageOutput(BytesIO):
    def __init__(self, limit: int) -> None:
        super().__init__()
        self.limit = limit

    def write(self, data: Buffer, /) -> int:
        if self.tell() + memoryview(data).nbytes > self.limit:
            raise UploadTooLargeError("Upload exceeds the size limit")
        return super().write(data)


def _prepare_image(data: bytes, image_format: str, byte_limit: int) -> bytes:
    if image_format == "PNG" and not data.endswith(_PNG_END):
        raise InvalidUploadError("Invalid upload content")

    try:
        with Image.open(BytesIO(data), formats=(image_format,)) as probe:
            if probe.width * probe.height > _MAX_IMAGE_PIXELS:
                raise InvalidUploadError("Invalid upload content")
            if getattr(probe, "n_frames", 1) != 1:
                raise InvalidUploadError("Invalid upload content")
            probe.verify()

        with Image.open(BytesIO(data), formats=(image_format,)) as source:
            image: Image.Image = source
            ImageOps.exif_transpose(image, in_place=True)
            if image_format == "JPEG" and image.mode not in ("L", "RGB"):
                image = image.convert("RGB")
            elif image.has_transparency_data and "A" not in image.getbands():
                image = image.convert("RGBA")
            image.info.clear()
            with _BoundedImageOutput(byte_limit) as output:
                image.save(output, format=image_format)
                return output.getvalue()
    except UploadTooLargeError:
        raise
    except (Image.DecompressionBombError, OSError, SyntaxError, ValueError, EOFError, StructError):
        raise InvalidUploadError("Invalid upload content") from None
