from app.repositories.configuration_repository import ConfigurationRepository


class ConfigurationService:
    """Reads business configuration from PULS_KONFIGURACIJA with safe fallbacks."""

    def __init__(self, repository: ConfigurationRepository):
        self.repository = repository

    def get_int(self, kljuc: str, default: int) -> int:
        raw = self.repository.get_value(kljuc)
        if raw is None:
            return default
        try:
            return int(raw)
        except ValueError:
            return default

    def get_bool(self, kljuc: str, default: bool) -> bool:
        raw = self.repository.get_value(kljuc)
        if raw is None:
            return default
        return raw.strip().upper() in ("D", "TRUE", "1")

    def get_str(self, kljuc: str, default: str) -> str:
        raw = self.repository.get_value(kljuc)
        return raw if raw is not None else default
