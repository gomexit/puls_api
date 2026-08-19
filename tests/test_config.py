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
        portal_service_key="k" * 40,
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
    assert s.portal_service_key == ""


def test_production_empty_service_key_rejected():
    with pytest.raises(ValidationError):
        prod(portal_service_key="")


def test_production_short_service_key_rejected():
    with pytest.raises(ValidationError):
        prod(portal_service_key="k" * 31)


def test_production_service_key_min_length_accepted():
    assert prod(portal_service_key="k" * 32).is_production


def test_service_key_value_not_in_error_message():
    try:
        prod(portal_service_key="s3cr3t")
    except ValidationError as exc:
        assert "s3cr3t" not in str(exc)
    else:  # pragma: no cover
        pytest.fail("Expected ValidationError")


# --------------------------------------------------------------------- item 6: FCM
def test_fcm_defaults_valid_when_disabled():
    s = Settings(_env_file=None)
    assert s.fcm_enabled is False
    assert s.fcm_batch_size == 100
    assert s.fcm_max_attempts == 5
    assert s.fcm_worker_interval_seconds == 30


@pytest.mark.parametrize("field", ["fcm_batch_size", "fcm_max_attempts", "fcm_worker_interval_seconds"])
def test_fcm_zero_rejected(field):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{field: 0})


@pytest.mark.parametrize("field", ["fcm_batch_size", "fcm_max_attempts", "fcm_worker_interval_seconds"])
def test_fcm_negative_rejected(field):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{field: -1})


def test_fcm_enabled_without_credentials_file_rejected():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, fcm_enabled=True, fcm_credentials_file="")


def test_fcm_enabled_with_blank_credentials_file_rejected():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, fcm_enabled=True, fcm_credentials_file="   ")


def test_fcm_enabled_with_credentials_file_accepted():
    s = Settings(_env_file=None, fcm_enabled=True, fcm_credentials_file="/etc/puls/fcm-sa.json")
    assert s.fcm_enabled is True


def test_fcm_disabled_allows_empty_credentials_file():
    s = Settings(_env_file=None, fcm_enabled=False, fcm_credentials_file="")
    assert s.fcm_enabled is False
