from app.core.exceptions import ValidationBusinessError
from app.core.security import hash_password, verify_password
from app.services.configuration_service import ConfigurationService

MIN_PASSWORD_LENGTH_KEY = "MIN_DUZINA_LOZINKE"


class PasswordService:
    """Centralized password hashing and validation rules, kept simple on purpose."""

    def __init__(self, configuration_service: ConfigurationService):
        self.configuration_service = configuration_service

    def get_min_length(self) -> int:
        return self.configuration_service.get_int(MIN_PASSWORD_LENGTH_KEY, 8)

    def hash(self, plain_password: str) -> str:
        return hash_password(plain_password)

    def verify(self, plain_password: str, password_hash: str) -> bool:
        return verify_password(plain_password, password_hash)

    def validate_new_password(
        self, nova_lozinka: str, potvrda_nove_lozinke: str, trenutna_lozinka_hash: str | None = None
    ) -> None:
        min_length = self.get_min_length()
        if len(nova_lozinka) < min_length:
            raise ValidationBusinessError(f"Lozinka mora imati najmanje {min_length} karaktera.")
        if nova_lozinka != potvrda_nove_lozinke:
            raise ValidationBusinessError("Nova lozinka i potvrda lozinke se ne poklapaju.")
        if trenutna_lozinka_hash and self.verify(nova_lozinka, trenutna_lozinka_hash):
            raise ValidationBusinessError("Nova lozinka ne sme biti ista kao trenutna lozinka.")
