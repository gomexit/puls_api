import logging

from app.api.v1.auth import USER_AGENT_MAX, _user_agent
from app.core.phone import mask_phone
from app.services.sms_service import ConsoleSmsProvider


def test_console_provider_does_not_log_secret_or_full_phone(caplog):
    provider = ConsoleSmsProvider()
    secret_password = "SuperTajnaLozinka123"
    phone = "063765432"
    with caplog.at_level(logging.INFO, logger="puls.sms"):
        provider.send_sms(phone, f"Vaša privremena lozinka za PULS je: {secret_password}")

    logged = " ".join(r.getMessage() for r in caplog.records)
    assert secret_password not in logged
    assert phone not in logged  # full phone must not appear
    assert "5432" in logged  # masked tail is fine


def test_mask_phone_keeps_only_last_four():
    assert mask_phone("060000000") == "*****0000"
    assert mask_phone("063765432") == "*****5432"
    assert mask_phone("123") == "***"


def test_user_agent_truncated_to_column_limit():
    request = type("R", (), {"headers": {"user-agent": "x" * 1000}})()
    assert len(_user_agent(request)) == USER_AGENT_MAX


def test_user_agent_none_when_missing():
    request = type("R", (), {"headers": {}})()
    assert _user_agent(request) is None
