import random
from io import BytesIO

import pytest
from PIL import Image, PngImagePlugin
from pypdf import PdfWriter

from src.application.services import uploads
from src.application.services.uploads import (
    MAX_DOCUMENT_BYTES,
    MAX_PHOTO_BYTES,
    InvalidUploadError,
    UploadPurpose,
    UploadTooLargeError,
    prepare_upload,
)


def image_bytes(image_format: str) -> bytes:
    output = BytesIO()
    with Image.new("RGB", (8, 5), "orange") as image:
        image.save(output, format=image_format)
    return output.getvalue()


@pytest.fixture
def pdf_bytes() -> bytes:
    output = BytesIO()
    with PdfWriter() as writer:
        writer.add_blank_page(width=72, height=72)
        writer.write(output)
    return output.getvalue()


@pytest.mark.parametrize(
    ("purpose", "image_format", "mime", "extension"),
    [
        ("lot_photo", "JPEG", "image/jpeg", "jpg"),
        ("ticket_photo", "WEBP", "image/webp", "webp"),
        ("verification_passport", "PNG", "image/png", "png"),
        ("verification_registration", "JPEG", "image/jpeg", "jpg"),
        ("verification_selfie", "PNG", "image/png", "png"),
    ],
)
def test_valid_image_is_saved_in_declared_format(
    purpose: UploadPurpose, image_format: str, mime: str, extension: str
) -> None:
    prepared = prepare_upload(image_bytes(image_format), mime, purpose)
    assert (prepared.content_type, prepared.extension) == (mime, extension)
    with Image.open(BytesIO(prepared.data)) as sanitized:
        assert (sanitized.format, sanitized.size) == (image_format, (8, 5))
        sanitized.load()


def test_jpeg_exif_orientation_is_applied_and_metadata_removed() -> None:
    output = BytesIO()
    with Image.new("RGB", (16, 8), "red") as image:
        image.paste("blue", (8, 0, 16, 8))
        exif = Image.Exif()
        exif[274] = 6  # Rotate 90 degrees clockwise.
        exif[315] = "private-artist"
        image.save(output, format="JPEG", exif=exif, icc_profile=b"private-profile")

    prepared = prepare_upload(output.getvalue(), "image/jpeg", "lot_photo")
    with Image.open(BytesIO(prepared.data)) as result:
        assert result.size == (8, 16)
        assert not result.getexif()
        assert "icc_profile" not in result.info
        red_pixel = result.getpixel((3, 2))
        blue_pixel = result.getpixel((3, 13))
        assert isinstance(red_pixel, tuple) and red_pixel[0] > 200 and red_pixel[2] < 50
        assert isinstance(blue_pixel, tuple) and blue_pixel[2] > 200 and blue_pixel[0] < 50


def test_png_metadata_removed_and_transparency_preserved() -> None:
    output = BytesIO()
    with Image.new("RGB", (4, 4), (1, 2, 3)) as image:
        metadata = PngImagePlugin.PngInfo()
        metadata.add_text("Comment", "private-comment")
        image.save(output, format="PNG", pnginfo=metadata, transparency=(1, 2, 3))

    prepared = prepare_upload(output.getvalue(), "image/png", "lot_photo")
    with Image.open(BytesIO(prepared.data)) as result:
        assert "Comment" not in result.info
        assert result.getpixel((0, 0)) == (1, 2, 3, 0)


@pytest.mark.parametrize("mime", [None, "image/jpeg", "application/octet-stream"])
def test_rejects_missing_or_mismatched_mime(mime: str | None) -> None:
    with pytest.raises(InvalidUploadError, match="Invalid upload content"):
        prepare_upload(image_bytes("PNG"), mime, "lot_photo")


@pytest.mark.parametrize("purpose", ["verification_passport", "verification_registration"])
def test_pdf_is_accepted_for_document_purposes(pdf_bytes: bytes, purpose: UploadPurpose) -> None:
    prepared = prepare_upload(pdf_bytes, "application/pdf", purpose)
    assert prepared.data == pdf_bytes
    assert (prepared.content_type, prepared.extension) == ("application/pdf", "pdf")


@pytest.mark.parametrize("purpose", ["lot_photo", "ticket_photo", "verification_selfie"])
def test_pdf_is_rejected_for_photo_purposes(pdf_bytes: bytes, purpose: UploadPurpose) -> None:
    with pytest.raises(InvalidUploadError):
        prepare_upload(pdf_bytes, "application/pdf", purpose)


@pytest.mark.parametrize(
    "purpose", ["verification_passport", "verification_registration", "verification_selfie"]
)
def test_webp_is_rejected_for_verification_purposes(purpose: UploadPurpose) -> None:
    with pytest.raises(InvalidUploadError):
        prepare_upload(image_bytes("WEBP"), "image/webp", purpose)


def test_rejects_pdf_with_plausible_header_and_eof_but_no_structure() -> None:
    with pytest.raises(InvalidUploadError):
        prepare_upload(
            b"%PDF-1.7\nunreadable content\n%%EOF\n", "application/pdf", "verification_passport"
        )


def test_rejects_pdf_exceeding_parser_limits(pdf_bytes: bytes) -> None:
    oversized_xref = pdf_bytes.replace(b"xref\n0 5\n", b"xref\n0 99999999\n")
    assert oversized_xref != pdf_bytes
    with pytest.raises(InvalidUploadError):
        prepare_upload(oversized_xref, "application/pdf", "verification_passport")


@pytest.mark.parametrize(
    ("image_format", "mime"), [("JPEG", "image/jpeg"), ("PNG", "image/png"), ("WEBP", "image/webp")]
)
def test_rejects_truncated_images(image_format: str, mime: str) -> None:
    with pytest.raises(InvalidUploadError):
        prepare_upload(image_bytes(image_format)[:-4], mime, "lot_photo")


def test_rejects_animated_images() -> None:
    output = BytesIO()
    with Image.new("RGB", (8, 8), "red") as red, Image.new("RGB", (8, 8), "blue") as blue:
        red.save(output, format="WEBP", save_all=True, append_images=[blue], duration=50)
    with pytest.raises(InvalidUploadError):
        prepare_upload(output.getvalue(), "image/webp", "lot_photo")


def test_decoded_pixel_limit_is_checked(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(uploads, "_MAX_IMAGE_PIXELS", 39)
    with pytest.raises(InvalidUploadError):
        prepare_upload(image_bytes("PNG"), "image/png", "lot_photo")


@pytest.mark.parametrize(
    ("purpose", "limit"),
    [("lot_photo", MAX_PHOTO_BYTES), ("verification_passport", MAX_DOCUMENT_BYTES)],
)
def test_size_is_checked_before_decode(purpose: UploadPurpose, limit: int) -> None:
    with pytest.raises(UploadTooLargeError):
        prepare_upload(b"x" * (limit + 1), "image/jpeg", purpose)


def test_size_is_checked_after_reencoding(monkeypatch: pytest.MonkeyPatch) -> None:
    rng = random.Random(42)
    output = BytesIO()
    with Image.frombytes("RGB", (64, 64), rng.randbytes(64 * 64 * 3)) as image:
        image.save(output, format="JPEG", quality=10)

    data = output.getvalue()
    assert len(prepare_upload(data, "image/jpeg", "lot_photo").data) > len(data)
    monkeypatch.setattr(uploads, "MAX_PHOTO_BYTES", len(data))
    with pytest.raises(UploadTooLargeError):
        prepare_upload(data, "image/jpeg", "lot_photo")
