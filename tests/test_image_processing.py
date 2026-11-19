"""Validacija i obrada slika (faza 0): format po sadrzaju, smanjivanje na 1200 px,
uklanjanje metapodataka, ogranicenje velicine."""

import io

import pytest
from PIL import Image

from app.core.exceptions import (
    ImageTooLargeError,
    InvalidImageError,
    ValidationBusinessError,
)
from app.services.image_processing import (
    MAX_SOURCE_PIXELS,
    process_image_upload,
    read_limited,
    validate_name,
)
from tests.image_fakes import make_image_bytes


def _open(data: bytes) -> Image.Image:
    return Image.open(io.BytesIO(data))


def test_small_jpeg_is_kept_size_and_reencoded():
    result = process_image_upload(make_image_bytes("JPEG", (100, 80)), "logo.jpg", "image/jpeg")
    assert (result.width, result.height) == (100, 80)
    assert result.mime_type == "image/jpeg"
    assert result.size == len(result.content)
    assert len(result.sha256) == 64
    assert _open(result.content).format == "JPEG"


def test_png_keeps_png_and_transparency_mode():
    result = process_image_upload(make_image_bytes("PNG", (50, 50)), "ikona.png", "image/png")
    assert result.mime_type == "image/png"
    img = _open(result.content)
    assert img.format == "PNG"
    assert img.mode in ("RGBA", "P", "RGB")


@pytest.mark.parametrize("size,expected", [((3000, 1500), (1200, 600)), ((800, 2400), (400, 1200))])
def test_large_image_is_resized_to_1200_on_longer_side(size, expected):
    result = process_image_upload(make_image_bytes("JPEG", size), "velika.jpeg", "image/jpeg")
    assert (result.width, result.height) == expected
    assert _open(result.content).size == expected


def test_exif_and_gps_metadata_is_removed():
    exif = Image.Exif()
    exif[0x010F] = "Proizvodjac"  # Make
    exif[0x8825] = {1: "N"}  # GPS IFD
    data = make_image_bytes("JPEG", (60, 40), exif=exif.tobytes())
    assert _open(data).getexif()  # izvor ima EXIF
    result = process_image_upload(data, "foto.jpg", "image/jpeg")
    assert not _open(result.content).getexif()


def test_exif_orientation_is_applied():
    exif = Image.Exif()
    exif[0x0112] = 6  # rotacija 90 stepeni
    data = make_image_bytes("JPEG", (200, 100), exif=exif.tobytes())
    result = process_image_upload(data, "foto.jpg", "image/jpeg")
    assert (result.width, result.height) == (100, 200)


def test_octet_stream_is_accepted_when_content_is_image():
    result = process_image_upload(make_image_bytes("PNG"), "a.png", "application/octet-stream")
    assert result.mime_type == "image/png"


@pytest.mark.parametrize(
    "data,name,ctype,message",
    [
        (b"", "a.jpg", "image/jpeg", "prazan"),
        (make_image_bytes("JPEG"), "../", "image/jpeg", "Naziv fajla"),
        (make_image_bytes("JPEG"), "a.jpg", "text/html", "JPEG ili PNG"),
        (b"%PDF-1.7 nesto", "a.jpg", "image/jpeg", "JPEG ili PNG"),
        (make_image_bytes("GIF"), "a.gif", "image/jpeg", "JPEG ili PNG"),
        (make_image_bytes("PNG"), "a.jpg", "image/jpeg", "Ekstenzija"),
        (b"\xff\xd8\xff\xe0" + b"\x00" * 50, "a.jpg", "image/jpeg", "oštećena"),
    ],
)
def test_invalid_uploads_are_rejected(data, name, ctype, message):
    with pytest.raises(InvalidImageError) as exc:
        process_image_upload(data, name, ctype)
    assert message in exc.value.message


def test_too_many_pixels_rejected(monkeypatch):
    monkeypatch.setattr("app.services.image_processing.MAX_SOURCE_PIXELS", 100 * 100 - 1)
    with pytest.raises(InvalidImageError):
        process_image_upload(make_image_bytes("PNG", (100, 100)), "a.png", "image/png")
    assert MAX_SOURCE_PIXELS == 40_000_000


def test_read_limited_rejects_bigger_than_limit():
    assert read_limited(io.BytesIO(b"x" * 10), 10) == b"x" * 10
    with pytest.raises(ImageTooLargeError):
        read_limited(io.BytesIO(b"x" * 11), 10)


def test_validate_name():
    assert validate_name("  Logo  ") == "Logo"
    for bad in ("", "   ", "x" * 201, "a\nb"):
        with pytest.raises(ValidationBusinessError):
            validate_name(bad)
