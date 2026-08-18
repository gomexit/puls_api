import pytest
from pydantic import ValidationError

from app.schemas.auth import (
    PASSWORD_MAX,
    PLATNI_BROJ_MAX,
    UREDJAJ_ID_MAX,
    ChangePasswordRequest,
    ConfirmPhoneRequest,
    LoginRequest,
    ResetPasswordRequest,
)


def test_login_trims_fields():
    m = LoginRequest(platni_broj="  12345 ", lozinka="x", uredjaj_id="  dev ", naziv_uredjaja="  Phone ")
    assert m.platni_broj == "12345"
    assert m.uredjaj_id == "dev"
    assert m.naziv_uredjaja == "Phone"


def test_login_platni_broj_too_long_rejected():
    with pytest.raises(ValidationError):
        LoginRequest(platni_broj="1" * (PLATNI_BROJ_MAX + 1), lozinka="x", uredjaj_id="d")


def test_login_platni_broj_control_chars_rejected():
    with pytest.raises(ValidationError):
        LoginRequest(platni_broj="12\x0034", lozinka="x", uredjaj_id="d")


def test_password_is_not_trimmed():
    m = LoginRequest(platni_broj="1", lozinka="  spaces  ", uredjaj_id="d")
    assert m.lozinka == "  spaces  "


def test_password_too_long_rejected():
    with pytest.raises(ValidationError):
        ChangePasswordRequest(
            trenutna_lozinka="a",
            nova_lozinka="b" * (PASSWORD_MAX + 1),
            potvrda_nove_lozinke="b",
        )


def test_uredjaj_id_too_long_rejected():
    with pytest.raises(ValidationError):
        LoginRequest(platni_broj="1", lozinka="x", uredjaj_id="d" * (UREDJAJ_ID_MAX + 1))


@pytest.mark.parametrize("phone", ["060000000", "061123456", "063765432", "0603111413"])
def test_confirm_phone_accepts_valid_local_mobile(phone):
    assert ConfirmPhoneRequest(broj_telefona=phone).broj_telefona == phone


@pytest.mark.parametrize(
    "phone",
    [
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
    ],
)
def test_confirm_phone_rejects_invalid(phone):
    with pytest.raises(ValidationError):
        ConfirmPhoneRequest(broj_telefona=phone)


@pytest.mark.parametrize("bad", ["12345", "1234567", "12345a", "abcdef", " 12345", ""])
def test_reset_code_must_be_exactly_six_digits(bad):
    with pytest.raises(ValidationError):
        ResetPasswordRequest(
            platni_broj="1", kod=bad, nova_lozinka="x", potvrda_nove_lozinke="x"
        )


def test_reset_code_valid_six_digits():
    m = ResetPasswordRequest(platni_broj="1", kod="123456", nova_lozinka="x", potvrda_nove_lozinke="x")
    assert m.kod == "123456"
