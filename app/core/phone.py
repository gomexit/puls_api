import re

# Accepted format: local Serbian mobile number starting with 06 followed by 7 or 8
# digits (i.e. 9 or 10 digits total). Some numbers are 9 digits, some are 10.
LOCAL_MOBILE_PATTERN = r"^06\d{7,8}$"
_LOCAL_MOBILE_RE = re.compile(LOCAL_MOBILE_PATTERN)


def is_valid_local_mobile_phone(phone: str | None) -> bool:
    if not phone:
        return False
    return _LOCAL_MOBILE_RE.match(phone.strip()) is not None


def validate_local_mobile_phone(phone: str) -> str:
    """Return the phone unchanged if it matches ^06\\d{7,8}$, else raise ValueError.

    No transformation is attempted: +381/381/spaces/dashes/letters are rejected,
    never converted."""
    if phone is None:
        raise ValueError("broj_telefona je obavezan.")
    candidate = phone.strip()
    if not _LOCAL_MOBILE_RE.match(candidate):
        raise ValueError("broj_telefona mora biti u formatu 06XXXXXXX(X) (9 ili 10 cifara).")
    return candidate


def mask_phone(phone: str | None) -> str:
    """Mask all but the last four digits, e.g. '060000000' -> '*****0000'."""
    digits = re.sub(r"\D", "", phone or "")
    if len(digits) <= 4:
        return "*" * len(digits)
    return "*" * (len(digits) - 4) + digits[-4:]
