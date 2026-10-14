"""Validacija PDF-a i metadata za modul ONBOARDING DOKUMENTI (bez DB zavisnosti).

Sve provere se rade na backendu; klijentu se ne veruje (ni MIME, ni ekstenzija, ni
velicina, ni hash). Sadrzaj PDF-a, hash ni multipart payload se nikada ne loguju."""

import hashlib
import io
import re
import urllib.parse
from dataclasses import dataclass
from typing import BinaryIO

from pypdf import PdfReader

from app.core.exceptions import (
    InvalidPdfDocumentError,
    PdfDocumentTooLargeError,
    ValidationBusinessError,
)
from app.models.onboarding_dokument import ONB_DOKUMENT_MIME_PDF

NAZIV_MAX = 200
OPIS_MAX = 4000
ORIGINALNI_NAZIV_MAX = 255
# REDOSLED je NUMBER(10,0) u Oracle-u: najvise 10 cifara.
REDOSLED_MIN = 1
REDOSLED_MAX = 9_999_999_999
PDF_MAGIC = b"%PDF-"
BYTES_PER_MB = 1024 * 1024

_ALLOWED_UPLOAD_MIME = frozenset({ONB_DOKUMENT_MIME_PDF, "application/octet-stream"})
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")
_PATH_SEPARATORS = re.compile(r"[\\/]")


@dataclass(frozen=True)
class ValidatedPdf:
    content: bytes
    sha256: str
    size: int
    original_name: str
    mime_type: str = ONB_DOKUMENT_MIME_PDF


@dataclass(frozen=True)
class DocumentMetadata:
    naziv: str
    opis: str | None
    redosled: int


def max_size_bytes(max_size_mb: int) -> int:
    return max_size_mb * BYTES_PER_MB


def read_limited(stream: BinaryIO, max_bytes: int) -> bytes:
    """Cita najvise max_bytes + 1 bajt, da prevelik upload nikad ne bude ucitan u memoriju
    u celini. Ako je procitano vise od limita, odbija se sa PDF_DOCUMENT_TOO_LARGE."""
    data = stream.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise PdfDocumentTooLargeError(
            f"PDF dokument je veći od dozvoljene veličine ({max_bytes // BYTES_PER_MB} MB)."
        )
    return data


def sanitize_filename(raw: str | None) -> str:
    """Izdvaja samo ime fajla: bez putanje (/, \\), bez kontrolnih znakova (CR/LF, NUL...)
    i bez razmaka na krajevima. Rezultat je bezbedan za cuvanje i za HTTP header."""
    if raw is None:
        return ""
    # Uklanja kontrolne znakove PRE izdvajanja imena, da CR/LF ne moze da se sakrije oko '/'.
    cleaned = _CONTROL_CHARS.sub("", raw)
    parts = _PATH_SEPARATORS.split(cleaned)
    name = parts[-1].strip() if parts else ""
    # Skriveni/relativni segmenti nisu validno ime fajla.
    if name in ("", ".", ".."):
        return ""
    return name


def _media_type(content_type: str | None) -> str:
    if not content_type:
        return ""
    return content_type.split(";", 1)[0].strip().lower()


