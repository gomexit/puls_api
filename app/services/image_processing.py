"""Validacija i obrada slika za modul SLIKE (faza 0, bez DB zavisnosti).

Klijentu se ne veruje: format se proverava po sadrzaju (magic bajtovi + Pillow), a ne
po ekstenziji ili MIME-u. Slika se uvek ponovo kodira: okrece se po EXIF orijentaciji,
smanjuje na najvise 1200 px po duzoj strani i snima BEZ metapodataka (EXIF, GPS, ICC
komentari), pa u bazu nikad ne ulazi originalni fajl. Sadrzaj se nikad ne loguje."""

import hashlib
import io
import re
import warnings
from dataclasses import dataclass

from PIL import Image, ImageOps

from app.core.exceptions import ImageTooLargeError, InvalidImageError, ValidationBusinessError
from app.models.slika import SLIKA_MAX_DIMENZIJA, SLIKA_MIME_JPEG, SLIKA_MIME_PNG
from app.services.onboarding_pdf import sanitize_filename

NAZIV_MAX = 200
ORIGINALNI_NAZIV_MAX = 255
BYTES_PER_MB = 1024 * 1024
JPEG_QUALITY = 85
# Zastita od "decompression bomb" slika: najvise 40 megapiksela pre smanjivanja.
MAX_SOURCE_PIXELS = 40_000_000

_JPEG_MAGIC = b"\xff\xd8\xff"
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_EXTENSIONS = {
    SLIKA_MIME_JPEG: (".jpg", ".jpeg"),
    SLIKA_MIME_PNG: (".png",),
}
_ALLOWED_UPLOAD_MIME = frozenset({SLIKA_MIME_JPEG, SLIKA_MIME_PNG, "image/jpg", "application/octet-stream"})
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


@dataclass(frozen=True)
class ProcessedImage:
    content: bytes
    sha256: str
    size: int
    width: int
    height: int
    mime_type: str
    original_name: str


def max_size_bytes(max_size_mb: int) -> int:
    return max_size_mb * BYTES_PER_MB


def read_limited(stream, max_bytes: int) -> bytes:
    """Cita najvise max_bytes + 1 bajt; veci upload se odbija bez ucitavanja u celini."""
    data = stream.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ImageTooLargeError(
            f"Slika je veća od dozvoljene veličine ({max_bytes // BYTES_PER_MB} MB)."
        )
    return data


def _media_type(content_type: str | None) -> str:
    if not content_type:
        return ""
    return content_type.split(";", 1)[0].strip().lower()


def _detect_mime(content: bytes) -> str | None:
    if content.startswith(_JPEG_MAGIC):
        return SLIKA_MIME_JPEG
    if content.startswith(_PNG_MAGIC):
        return SLIKA_MIME_PNG
    return None


def validate_name(naziv: str | None) -> str:
    value = (naziv or "").strip()
    if not value:
        raise ValidationBusinessError("Naziv slike je obavezan.")
    if len(value) > NAZIV_MAX:
        raise ValidationBusinessError(f"Naziv može imati najviše {NAZIV_MAX} karaktera.")
    if _CONTROL_CHARS.search(value):
        raise ValidationBusinessError("Naziv slike sadrži nevažeće kontrolne znakove.")
    return value


def process_image_upload(
    content: bytes,
    filename: str | None,
    content_type: str | None,
    max_dimension: int = SLIKA_MAX_DIMENZIJA,
) -> ProcessedImage:
    """Validira vec procitan (i velicinski ogranicen) upload i vraca ponovo kodiranu
    sliku. Poredak: prazno -> ime -> MIME -> magic -> ekstenzija -> Pillow -> obrada."""
    if len(content) == 0:
        raise InvalidImageError("Fajl slike je prazan.")

    name = sanitize_filename(filename)
    if not name:
        raise InvalidImageError("Naziv fajla nije ispravan.")
    if len(name) > ORIGINALNI_NAZIV_MAX:
        raise InvalidImageError(f"Naziv fajla može imati najviše {ORIGINALNI_NAZIV_MAX} karaktera.")

    if _media_type(content_type) not in _ALLOWED_UPLOAD_MIME:
        raise InvalidImageError("Dozvoljene su samo slike u formatu JPEG ili PNG.")

    mime = _detect_mime(content)
    if mime is None:
        raise InvalidImageError("Dozvoljene su samo slike u formatu JPEG ili PNG.")
    if not name.lower().endswith(_EXTENSIONS[mime]):
        raise InvalidImageError("Ekstenzija fajla ne odgovara sadržaju slike.")

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(content)) as probe:
                if probe.width * probe.height > MAX_SOURCE_PIXELS:
                    raise InvalidImageError("Slika ima previše piksela.")
                probe.verify()
            with Image.open(io.BytesIO(content)) as img:
                img.load()
                expected_format = "JPEG" if mime == SLIKA_MIME_JPEG else "PNG"
                if img.format != expected_format:
                    raise InvalidImageError("Dozvoljene su samo slike u formatu JPEG ili PNG.")
                processed = _normalize(img, mime, max_dimension)
    except InvalidImageError:
        raise
    except Exception as exc:  # Pillow baca razlicite izuzetke za ostecen sadrzaj
        raise InvalidImageError("Slika je oštećena ili ne može da se otvori.") from exc

    out_bytes, width, height = processed
    return ProcessedImage(
        content=out_bytes,
        sha256=hashlib.sha256(out_bytes).hexdigest(),
        size=len(out_bytes),
        width=width,
        height=height,
        mime_type=mime,
        original_name=name,
    )


def _normalize(img: Image.Image, mime: str, max_dimension: int) -> tuple[bytes, int, int]:
    img = ImageOps.exif_transpose(img)
    if max(img.width, img.height) > max_dimension:
        img.thumbnail((max_dimension, max_dimension), Image.Resampling.LANCZOS)

    buf = io.BytesIO()
    if mime == SLIKA_MIME_JPEG:
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        img.save(buf, format="JPEG", quality=JPEG_QUALITY, optimize=True)
    else:
        if img.mode not in ("RGB", "RGBA", "L", "LA", "P"):
            img = img.convert("RGBA")
        img.save(buf, format="PNG", optimize=True)
    return buf.getvalue(), int(img.width), int(img.height)
