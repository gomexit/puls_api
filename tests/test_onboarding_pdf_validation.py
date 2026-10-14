"""PDF validacija i metadata za modul ONBOARDING DOKUMENTI (bez baze)."""

import hashlib
import io

import pytest

from app.core.config import Settings
from app.core.exceptions import (
    InvalidPdfDocumentError,
    PdfDocumentTooLargeError,
    ValidationBusinessError,
)
from app.services.onboarding_document_service import OnboardingDocumentService
from app.services.onboarding_pdf import (
    content_disposition_inline,
    read_limited,
    sanitize_filename,
    validate_metadata,
    validate_pdf_upload,
)
from tests.onboarding_document_fakes import make_pdf_bytes


def _valid(name="dokument.pdf", content_type="application/pdf", pages=1):
    return validate_pdf_upload(make_pdf_bytes(pages), name, content_type)


# ------------------------------------------------------------------ happy path
def test_valid_pdf_is_accepted_and_hashed_on_backend():
    data = make_pdf_bytes()
    result = validate_pdf_upload(data, "Pravilnik.PDF", "application/pdf")
    assert result.size == len(data)
    assert result.sha256 == hashlib.sha256(data).hexdigest()
    assert result.mime_type == "application/pdf"
    assert result.original_name == "Pravilnik.PDF"


def test_extension_is_case_insensitive():
    assert _valid("a.PdF").original_name == "a.PdF"


def test_octet_stream_accepted_only_for_valid_pdf_and_stored_as_pdf():
    result = _valid(content_type="application/octet-stream")
    assert result.mime_type == "application/pdf"


def test_content_type_parameters_are_ignored():
    assert _valid(content_type="application/pdf; charset=binary").size > 0


def test_octet_stream_with_garbage_is_rejected():
    with pytest.raises(InvalidPdfDocumentError):
        validate_pdf_upload(b"not a pdf at all", "a.pdf", "application/octet-stream")


# --------------------------------------------------------------------- rejects
def test_empty_file_rejected():
    with pytest.raises(InvalidPdfDocumentError):
        validate_pdf_upload(b"", "a.pdf", "application/pdf")


@pytest.mark.parametrize("name", ["a.txt", "a.pdf.exe", "a", "pdf", "a.pdf.txt"])
def test_wrong_extension_rejected(name):
    with pytest.raises(InvalidPdfDocumentError):
        validate_pdf_upload(make_pdf_bytes(), name, "application/pdf")


@pytest.mark.parametrize("ctype", ["text/plain", "image/png", "application/json", "", None])
def test_wrong_mime_rejected(ctype):
    with pytest.raises(InvalidPdfDocumentError):
        validate_pdf_upload(make_pdf_bytes(), "a.pdf", ctype)


def test_missing_pdf_magic_rejected():
    with pytest.raises(InvalidPdfDocumentError):
        validate_pdf_upload(b"GIF89a" + make_pdf_bytes(), "a.pdf", "application/pdf")


def test_corrupted_pdf_rejected():
    corrupted = b"%PDF-1.7\n1 0 obj << /Broken >> \nthis is not a pdf structure"
    with pytest.raises(InvalidPdfDocumentError):
        validate_pdf_upload(corrupted, "a.pdf", "application/pdf")


