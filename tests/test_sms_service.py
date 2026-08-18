import pytest

from app.core.phone import is_valid_local_mobile_phone, validate_local_mobile_phone

VALID = ["060000000", "061123456", "063765432", "0603111413", "0601234567"]  # 9 or 10 digits
INVALID = [
    "+381601234567",
    "381601234567",
    "060 123 456",
    "060-123-456",
    "060/123456",
    "abc060123456",
    "011123456",
    "06012345",      # 8 digits (too short)
    "06012345678",   # 11 digits (too long)
    "",              # empty
]


@pytest.mark.parametrize("phone", VALID)
def test_valid_local_mobile_accepted(phone):
    assert is_valid_local_mobile_phone(phone)
    assert validate_local_mobile_phone(phone) == phone


@pytest.mark.parametrize("phone", INVALID)
def test_invalid_local_mobile_rejected(phone):
    assert not is_valid_local_mobile_phone(phone)
    with pytest.raises(ValueError):
        validate_local_mobile_phone(phone)


def test_none_is_invalid():
    assert not is_valid_local_mobile_phone(None)