def validate_pdf_upload(
    content: bytes,
    filename: str | None,
    content_type: str | None,
) -> ValidatedPdf:
    """Validira vec procitan (i velicinski ogranicen) upload. Vraca ValidatedPdf ili baca
    InvalidPdfDocumentError. Poredak: prazno -> ime -> ekstenzija -> MIME -> magic -> pypdf."""
    if len(content) == 0:
        raise InvalidPdfDocumentError("PDF fajl je prazan.")

    name = sanitize_filename(filename)
    if not name:
        raise InvalidPdfDocumentError("Naziv fajla nije ispravan.")
    if len(name) > ORIGINALNI_NAZIV_MAX:
        raise InvalidPdfDocumentError(
            f"Naziv fajla može imati najviše {ORIGINALNI_NAZIV_MAX} karaktera."
        )
    if not name.lower().endswith(".pdf"):
        raise InvalidPdfDocumentError("Dozvoljeni su samo fajlovi sa ekstenzijom .pdf.")

    media_type = _media_type(content_type)
    if media_type not in _ALLOWED_UPLOAD_MIME:
        raise InvalidPdfDocumentError("Tip sadržaja fajla mora biti application/pdf.")

    if not content.startswith(PDF_MAGIC):
        raise InvalidPdfDocumentError("Sadržaj fajla nije PDF.")

    # application/octet-stream se prihvata SAMO jer sadrzaj prolazi proveru ispod;
    # u bazu se uvek upisuje application/pdf.
    try:
        reader = PdfReader(io.BytesIO(content))
        if reader.is_encrypted:
            raise InvalidPdfDocumentError("PDF zaštićen lozinkom nije dozvoljen.")
        page_count = len(reader.pages)
    except InvalidPdfDocumentError:
        raise
    except Exception as exc:  # pypdf baca razlicite izuzetke za koruptovan sadrzaj
        raise InvalidPdfDocumentError("PDF fajl je oštećen ili ne može da se otvori.") from exc
    if page_count < 1:
        raise InvalidPdfDocumentError("PDF ne sadrži nijednu stranicu.")

    return ValidatedPdf(
        content=content,
        sha256=hashlib.sha256(content).hexdigest(),
        size=len(content),
        original_name=name,
    )


def strip_text(value):
    """Pydantic BEFORE validator: trim se primenjuje pre provere duzine (Field
    min_length/max_length), tako da OpenAPI ogranicenje i stvarna validacija ostaju
    usaglasena. Ne-string vrednosti se ne diraju (pydantic ih odbija)."""
    return value.strip() if isinstance(value, str) else value


def strip_text_or_none(value):
    """Kao strip_text, ali prazan string (posle trima) postaje None (opis)."""
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value


def validate_metadata(naziv: str | None, opis: str | None, redosled: int | None) -> DocumentMetadata:
    """Trim + provera duzina. Greske su VALIDATION_ERROR (422), nikad 500."""
    naziv = (naziv or "").strip()
    if not naziv:
        raise ValidationBusinessError("Naziv dokumenta je obavezan.")
    if len(naziv) > NAZIV_MAX:
        raise ValidationBusinessError(f"Naziv može imati najviše {NAZIV_MAX} karaktera.")

    opis_norm: str | None = None
    if opis is not None:
        opis_norm = opis.strip()
        if len(opis_norm) > OPIS_MAX:
            raise ValidationBusinessError(f"Opis može imati najviše {OPIS_MAX} karaktera.")
        if not opis_norm:
            opis_norm = None

    if redosled is None or isinstance(redosled, bool):
        raise ValidationBusinessError("Redosled je obavezan.")
    if not REDOSLED_MIN <= int(redosled) <= REDOSLED_MAX:
        raise ValidationBusinessError(
            f"Redosled mora biti ceo broj od {REDOSLED_MIN} do {REDOSLED_MAX}."
        )
    return DocumentMetadata(naziv=naziv, opis=opis_norm, redosled=int(redosled))


def content_disposition_inline(filename: str) -> str:
    """inline; filename="<ascii fallback>"; filename*=UTF-8''<percent-encoded>.
    Ime je vec sanitizovano pri upload-u, ali se ovde ponovo cisti (odbrana u dubinu) i
    kodira tako da u headeru ne moze da se pojavi CR/LF, navodnik ni razdvajac putanje."""
    safe = sanitize_filename(filename) or "dokument.pdf"
    ascii_fallback = re.sub(r'[^A-Za-z0-9._ -]', "_", safe).strip() or "dokument.pdf"
    encoded = urllib.parse.quote(safe, safe="")
    return f"inline; filename=\"{ascii_fallback}\"; filename*=UTF-8''{encoded}"
