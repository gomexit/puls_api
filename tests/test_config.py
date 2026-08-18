import pytest
from pydantic import ValidationError

from app.core.config import Settings


def prod(**overrides) -> Settings:
    base = dict(
        app_env="production",
        sms_provider="oracle",
        reset_code_pepper="p" * 40,
        db_user="u",
        db_password="pw",
        db_dsn="host:1521/svc",
    )
    base.update(overrides)
    return Settings(_env_file=None, **base)


def test_valid_production_settings_ok():
    assert prod().is_production


def test_production_console_provider_rejected():
    with pytest.raises(ValidationError):
        prod(sms_provider="console")


def test_production_short_pepper_rejected():
    with pytest.raises(ValidationError):
        prod(reset_code_pepper="short")


def test_production_missing_db_rejected():
    with pytest.raises(ValidationError):
        prod(db_user="")


def test_error_message_does_not_contain_secret_value():
    try:
        prod(reset_code_pepper="supersecretpepper")
    except ValidationError as exc:
        assert "supersecretpepper" not in str(exc)
    else:  # pragma: no cover
        pytest.fail("Expected ValidationError")


def test_development_allows_console_and_empty_secrets():
    s = Settings(_env_file=None, app_env="development")
    assert not s.is_production
    assert s.sms_provider == "console"
