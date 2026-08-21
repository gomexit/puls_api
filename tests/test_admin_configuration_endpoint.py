"""HTTP-level provera admin CONFIGURATION ruta: OBO autentikacija (SAMO ADMIN,
HR dobija 403) + osnovni ugovori GET/PUT."""

import pytest
from fastapi.testclient import TestClient

from app.api.v1 import admin_configuration as config_mod
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.dependencies import portal_auth
from app.main import app
from app.services.admin_configuration_service import AdminConfigurationService
from tests.admin_configuration_fakes import FakeAdminConfigurationRepository, FakeDb, FakeKonfiguracijaRow
from tests.fakes import FakeAuditService, make_korisnik

VALID_KEY = "s" * 40


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


class FakePortalRepo:
    def __init__(self, users=None, roles=None):
        self._users = {u.platni_broj: u for u in (users or [])}
        self._roles = roles or {}

    def get_by_platni_broj(self, pb):
        return self._users.get(pb)

    def get_active_role_codes(self, kid):
        return self._roles.get(kid, [])


def _actor(pb="actor1", **ov):
    return make_korisnik(id=1, platni_broj=pb, **ov)


def _use_portal(monkeypatch, repo, key=VALID_KEY):
    monkeypatch.setattr(portal_auth, "KorisnikRepository", lambda db: db)
    app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None, portal_service_key=key)
    app.dependency_overrides[get_db] = lambda: repo


def _headers(acting="actor1"):
    return {"X-Service-Key": VALID_KEY, "X-Acting-Platni-Broj": acting}


def _use_service(service):
    app.dependency_overrides[config_mod.get_admin_configuration_service] = lambda: service


def _authed(monkeypatch, role="ADMIN"):
    _use_portal(monkeypatch, FakePortalRepo([_actor()], {1: [role]}))


def _make_service(rows=None):
    store: dict = {}
    repo = FakeAdminConfigurationRepository(rows, store=store)
    db = FakeDb(store=store)
    return AdminConfigurationService(db, repository=repo, audit_service=FakeAuditService())


# ================================================================= OBO auth
def test_get_no_service_key_401(client, monkeypatch):
    _authed(monkeypatch)
    resp = client.get("/api/v1/admin/configuration")
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "INVALID_SERVICE_CREDENTIALS"


def test_get_wrong_service_key_401(client, monkeypatch):
    _authed(monkeypatch)
    resp = client.get("/api/v1/admin/configuration", headers={"X-Service-Key": "wrong"})
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "INVALID_SERVICE_CREDENTIALS"


def test_get_zaposleni_role_403(client, monkeypatch):
    _authed(monkeypatch, role="ZAPOSLENI")
    resp = client.get("/api/v1/admin/configuration", headers=_headers())
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "FORBIDDEN"


def test_get_hr_role_403(client, monkeypatch):
    """Configuration je SAMO za ADMIN - za razliku od dashboard/audit modula, HR nema pristup."""
    _authed(monkeypatch, role="HR")
    resp = client.get("/api/v1/admin/configuration", headers=_headers())
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "FORBIDDEN"


def test_get_admin_role_allowed(client, monkeypatch):
    _authed(monkeypatch, role="ADMIN")
    _use_service(_make_service())
    resp = client.get("/api/v1/admin/configuration", headers=_headers())
    assert resp.status_code == 200


def test_put_hr_role_403(client, monkeypatch):
    _authed(monkeypatch, role="HR")
    _use_service(_make_service())
    resp = client.put(
        "/api/v1/admin/configuration/MAX_IDEJA_PO_CIKLUSU", headers=_headers(), json={"vrednost": "5"}
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "FORBIDDEN"


def test_put_no_service_key_401(client, monkeypatch):
    _authed(monkeypatch)
    resp = client.put("/api/v1/admin/configuration/MAX_IDEJA_PO_CIKLUSU", json={"vrednost": "5"})
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "INVALID_SERVICE_CREDENTIALS"


# ============================================================ osnovni ugovori
def test_get_returns_exactly_9_keys_and_no_secrets(client, monkeypatch):
    _authed(monkeypatch)
    _use_service(_make_service())
    resp = client.get("/api/v1/admin/configuration", headers=_headers())
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["items"]) == 9
    dumped = str(body)
    for forbidden in ("DB_PASSWORD", "PORTAL_SERVICE_KEY", "RESET_CODE_PEPPER", "FCM_CREDENTIALS", "DB_USER", "DB_DSN"):
        assert forbidden not in dumped


def test_put_unknown_key_404(client, monkeypatch):
    _authed(monkeypatch)
    _use_service(_make_service())
    resp = client.put("/api/v1/admin/configuration/NEPOSTOJECI", headers=_headers(), json={"vrednost": "1"})
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "CONFIGURATION_KEY_NOT_ALLOWED"


def test_put_extra_field_422(client, monkeypatch):
    _authed(monkeypatch)
    _use_service(_make_service())
    resp = client.put(
        "/api/v1/admin/configuration/MAX_IDEJA_PO_CIKLUSU",
        headers=_headers(),
        json={"vrednost": "5", "nepoznato_polje": "x"},
    )
    assert resp.status_code == 422


