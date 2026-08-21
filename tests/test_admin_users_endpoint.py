"""HTTP-level provera admin USERS ruta: OBO autentikacija (require_portal_admin) +
osnovni ugovori. HR (bez ADMIN uloge) mora biti odbijen 403 - za razliku od ostalih
admin modula koji koriste require_portal_admin_or_hr."""

import pytest
from fastapi.testclient import TestClient

from app.api.v1 import admin_users as admin_users_module
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.dependencies import portal_auth
from app.main import app
from app.services.admin_users_service import AdminUsersService
from tests.admin_users_fakes import FakeAdminUsersRepository
from tests.fakes import FakeAuditService, FakeDb, FakePushTokenRepository, FakeSessionRepository, FakeSmsProvider, make_korisnik

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


def _admin_user(pb="admin1", **ov):
    return make_korisnik(id=1, platni_broj=pb, **ov)


def _use_portal(monkeypatch, repo, key=VALID_KEY):
    monkeypatch.setattr(portal_auth, "KorisnikRepository", lambda db: db)
    app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None, portal_service_key=key)
    app.dependency_overrides[get_db] = lambda: repo


def _headers(acting="admin1"):
    return {"X-Service-Key": VALID_KEY, "X-Acting-Platni-Broj": acting}


def _use_service(service):
    app.dependency_overrides[admin_users_module.get_admin_users_service] = lambda: service


def _wired_service(korisnici, roles=None, rasporedi=None):
    repo = FakeAdminUsersRepository(korisnici=korisnici, roles=roles, rasporedi=rasporedi)
    return AdminUsersService(
        db=FakeDb(),
        sms_provider=FakeSmsProvider(),
        repository=repo,
        session_repository=FakeSessionRepository(),
        push_token_repository=FakePushTokenRepository(),
        audit_service=FakeAuditService(),
    )


# ================================================================= OBO auth
def test_no_service_key_401(client, monkeypatch):
    _use_portal(monkeypatch, FakePortalRepo([_admin_user()], {1: ["ADMIN"]}))
    resp = client.get("/api/v1/admin/users")
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "INVALID_SERVICE_CREDENTIALS"


def test_wrong_service_key_401(client, monkeypatch):
    _use_portal(monkeypatch, FakePortalRepo([_admin_user()], {1: ["ADMIN"]}))
    resp = client.get("/api/v1/admin/users", headers={"X-Service-Key": "wrong"})
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "INVALID_SERVICE_CREDENTIALS"


def test_hr_role_rejected_403(client, monkeypatch):
    _use_portal(monkeypatch, FakePortalRepo([_admin_user()], {1: ["HR"]}))
    resp = client.get("/api/v1/admin/users", headers=_headers())
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "FORBIDDEN"


def test_zaposleni_role_rejected_403(client, monkeypatch):
    _use_portal(monkeypatch, FakePortalRepo([_admin_user()], {1: ["ZAPOSLENI"]}))
    resp = client.get("/api/v1/admin/users", headers=_headers())
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "FORBIDDEN"


def test_admin_role_allowed(client, monkeypatch):
    _use_portal(monkeypatch, FakePortalRepo([_admin_user()], {1: ["ADMIN"]}))
    _use_service(_wired_service([make_korisnik(id=1, platni_broj="admin1")]))
    resp = client.get("/api/v1/admin/users", headers=_headers())
    assert resp.status_code == 200


# ============================================================ osnovni ugovori
def _authed(monkeypatch):
    _use_portal(monkeypatch, FakePortalRepo([_admin_user()], {1: ["ADMIN"]}))


def test_list_response_shape_and_no_secrets(client, monkeypatch):
    _authed(monkeypatch)
    target = make_korisnik(id=2, platni_broj="target", lozinka_hash="argon2$secret")
    _use_service(_wired_service([_admin_user(), target], roles={2: ["ADMIN"]}))
    resp = client.get("/api/v1/admin/users", headers=_headers())
    assert resp.status_code == 200
    body = resp.json()
    assert set(body.keys()) == {"items", "page", "page_size", "total", "has_more"}
    assert "lozinka_hash" not in resp.text
    assert "argon2$secret" not in resp.text


def test_get_user_not_found_404(client, monkeypatch):
    _authed(monkeypatch)
    _use_service(_wired_service([_admin_user()]))
    resp = client.get("/api/v1/admin/users/999", headers=_headers())
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "USER_NOT_FOUND"


def test_invalid_status_filter_422(client, monkeypatch):
    _authed(monkeypatch)
    _use_service(_wired_service([_admin_user()]))
    resp = client.get(
        "/api/v1/admin/users", headers=_headers(), params={"status_zaposlenja": "BLAH"}
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"


def test_blank_search_filter_422(client, monkeypatch):
    _authed(monkeypatch)
    _use_service(_wired_service([_admin_user()]))
    resp = client.get("/api/v1/admin/users", headers=_headers(), params={"search": "   "})
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"


def test_self_lock_returns_409(client, monkeypatch):
    _authed(monkeypatch)
    _use_service(_wired_service([_admin_user()]))
    resp = client.patch("/api/v1/admin/users/1/lock", headers=_headers())
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "ADMIN_SELF_ACTION_NOT_ALLOWED"


def test_lock_unlock_happy_path(client, monkeypatch):
    _authed(monkeypatch)
    target = make_korisnik(id=2, platni_broj="target")
    _use_service(_wired_service([_admin_user(), target]))
    lock_resp = client.patch("/api/v1/admin/users/2/lock", headers=_headers())
    assert lock_resp.status_code == 200
    assert lock_resp.json()["zakljucan"] is True

    unlock_resp = client.patch("/api/v1/admin/users/2/unlock", headers=_headers())
    assert unlock_resp.status_code == 200
    assert unlock_resp.json()["zakljucan"] is False


def test_reset_password_sms_failure_returns_502(client, monkeypatch):
    _authed(monkeypatch)
    target = make_korisnik(
        id=2, platni_broj="target", status_zaposlenja="AKTIVAN", status_naloga="OMOGUCEN",
        broj_telefona="060123456",
    )
    service = AdminUsersService(
        db=FakeDb(),
        sms_provider=FakeSmsProvider(should_succeed=False),
        repository=FakeAdminUsersRepository(korisnici=[_admin_user(), target]),
        session_repository=FakeSessionRepository(),
        push_token_repository=FakePushTokenRepository(),
        audit_service=FakeAuditService(),
    )
    _use_service(service)
    resp = client.post("/api/v1/admin/users/2/reset-password", headers=_headers())
    assert resp.status_code == 502
    assert resp.json()["error"]["code"] == "SMS_DELIVERY_FAILED"
