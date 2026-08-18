import pytest

from app.core.exceptions import ValidationBusinessError
from app.services.password_service import PasswordService
from tests.fakes import FakeConfigurationService


def build_password_service(min_length=8):
    return PasswordService(FakeConfigurationService({"MIN_DUZINA_LOZINKE": str(min_length)}))


def test_hash_and_verify_roundtrip():
    service = build_password_service()
    hashed = service.hash("SomePassword1")

    assert service.verify("SomePassword1", hashed)
    assert not service.verify("WrongPassword", hashed)


def test_validate_new_password_too_short():
    service = build_password_service(min_length=8)
    with pytest.raises(ValidationBusinessError):
        service.validate_new_password("short", "short")


def test_validate_new_password_mismatch():
    service = build_password_service()
    with pytest.raises(ValidationBusinessError):
        service.validate_new_password("GoodPassword1", "DifferentPassword1")


def test_validate_new_password_same_as_current():
    service = build_password_service()
    current_hash = service.hash("SamePassword1")
    with pytest.raises(ValidationBusinessError):
        service.validate_new_password("SamePassword1", "SamePassword1", current_hash)
