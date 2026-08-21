"""HTTP-level provera admin AUDIT LOG ruta: OBO autentikacija (ADMIN i HR dozvoljeni)
+ validacija filtera + 404 detalj."""

import pytest
from fastapi.testclient import TestClient

from app.api.v1 import admin_audit as audit_mod
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.dependencies import portal_auth
from app.main import app
from app.services.admin_audit_service import AdminAuditService
from tests.admin_audit_fakes import FakeAdminAuditRepository, FakeAuditLog
from tests.fakes import make_korisnik

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
    app.dependency_overrides[audit_mod.get_admin_audit_service] = lambda: service


def _authed(monkeypatch, role="ADMIN"):
    _use_portal(monkeypatch, FakePortalRepo([_actor()], {1: [role]}))


# ================================================================= OBO auth
def test_list_no_service_key_401(client, monkeypatch):
    _authed(monkeypatch)
    resp = client.get("/api/v1/admin/audit-logs")
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "INVALID_SERVICE_CREDENTIALS"


def test_list_wrong_service_key_401(client, monkeypatch):
    _authed(monkeypatch)
    resp = client.get("/api/v1/admin/audit-logs", headers={"X-Service-Key": "wrong"})
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "INVALID_SERVICE_CREDENTIALS"


def test_list_zaposleni_role_403(client, monkeypatch):
    _authed(monkeypatch, role="ZAPOSLENI")
    resp = client.get("/api/v1/admin/audit-logs", headers=_headers())
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "FORBIDDEN"


def test_list_admin_role_allowed(client, monkeypatch):
    _authed(monkeypatch, role="ADMIN")
    _use_service(AdminAuditService(db=None, repository=FakeAdminAuditRepository()))
    resp = client.get("/api/v1/admin/audit-logs", headers=_headers())
    assert resp.status_code == 200


def test_list_hr_role_allowed(client, monkeypatch):
    _authed(monkeypatch, role="HR")
    _use_service(AdminAuditService(db=None, repository=FakeAdminAuditRepository()))
    resp = client.get("/api/v1/admin/audit-logs", headers=_headers())
    assert resp.status_code == 200


# ============================================================ osnovni ugovori
def test_list_response_shape(client, monkeypatch):
    _authed(monkeypatch)
    logs = [FakeAuditLog(id=1, platni_broj="123", sifra_akcije="LOGIN")]
    _use_service(AdminAuditService(db=None, repository=FakeAdminAuditRepository(logs)))
    resp = client.get("/api/v1/admin/audit-logs", headers=_headers())
    assert resp.status_code == 200
    body = resp.json()
    assert set(body.keys()) == {"items", "page", "page_size", "total", "has_more"}
    item = body["items"][0]
    assert set(item.keys()) == {
        "id", "korisnik_id", "platni_broj", "sifra_akcije", "tip_entiteta",
        "entitet_id", "izvor", "datum_kreiranja",
    }
    assert "detalji" not in item
    assert "ip_adresa" not in item
    assert "korisnicki_agent" not in item


def test_list_datum_do_before_od_422(client, monkeypatch):
    _authed(monkeypatch)
    _use_service(AdminAuditService(db=None, repository=FakeAdminAuditRepository()))
    resp = client.get(
        "/api/v1/admin/audit-logs",
        headers=_headers(),
        params={"datum_od": "2026-02-01T00:00:00", "datum_do": "2026-01-01T00:00:00"},
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"


def test_list_timezone_aware_datum_422(client, monkeypatch):
    _authed(monkeypatch)
    _use_service(AdminAuditService(db=None, repository=FakeAdminAuditRepository()))
    resp = client.get(
        "/api/v1/admin/audit-logs",
        headers=_headers(),
        params={"datum_od": "2026-01-01T00:00:00Z"},
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"


def test_list_timezone_offset_datum_422(client, monkeypatch):
    _authed(monkeypatch)
    _use_service(AdminAuditService(db=None, repository=FakeAdminAuditRepository()))
    resp = client.get(
        "/api/v1/admin/audit-logs",
        headers=_headers(),
        params={"datum_od": "2026-01-01T00:00:00+02:00"},
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"


def test_list_naive_datetimes_pass(client, monkeypatch):
    _authed(monkeypatch)
    _use_service(AdminAuditService(db=None, repository=FakeAdminAuditRepository()))
    resp = client.get(
        "/api/v1/admin/audit-logs",
        headers=_headers(),
        params={"datum_od": "2026-01-01T00:00:00", "datum_do": "2026-02-01T00:00:00"},
    )
    assert resp.status_code == 200


def test_list_blank_platni_broj_filter_422(client, monkeypatch):
    _authed(monkeypatch)
    _use_service(AdminAuditService(db=None, repository=FakeAdminAuditRepository()))
    resp = client.get(
        "/api/v1/admin/audit-logs", headers=_headers(), params={"platni_broj": "   "}
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"


def test_list_too_long_sifra_akcije_filter_422(client, monkeypatch):
    _authed(monkeypatch)
    _use_service(AdminAuditService(db=None, repository=FakeAdminAuditRepository()))
    resp = client.get(
        "/api/v1/admin/audit-logs", headers=_headers(), params={"sifra_akcije": "X" * 101}
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"


def test_list_sifra_akcije_and_izvor_normalized_uppercase(client, monkeypatch):
    _authed(monkeypatch)
    logs = [FakeAuditLog(id=1, sifra_akcije="LOGIN", izvor="PORTAL")]
    _use_service(AdminAuditService(db=None, repository=FakeAdminAuditRepository(logs)))
    resp = client.get(
        "/api/v1/admin/audit-logs",
        headers=_headers(),
        params={"sifra_akcije": "login", "izvor": "portal"},
    )
    assert resp.status_code == 200
    assert resp.json()["total"] == 1


# ================================================================= detail
def test_detail_404_not_found(client, monkeypatch):
    _authed(monkeypatch)
    _use_service(AdminAuditService(db=None, repository=FakeAdminAuditRepository()))
    resp = client.get("/api/v1/admin/audit-logs/999", headers=_headers())
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "AUDIT_LOG_NOT_FOUND"


def test_detail_includes_sensitive_fields(client, monkeypatch):
    _authed(monkeypatch)
    logs = [
        FakeAuditLog(
            id=1,
            detalji='{"stara_vrednost": "X"}',
            ip_adresa="192.168.1.1",
            korisnicki_agent="Mozilla/5.0",
        )
    ]
    _use_service(AdminAuditService(db=None, repository=FakeAdminAuditRepository(logs)))
    resp = client.get("/api/v1/admin/audit-logs/1", headers=_headers())
    assert resp.status_code == 200
    body = resp.json()
    assert body["detalji"] == '{"stara_vrednost": "X"}'
    assert body["ip_adresa"] == "192.168.1.1"
    assert body["korisnicki_agent"] == "Mozilla/5.0"
