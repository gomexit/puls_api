"""Employee push-token API + servis. Bez prave baze; token se nikad ne vraca/loguje."""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.api.v1 import push as push_module
from app.dependencies.auth import AuthContext, get_current_context
from app.main import app
from app.services.audit_service import AuditAction
from app.services.push_token_service import PushTokenService
from tests.fakes import FakeAuditService, FakePushTokenRepository, make_korisnik
from tests.notification_fakes import FakeNotifDb


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _ctx(korisnik_id=1, uredjaj="dev-1"):
    return AuthContext(
        korisnik=make_korisnik(id=korisnik_id, platni_broj=f"p{korisnik_id}"),
        sesija=SimpleNamespace(uredjaj_id=uredjaj),
    )


def _wire(repo=None, audit=None):
    repo = repo or FakePushTokenRepository()
    audit = audit or FakeAuditService()
    svc = PushTokenService(db=FakeNotifDb(), token_repository=repo, audit_service=audit)
    app.dependency_overrides[push_module.get_push_token_service] = lambda: svc
    return repo, audit


# ------------------------------------------------------------------ HTTP
def test_register_uses_context_identity(client):
    repo, audit = _wire()
    app.dependency_overrides[get_current_context] = lambda: _ctx(1, "dev-1")
    resp = client.put("/api/v1/push/token", json={"fcm_token": "tok-abc", "app_version": "1.0.0"})
    assert resp.status_code == 200
    assert resp.json() == {"registered": True}
    # token upisan za (korisnik 1, dev-1) iz konteksta
    assert repo.tokens[(1, "dev-1")]["token"] == "tok-abc"
    # response ne sadrzi token
    assert "tok-abc" not in resp.text
    # audit ne sadrzi token
    assert all("tok-abc" not in str(e) for e in audit.entries)
    assert any(e["sifra_akcije"] == AuditAction.PUSH_TOKEN_REGISTERED for e in audit.entries)


def test_payload_cannot_send_identity(client):
    _wire()
    app.dependency_overrides[get_current_context] = lambda: _ctx()
    for extra in ({"korisnik_id": 5}, {"platni_broj": "999"}, {"uredjaj_id": "x"}):
        resp = client.put("/api/v1/push/token", json={"fcm_token": "t", **extra})
        assert resp.status_code == 422


def test_empty_and_control_char_token_rejected(client):
    _wire()
    app.dependency_overrides[get_current_context] = lambda: _ctx()
    assert client.put("/api/v1/push/token", json={"fcm_token": "   "}).status_code == 422
    assert client.put("/api/v1/push/token", json={"fcm_token": "a\x00b"}).status_code == 422


def test_delete_deactivates_current_device_only(client):
    repo, _ = _wire()
    repo.upsert(1, "dev-1", "tok-1", None)
    repo.upsert(1, "dev-2", "tok-2", None)  # ovo deaktivira dev-1 (jedan aktivan uredjaj)
    # reaktiviraj dev-1 da simuliramo dva reda (jedan aktivan)
    repo.tokens[(1, "dev-1")]["aktivan"] = "D"
    app.dependency_overrides[get_current_context] = lambda: _ctx(1, "dev-1")
    resp = client.delete("/api/v1/push/token")
    assert resp.status_code == 200
    assert resp.json() == {"deactivated": True}
    assert repo.tokens[(1, "dev-1")]["aktivan"] == "N"
    assert repo.tokens[(1, "dev-2")]["aktivan"] == "D"


# ------------------------------------------------------------------ servis
def test_upsert_and_new_token_deactivates_old():
    repo = FakePushTokenRepository()
    svc = PushTokenService(db=FakeNotifDb(), token_repository=repo, audit_service=FakeAuditService())
    k = make_korisnik(id=7, platni_broj="p7")
    svc.register(k, "dev-A", "tok-A", "1.0.0")
    svc.register(k, "dev-B", "tok-B", "1.0.1")  # novi uredjaj deaktivira stari
    assert repo.tokens[(7, "dev-A")]["aktivan"] == "N"
    assert repo.tokens[(7, "dev-B")]["aktivan"] == "D"
    # upsert istog uredjaja azurira token (ostaje jedan red)
    svc.register(k, "dev-B", "tok-B2", None)
    assert repo.tokens[(7, "dev-B")]["token"] == "tok-B2"


# --------------------------------------------------- item 1: konkurentni unique konflikt
def test_active_index_conflict_translates_to_push_token_conflict_error():
    from sqlalchemy.exc import IntegrityError

    from app.core.exceptions import PushTokenConflictError

    repo = FakePushTokenRepository()

    def _boom(*a, **k):
        raise IntegrityError("stmt", {}, Exception("ORA-00001: UX_PUSH_TOKEN_AKTIVAN_HASH"))

    repo.upsert = _boom
    svc = PushTokenService(db=FakeNotifDb(), token_repository=repo, audit_service=FakeAuditService())
    with pytest.raises(PushTokenConflictError):
        svc.register(make_korisnik(id=1), "dev-1", "tok-1", None)


def test_active_kor_index_conflict_also_translates():
    from sqlalchemy.exc import IntegrityError

    from app.core.exceptions import PushTokenConflictError

    repo = FakePushTokenRepository()

    def _boom(*a, **k):
        raise IntegrityError("stmt", {}, Exception("ORA-00001: UX_PUSH_TOKEN_AKTIVAN_KOR"))

    repo.upsert = _boom
    svc = PushTokenService(db=FakeNotifDb(), token_repository=repo, audit_service=FakeAuditService())
    with pytest.raises(PushTokenConflictError):
        svc.register(make_korisnik(id=1), "dev-1", "tok-1", None)


def test_unrelated_integrity_error_propagates_unmasked():
    from sqlalchemy.exc import IntegrityError

    repo = FakePushTokenRepository()

    def _boom(*a, **k):
        raise IntegrityError("stmt", {}, Exception("ORA-02291: FK_PUSH_TOKEN_KORISNIK nepovezano"))

    repo.upsert = _boom
    svc = PushTokenService(db=FakeNotifDb(), token_repository=repo, audit_service=FakeAuditService())
    with pytest.raises(IntegrityError):
        svc.register(make_korisnik(id=1), "dev-1", "tok-1", None)
