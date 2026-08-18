from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PRODUCTION_ENV = "production"
MIN_PRODUCTION_PEPPER_LENGTH = 32


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "PULS API"
    app_env: str = "development"
    log_level: str = "INFO"

    db_user: str = ""
    db_password: str = ""
    db_dsn: str = ""
    db_pool_size: int = 5
    db_max_overflow: int = 5

    session_ttl_days: int = 30
    reset_code_pepper: str = ""
    reset_code_ttl_min_fallback: int = 15
    reset_code_max_attempts: int = 5

    max_login_attempts_fallback: int = 3
    min_password_length_fallback: int = 8

    sms_provider: str = "console"

    audit_source: str = "API"

    # Provisioning runs as a dedicated single-instance worker, not in the API process.
    provisioning_interval_minutes: int = 10
    provisioning_batch_size: int = 100

    @property
    def is_production(self) -> bool:
        return self.app_env.strip().lower() == PRODUCTION_ENV

    @model_validator(mode="after")
    def _validate_production(self) -> "Settings":
        if not self.is_production:
            return self

        # Error messages intentionally never contain the secret values themselves.
        if self.sms_provider == "console":
            raise ValueError("U produkciji SMS_PROVIDER ne sme biti 'console'.")
        if len(self.reset_code_pepper) < MIN_PRODUCTION_PEPPER_LENGTH:
            raise ValueError(
                f"U produkciji RESET_CODE_PEPPER mora imati najmanje {MIN_PRODUCTION_PEPPER_LENGTH} karaktera."
            )
        if not (self.db_user and self.db_password and self.db_dsn):
            raise ValueError("U produkciji DB_USER, DB_PASSWORD i DB_DSN moraju biti postavljeni.")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
