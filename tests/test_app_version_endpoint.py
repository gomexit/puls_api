"""HTTP-level provera GET /api/v1/app/version: BEZ autentikacije (nema Bearer,
nema X-Service-Key/X-Acting-Platni-Broj) - Android ga poziva pre login-a."""

import pytest
from fastapi.testclient import TestClient

from app.api.v1 import app_version as app_version_mod
from app.main import app
from app.services.app_version_service import AppVersionService
from tests.admin_configuration_fakes import FakeConfigurationRepository


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _use_service(service):
    app.dependency_overrides[app_version_mod.get_app_version_service] = lambda: service


def test_version_no_headers_required(client):
    _use_service(AppVersionService(db=None, repository=FakeConfigurationRepository({})))
    resp = client.get("/api/v1/app/version")
    assert resp.status_code == 200


def test_version_response_shape_defaults(client):
    _use_service(AppVersionService(db=None, repository=FakeConfigurationRepository({})))
    resp = client.get("/api/v1/app/version")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body.keys()) == {"current_version", "min_supported_version", "download_url"}
    assert body == {"current_version": "1.0", "min_supported_version": "1.0", "download_url": None}


def test_version_response_shape_with_values(client):
    repo = FakeConfigurationRepository(
        {
            "CURRENT_VERSION": "2.3.1",
            "MIN_SUPPORTED_VERSION": "2.0",
            "DOWNLOAD_URL": "https://cdn.example.com/app.apk",
        }
    )
    _use_service(AppVersionService(db=None, repository=repo))
    resp = client.get("/api/v1/app/version")
    assert resp.status_code == 200
    body = resp.json()
    assert body["current_version"] == "2.3.1"
    assert body["min_supported_version"] == "2.0"
    assert body["download_url"] == "https://cdn.example.com/app.apk"


def test_version_fail_safe_on_invalid_db_value(client):
    repo = FakeConfigurationRepository({"CURRENT_VERSION": "v1.0-corrupted"})
    _use_service(AppVersionService(db=None, repository=repo))
    resp = client.get("/api/v1/app/version")
    assert resp.status_code == 200
    assert resp.json()["current_version"] == "1.0"


def test_version_works_with_bearer_header_present_but_ignored(client):
    """Endpoint ne zahteva autentikaciju, ali ne sme ni da padne ako je poslata."""
    _use_service(AppVersionService(db=None, repository=FakeConfigurationRepository({})))
    resp = client.get("/api/v1/app/version", headers={"Authorization": "Bearer nekitoken"})
    assert resp.status_code == 200


# =============================================================== rubni slucajevi (bez 500)
def test_version_download_url_empty_host_with_port_null(client):
    repo = FakeConfigurationRepository({"DOWNLOAD_URL": "https://:443/app.apk"})
    _use_service(AppVersionService(db=None, repository=repo))
    resp = client.get("/api/v1/app/version")
    assert resp.status_code == 200
    assert resp.json()["download_url"] is None


def test_version_download_url_malformed_ipv6_null(client):
    repo = FakeConfigurationRepository({"DOWNLOAD_URL": "https://[::1"})
    _use_service(AppVersionService(db=None, repository=repo))
    resp = client.get("/api/v1/app/version")
    assert resp.status_code == 200
    assert resp.json()["download_url"] is None


def test_version_download_url_with_credentials_null(client):
    repo = FakeConfigurationRepository({"DOWNLOAD_URL": "https://user:pass@example.com/app.apk"})
    _use_service(AppVersionService(db=None, repository=repo))
    resp = client.get("/api/v1/app/version")
    assert resp.status_code == 200
    assert resp.json()["download_url"] is None


def test_version_download_url_valid_returned(client):
    repo = FakeConfigurationRepository({"DOWNLOAD_URL": "https://cdn.example.com/app.apk"})
    _use_service(AppVersionService(db=None, repository=repo))
    resp = client.get("/api/v1/app/version")
    assert resp.status_code == 200
    assert resp.json()["download_url"] == "https://cdn.example.com/app.apk"


def test_version_over_50_chars_uses_default_no_500(client):
    too_long = "1." + "2" * 49
    repo = FakeConfigurationRepository({"CURRENT_VERSION": too_long})
    _use_service(AppVersionService(db=None, repository=repo))
    resp = client.get("/api/v1/app/version")
    assert resp.status_code == 200
    assert resp.json()["current_version"] == "1.0"
