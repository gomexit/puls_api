"""Read-only servis za GET /api/v1/app/version. Android poziva ovaj endpoint pre
login-a, bez ikakve autentikacije - zato mora biti fail-safe: nevalidan ili
nedostajući sadržaj u PULS_KONFIGURACIJA NIKADA ne sme izazvati 500, samo tihi
pad na bezbedan default."""

from sqlalchemy.orm import Session

from app.core.configuration_definitions import (
    CONFIGURATION_DEFINITIONS,
    MAX_VERSION_LENGTH,
    compare_versions,
    parse_version,
    validate_https_url,
)
from app.core.exceptions import ValidationBusinessError
from app.repositories.configuration_repository import ConfigurationRepository

CURRENT_VERSION_KEY = "CURRENT_VERSION"
MIN_SUPPORTED_VERSION_KEY = "MIN_SUPPORTED_VERSION"
DOWNLOAD_URL_KEY = "DOWNLOAD_URL"


class AppVersionService:
    def __init__(self, db: Session, repository: ConfigurationRepository | None = None):
        self.repo = repository or ConfigurationRepository(db)

    def get_version_info(self) -> dict:
        values = self.repo.get_values([CURRENT_VERSION_KEY, MIN_SUPPORTED_VERSION_KEY, DOWNLOAD_URL_KEY])

        current = self._safe_version(values.get(CURRENT_VERSION_KEY), CURRENT_VERSION_KEY)
        min_supported = self._safe_version(values.get(MIN_SUPPORTED_VERSION_KEY), MIN_SUPPORTED_VERSION_KEY)

        # Fail-safe: ako je neko rucno u bazi postavio MIN_SUPPORTED_VERSION > CURRENT_VERSION,
        # ne smemo blokirati bas sve korisnike - spustimo minimum na trenutnu verziju.
        if compare_versions(min_supported, current) > 0:
            min_supported = current

        return {
            "current_version": current,
            "min_supported_version": min_supported,
            "download_url": self._safe_download_url(values.get(DOWNLOAD_URL_KEY)),
        }

    @staticmethod
    def _safe_version(raw: str | None, key: str) -> str:
        default = CONFIGURATION_DEFINITIONS[key].default
        if raw is None or len(raw) > MAX_VERSION_LENGTH:
            return default
        try:
            parse_version(raw)
        except ValueError:
            return default
        return raw

    @staticmethod
    def _safe_download_url(raw: str | None) -> str | None:
        if raw is None:
            return None
        v = raw.strip()
        if not v:
            return None
        try:
            validate_https_url(v, "DOWNLOAD_URL")
        except ValidationBusinessError:
            return None
        return v