def test_put_missing_vrednost_field_422(client, monkeypatch):
    _authed(monkeypatch)
    _use_service(_make_service())
    resp = client.put("/api/v1/admin/configuration/MAX_IDEJA_PO_CIKLUSU", headers=_headers(), json={})
    assert resp.status_code == 422


def test_put_out_of_range_422(client, monkeypatch):
    _authed(monkeypatch)
    _use_service(_make_service())
    resp = client.put(
        "/api/v1/admin/configuration/MAX_IDEJA_PO_CIKLUSU", headers=_headers(), json={"vrednost": "101"}
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"


def test_put_happy_path_updates_value(client, monkeypatch):
    _authed(monkeypatch)
    _use_service(_make_service())
    resp = client.put(
        "/api/v1/admin/configuration/MAX_IDEJA_PO_CIKLUSU", headers=_headers(), json={"vrednost": "5"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["kljuc"] == "MAX_IDEJA_PO_CIKLUSU"
    assert body["vrednost"] == "5"
    assert body["izmenio_korisnik_id"] == 1


def test_put_download_url_valid_https(client, monkeypatch):
    _authed(monkeypatch)
    _use_service(_make_service())
    resp = client.put(
        "/api/v1/admin/configuration/DOWNLOAD_URL",
        headers=_headers(),
        json={"vrednost": "https://cdn.example.com/app.apk"},
    )
    assert resp.status_code == 200
    assert resp.json()["vrednost"] == "https://cdn.example.com/app.apk"


def test_put_download_url_http_rejected(client, monkeypatch):
    _authed(monkeypatch)
    _use_service(_make_service())
    resp = client.put(
        "/api/v1/admin/configuration/DOWNLOAD_URL",
        headers=_headers(),
        json={"vrednost": "http://cdn.example.com/app.apk"},
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"


def test_put_min_supported_greater_than_current_422(client, monkeypatch):
    _authed(monkeypatch)
    rows = [FakeKonfiguracijaRow("CURRENT_VERSION", "1.5", "TEKST", "opis")]
    _use_service(_make_service(rows))
    resp = client.put(
        "/api/v1/admin/configuration/MIN_SUPPORTED_VERSION", headers=_headers(), json={"vrednost": "1.6"}
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"


# =============================================================== rubni slucajevi (nikad 500)
def test_put_download_url_empty_host_with_port_422(client, monkeypatch):
    _authed(monkeypatch)
    _use_service(_make_service())
    resp = client.put(
        "/api/v1/admin/configuration/DOWNLOAD_URL", headers=_headers(), json={"vrednost": "https://:443/app.apk"}
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"


def test_put_download_url_malformed_ipv6_422(client, monkeypatch):
    _authed(monkeypatch)
    _use_service(_make_service())
    resp = client.put(
        "/api/v1/admin/configuration/DOWNLOAD_URL", headers=_headers(), json={"vrednost": "https://[::1"}
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"


def test_put_download_url_with_credentials_422(client, monkeypatch):
    _authed(monkeypatch)
    _use_service(_make_service())
    resp = client.put(
        "/api/v1/admin/configuration/DOWNLOAD_URL",
        headers=_headers(),
        json={"vrednost": "https://user:pass@example.com/app.apk"},
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"


def test_put_download_url_valid_still_passes(client, monkeypatch):
    _authed(monkeypatch)
    _use_service(_make_service())
    resp = client.put(
        "/api/v1/admin/configuration/DOWNLOAD_URL",
        headers=_headers(),
        json={"vrednost": "https://cdn.example.com/app.apk"},
    )
    assert resp.status_code == 200
    assert resp.json()["vrednost"] == "https://cdn.example.com/app.apk"


def test_put_version_over_50_chars_422(client, monkeypatch):
    _authed(monkeypatch)
    _use_service(_make_service())
    too_long = "1." + "2" * 49
    resp = client.put(
        "/api/v1/admin/configuration/CURRENT_VERSION", headers=_headers(), json={"vrednost": too_long}
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"


def test_put_numeric_value_over_20_chars_422(client, monkeypatch):
    _authed(monkeypatch)
    _use_service(_make_service())
    resp = client.put(
        "/api/v1/admin/configuration/MAX_IDEJA_PO_CIKLUSU", headers=_headers(), json={"vrednost": "9" * 21}
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"


def test_put_vrednost_over_4000_chars_422(client, monkeypatch):
    """AdminConfigurationUpdateRequest.vrednost max_length=4000 - pydantic validacija
    (422 pre nego sto zahtev uopste stigne do servisa/DB)."""
    _authed(monkeypatch)
    _use_service(_make_service())
    resp = client.put(
        "/api/v1/admin/configuration/DOWNLOAD_URL",
        headers=_headers(),
        json={"vrednost": "https://example.com/" + ("a" * 4000)},
    )
    assert resp.status_code == 422
