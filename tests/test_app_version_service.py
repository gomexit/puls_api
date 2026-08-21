"""Servisni testovi za AppVersionService (fake repository, bez DB). Fail-safe
ponasanje na nevalidne/nedostajuce vrednosti je kriticno jer Android ovaj
endpoint zove bez ikakve autentikacije, pre login-a."""

from app.services.app_version_service import AppVersionService
from tests.admin_configuration_fakes import FakeConfigurationRepository


def _service(values=None):
    return AppVersionService(db=None, repository=FakeConfigurationRepository(values))


def test_defaults_when_no_rows():
    service = _service({})
    result = service.get_version_info()
    assert result == {"current_version": "1.0", "min_supported_version": "1.0", "download_url": None}


def test_reads_actual_values():
    service = _service(
        {
            "CURRENT_VERSION": "2.3.1",
            "MIN_SUPPORTED_VERSION": "2.0",
            "DOWNLOAD_URL": "https://cdn.example.com/app.apk",
        }
    )
    result = service.get_version_info()
    assert result == {
        "current_version": "2.3.1",
        "min_supported_version": "2.0",
        "download_url": "https://cdn.example.com/app.apk",
    }


def test_invalid_current_version_format_falls_back_to_default():
    service = _service({"CURRENT_VERSION": "v1.0-beta"})
    result = service.get_version_info()
    assert result["current_version"] == "1.0"


def test_invalid_min_supported_version_format_falls_back_to_default():
    service = _service({"MIN_SUPPORTED_VERSION": "not-a-version"})
    result = service.get_version_info()
    assert result["min_supported_version"] == "1.0"


def test_min_supported_greater_than_current_fail_safe_downgrades_min():
    service = _service({"CURRENT_VERSION": "1.2", "MIN_SUPPORTED_VERSION": "1.5"})
    result = service.get_version_info()
    assert result["current_version"] == "1.2"
    assert result["min_supported_version"] == "1.2"


def test_download_url_invalid_scheme_returns_none():
    service = _service({"DOWNLOAD_URL": "http://cdn.example.com/app.apk"})
    result = service.get_version_info()
    assert result["download_url"] is None


def test_download_url_blank_returns_none():
    service = _service({"DOWNLOAD_URL": "   "})
    result = service.get_version_info()
    assert result["download_url"] is None


def test_never_returns_other_configuration_keys():
    service = _service({"MIN_DUZINA_LOZINKE": "8", "MAX_NEUSPESNIH_PRIJAVA": "3"})
    result = service.get_version_info()
    assert set(result.keys()) == {"current_version", "min_supported_version", "download_url"}


# =============================================================== rubni slucajevi
def test_download_url_empty_host_with_port_only_returns_none():
    service = _service({"DOWNLOAD_URL": "https://:443/app.apk"})
    result = service.get_version_info()
    assert result["download_url"] is None


def test_download_url_malformed_ipv6_bracket_returns_none():
    service = _service({"DOWNLOAD_URL": "https://[::1"})
    result = service.get_version_info()
    assert result["download_url"] is None


def test_download_url_with_username_password_returns_none():
    service = _service({"DOWNLOAD_URL": "https://user:pass@example.com/app.apk"})
    result = service.get_version_info()
    assert result["download_url"] is None


def test_download_url_valid_still_returned():
    service = _service({"DOWNLOAD_URL": "https://cdn.example.com/app.apk"})
    result = service.get_version_info()
    assert result["download_url"] == "https://cdn.example.com/app.apk"


def test_version_over_50_chars_falls_back_to_default():
    too_long = "1." + "2" * 49
    service = _service({"CURRENT_VERSION": too_long})
    result = service.get_version_info()
    assert result["current_version"] == "1.0"


def test_batch_read_single_call():
    """Jedan batch upit za sve 3 vrednosti (izbegava N+1)."""
    repo = FakeConfigurationRepository({"CURRENT_VERSION": "1.5"})
    calls = {"n": 0}
    original = repo.get_values

    def counting(keys):
        calls["n"] += 1
        assert set(keys) == {"CURRENT_VERSION", "MIN_SUPPORTED_VERSION", "DOWNLOAD_URL"}
        return original(keys)

    repo.get_values = counting
    service = AppVersionService(db=None, repository=repo)
    service.get_version_info()
    assert calls["n"] == 1
