import re

from pydantic import BaseModel, field_validator

from app.core.phone import validate_local_mobile_phone
from app.schemas.user import UserSummary

# Max lengths aligned with the Oracle columns they ultimately populate.
PLATNI_BROJ_MAX = 30
PASSWORD_MAX = 128
UREDJAJ_ID_MAX = 255
NAZIV_UREDJAJA_MAX = 255

_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")
_SIX_DIGITS = re.compile(r"^\d{6}$")


def _validate_platni_broj(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("platni_broj je obavezan.")
    if len(value) > PLATNI_BROJ_MAX:
        raise ValueError("platni_broj je predugačak.")
    if _CONTROL_CHARS.search(value):
        raise ValueError("platni_broj sadrži nedozvoljene znakove.")
    return value


def _validate_password(value: str) -> str:
    # Do NOT trim passwords: leading/trailing whitespace can be intentional.
    if len(value) < 1:
        raise ValueError("Lozinka je obavezna.")
    if len(value) > PASSWORD_MAX:
        raise ValueError("Lozinka je predugačka.")
    return value


class LoginRequest(BaseModel):
    platni_broj: str
    lozinka: str
    uredjaj_id: str
    naziv_uredjaja: str | None = None

    @field_validator("platni_broj")
    @classmethod
    def _platni_broj(cls, v: str) -> str:
        return _validate_platni_broj(v)

    @field_validator("lozinka")
    @classmethod
    def _lozinka(cls, v: str) -> str:
        return _validate_password(v)

    @field_validator("uredjaj_id")
    @classmethod
    def _uredjaj_id(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("uredjaj_id je obavezan.")
        if len(v) > UREDJAJ_ID_MAX:
            raise ValueError("uredjaj_id je predugačak.")
        return v

    @field_validator("naziv_uredjaja")
    @classmethod
    def _naziv_uredjaja(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        if len(v) > NAZIV_UREDJAJA_MAX:
            raise ValueError("naziv_uredjaja je predugačak.")
        return v or None


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserSummary
    obavezna_promena_lozinke: bool
    telefon_potvrdjen: bool


class ChangePasswordRequest(BaseModel):
    trenutna_lozinka: str
    nova_lozinka: str
    potvrda_nove_lozinke: str

    @field_validator("trenutna_lozinka", "nova_lozinka", "potvrda_nove_lozinke")
    @classmethod
    def _passwords(cls, v: str) -> str:
        return _validate_password(v)


class ConfirmPhoneRequest(BaseModel):
    broj_telefona: str

    @field_validator("broj_telefona")
    @classmethod
    def _broj_telefona(cls, v: str) -> str:
        return validate_local_mobile_phone(v)


class ForgotPasswordRequest(BaseModel):
    platni_broj: str

    @field_validator("platni_broj")
    @classmethod
    def _platni_broj(cls, v: str) -> str:
        return _validate_platni_broj(v)


class ResetPasswordRequest(BaseModel):
    platni_broj: str
    kod: str
    nova_lozinka: str
    potvrda_nove_lozinke: str

    @field_validator("platni_broj")
    @classmethod
    def _platni_broj(cls, v: str) -> str:
        return _validate_platni_broj(v)

    @field_validator("kod")
    @classmethod
    def _kod(cls, v: str) -> str:
        v = v.strip()
        if not _SIX_DIGITS.match(v):
            raise ValueError("Reset kod mora imati tačno šest cifara.")
        return v

    @field_validator("nova_lozinka", "potvrda_nove_lozinke")
    @classmethod
    def _passwords(cls, v: str) -> str:
        return _validate_password(v)