def test_truncated_pdf_rejected():
    data = make_pdf_bytes()
    with pytest.raises(InvalidPdfDocumentError):
        validate_pdf_upload(data[: len(data) // 2], "a.pdf", "application/pdf")


def test_encrypted_pdf_rejected():
    with pytest.raises(InvalidPdfDocumentError):
        validate_pdf_upload(make_pdf_bytes(password="tajna"), "a.pdf", "application/pdf")


def test_pdf_without_pages_rejected():
    with pytest.raises(InvalidPdfDocumentError):
        validate_pdf_upload(make_pdf_bytes(pages=0), "a.pdf", "application/pdf")


def test_original_name_over_255_rejected():
    with pytest.raises(InvalidPdfDocumentError):
        validate_pdf_upload(make_pdf_bytes(), ("a" * 252) + ".pdf", "application/pdf")


def test_original_name_exactly_255_accepted():
    assert len(_valid(("a" * 251) + ".pdf").original_name) == 255


# ------------------------------------------------------------------- size limit
def test_exactly_limit_passes_and_limit_plus_one_rejected():
    limit = 1024
    assert read_limited(io.BytesIO(b"x" * limit), limit) == b"x" * limit
    with pytest.raises(PdfDocumentTooLargeError):
        read_limited(io.BytesIO(b"x" * (limit + 1)), limit)


def test_read_limited_never_reads_more_than_limit_plus_one():
    class CountingStream(io.BytesIO):
        requested = 0

        def read(self, size=-1):
            CountingStream.requested = size
            return super().read(size)

    stream = CountingStream(b"x" * 10_000)
    with pytest.raises(PdfDocumentTooLargeError):
        read_limited(stream, 100)
    assert CountingStream.requested == 101


def test_service_parse_upload_uses_configured_limit():
    pdf = make_pdf_bytes()
    settings = Settings(_env_file=None, onboarding_pdf_max_size_mb=1)
    service = OnboardingDocumentService(db=None, repository=object(), audit_service=object(), settings=settings)
    assert service.parse_upload(io.BytesIO(pdf), "a.pdf", "application/pdf").size == len(pdf)
    big = pdf + b"\n" + b"0" * (1024 * 1024)
    with pytest.raises(PdfDocumentTooLargeError):
        service.parse_upload(io.BytesIO(big), "a.pdf", "application/pdf")


def test_size_setting_default_and_bounds():
    assert Settings(_env_file=None).onboarding_pdf_max_size_mb == 20
    with pytest.raises(ValueError):
        Settings(_env_file=None, onboarding_pdf_max_size_mb=0)
    with pytest.raises(ValueError):
        Settings(_env_file=None, onboarding_pdf_max_size_mb=-5)


# ----------------------------------------------------------- filename handling
@pytest.mark.parametrize(
    "raw, expected",
    [
        ("../../etc/passwd.pdf", "passwd.pdf"),
        ("..\\..\\windows\\a.pdf", "a.pdf"),
        ("C:\\fakepath\\ugovor.pdf", "ugovor.pdf"),
        ("a\r\nSet-Cookie: x=1.pdf", "aSet-Cookie: x=1.pdf"),
        ("  ime.pdf  ", "ime.pdf"),
        ("a\x00b.pdf", "ab.pdf"),
        ("..", ""),
        (".", ""),
        ("", ""),
        (None, ""),
    ],
)
def test_sanitize_filename(raw, expected):
    assert sanitize_filename(raw) == expected


def test_path_traversal_and_crlf_name_is_stored_safely():
    result = validate_pdf_upload(make_pdf_bytes(), "..\\..\\x\r\ny/ime\n.pdf", "application/pdf")
    assert "/" not in result.original_name and "\\" not in result.original_name
    assert "\r" not in result.original_name and "\n" not in result.original_name
    assert result.original_name == "ime.pdf"


def test_content_disposition_is_header_safe():
    header = content_disposition_inline('x"; foo=\r\nbar/ćč evil.pdf')
    assert "\r" not in header and "\n" not in header
    assert header.startswith("inline; filename=")
    assert "filename*=UTF-8''" in header
    ascii_part = header.split("filename*=")[0]
    assert ascii_part.count('"') == 2  # navodnici u imenu su zamenjeni
    assert "ć" not in header and "č" not in header


def test_content_disposition_encodes_serbian_letters():
    header = content_disposition_inline("Pravilnik šđčćž.pdf")
    assert "%C5%A1" in header  # š


# ---------------------------------------------------------------------- metadata
def test_metadata_trims_and_normalizes():
    md = validate_metadata("  Naziv  ", "  opis  ", 3)
    assert (md.naziv, md.opis, md.redosled) == ("Naziv", "opis", 3)


def test_metadata_empty_opis_becomes_none():
    assert validate_metadata("N", "   ", 1).opis is None
    assert validate_metadata("N", None, 1).opis is None


def test_metadata_limits():
    assert validate_metadata("a" * 200, "b" * 4000, 1).naziv == "a" * 200
    for args in [("a" * 201, None, 1), ("N", "b" * 4001, 1), ("   ", None, 1), (None, None, 1)]:
        with pytest.raises(ValidationBusinessError):
            validate_metadata(*args)


@pytest.mark.parametrize("redosled", [0, -1, None, True])
def test_metadata_redosled_must_be_positive(redosled):
    with pytest.raises(ValidationBusinessError):
        validate_metadata("N", None, redosled)


# ---------------------------------------------- granice REDOSLED (NUMBER(10,0))
REDOSLED_MAX = 9_999_999_999


def test_redosled_bounds_constants_match_oracle_number_10_0():
    from app.services import onboarding_pdf

    assert onboarding_pdf.REDOSLED_MIN == 1
    assert onboarding_pdf.REDOSLED_MAX == REDOSLED_MAX == 10**10 - 1


def test_redosled_minimum_and_maximum_pass():
    assert validate_metadata("N", None, 1).redosled == 1
    assert validate_metadata("N", None, REDOSLED_MAX).redosled == REDOSLED_MAX


@pytest.mark.parametrize("redosled", [REDOSLED_MAX + 1, 10**12, 2**63])
def test_redosled_above_maximum_rejected(redosled):
    with pytest.raises(ValidationBusinessError):
        validate_metadata("N", None, redosled)


# ------------------------------------- trim se primenjuje pre provere duzine
def test_metadata_length_is_checked_after_trim():
    md = validate_metadata("  " + "a" * 200 + "  ", "  " + "b" * 4000 + "  ", 1)
    assert len(md.naziv) == 200 and len(md.opis) == 4000


def test_strip_helpers():
    from app.services.onboarding_pdf import strip_text, strip_text_or_none

    assert strip_text("  x  ") == "x"
    assert strip_text("   ") == ""  # prazan naziv pada na min_length=1
    assert strip_text(5) == 5  # ne-string ostaje pydantic-u da ga odbije
    assert strip_text_or_none("   ") is None
    assert strip_text_or_none(" o ") == "o"
    assert strip_text_or_none(None) is None
