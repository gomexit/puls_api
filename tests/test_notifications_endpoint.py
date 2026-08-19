"""HTTP-level provera Inbox ruta (routing + auth/gating wiring), bez prave baze."""

import datetime

import pytest
from fastapi.testclient import TestClient

from app.api.v1 import notifications as notifications_module
from app.dependencies.auth import AuthContext, get_current_context, get_current_ready_user
from app.main import app
from app.services.notification_service import NotificationService
from tests.fakes import FakeAuditService, make_korisnik
from tests.notification_fakes import (
    FakeNotifDb,
    FakeNotificationRepo,
    make_kategorija,
    make_obavestenje,
    make_primalac,
)

FIXED_NOW = datetime.datetime(2026, 8, 18, 10, 0, 0)


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _seeded_repo():
    repo = FakeNotificationRepo()
    repo.add_category(make_kategorija(sifra="ANKETA", naziv="Ankete"))
    o = repo.seed_notification(
        make_obavestenje(
            kategorija_sifra="ANKETA",
            naslov="Nova anketa",
            kratak_tekst="Popunite novu anketu.",
            akcija_tip="SURVEY",
            resurs_id=10,
        )
    )
    repo.seed_recipient(make_primalac(o.id, korisnik_id=1, procitano="N"))
    return repo, o


def _use_service(repo):
    def _factory():
        return NotificationService(
            db=FakeNotifDb(),
            repository=repo,
            audit_service=FakeAuditService(),
            now_fn=lambda: FIXED_NOW,
        )

    app.dependency_overrides[notifications_module.get_notification_service] = _factory


def _as_user(korisnik):
    app.dependency_overrides[get_current_ready_user] = lambda: korisnik


# ------------------------------------------------------------------ auth/gating
def test_unauthorized_returns_invalid_session(client):
    resp = client.get("/api/v1/notifications")
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "INVALID_SESSION"


def test_first_login_flow_blocks_inbox(client):
    korisnik = make_korisnik(obavezna_promena_lozinke="D", telefon_potvrdjen="D")
    app.dependency_overrides[get_current_context] = lambda: AuthContext(
        korisnik=korisnik, sesija=None
    )
    resp = client.get("/api/v1/notifications")
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "PASSWORD_CHANGE_REQUIRED"


# ------------------------------------------------------------------ list/detail
def test_list_contract(client):
    repo, o = _seeded_repo()
    _use_service(repo)
    _as_user(make_korisnik(id=1))
    resp = client.get("/api/v1/notifications")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1 and body["unread_count"] == 1 and body["has_more"] is False
    item = body["items"][0]
    assert item["id"] == o.id
    assert item["kategorija"] == {"sifra": "ANKETA", "naziv": "Ankete"}
    assert item["procitano"] is False
    assert item["akcija"] == {"tip": "SURVEY", "resurs_id": 10, "url": None}
    assert "sadrzaj" not in item


def test_detail_includes_sadrzaj(client):
    repo, o = _seeded_repo()
    _use_service(repo)
    _as_user(make_korisnik(id=1))
    resp = client.get(f"/api/v1/notifications/{o.id}")
    assert resp.status_code == 200
    assert resp.json()["sadrzaj"]


def test_missing_notification_returns_404(client):
    repo, _ = _seeded_repo()
    _use_service(repo)
    _as_user(make_korisnik(id=1))
    resp = client.get("/api/v1/notifications/99999")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "NOTIFICATION_NOT_FOUND"


def test_foreign_notification_returns_404(client):
    repo, o = _seeded_repo()
    _use_service(repo)
    _as_user(make_korisnik(id=2))  # nije primalac
    resp = client.get(f"/api/v1/notifications/{o.id}")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "NOTIFICATION_NOT_FOUND"


# ------------------------------------------------------------------ unread-count route
def test_unread_count_route_not_shadowed(client):
    repo, _ = _seeded_repo()
    _use_service(repo)
    _as_user(make_korisnik(id=1))
    resp = client.get("/api/v1/notifications/unread-count")
    assert resp.status_code == 200
    assert resp.json() == {"unread_count": 1}


def test_category_filter_normalized_uppercase(client):
    repo, o = _seeded_repo()  # kategorija 'ANKETA'
    _use_service(repo)
    _as_user(make_korisnik(id=1))
    # malim slovima + razmaci -> normalizuje se u 'ANKETA' i pronalazi obavestenje
    resp = client.get("/api/v1/notifications", params={"category": "  anketa  "})
    assert resp.status_code == 200
    assert resp.json()["total"] == 1


def test_blank_category_returns_422(client):
    repo, _ = _seeded_repo()
    _use_service(repo)
    _as_user(make_korisnik(id=1))
    resp = client.get("/api/v1/notifications", params={"category": "   "})
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"


def test_too_long_category_returns_422(client):
    repo, _ = _seeded_repo()
    _use_service(repo)
    _as_user(make_korisnik(id=1))
    resp = client.get("/api/v1/notifications", params={"category": "X" * 51})
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"


def test_invalid_read_status_returns_422(client):
    repo, _ = _seeded_repo()
    _use_service(repo)
    _as_user(make_korisnik(id=1))
    resp = client.get("/api/v1/notifications", params={"read_status": "NOPE"})
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"


# ------------------------------------------------------------------ read/unread
def test_mark_read_then_unread_flow(client):
    repo, o = _seeded_repo()
    _use_service(repo)
    _as_user(make_korisnik(id=1))

    resp = client.patch(f"/api/v1/notifications/{o.id}/read")
    assert resp.status_code == 200
    body = resp.json()
    assert body["procitano"] is True and body["datum_citanja"] is not None
    assert body["unread_count"] == 0

    first_date = body["datum_citanja"]
    # Idempotentno: ponovljeni read ne menja datum.
    resp2 = client.patch(f"/api/v1/notifications/{o.id}/read")
    assert resp2.json()["datum_citanja"] == first_date

    resp3 = client.patch(f"/api/v1/notifications/{o.id}/unread")
    assert resp3.status_code == 200
    assert resp3.json()["procitano"] is False
    assert resp3.json()["datum_citanja"] is None
    assert resp3.json()["unread_count"] == 1


def test_mark_read_foreign_returns_404(client):
    repo, o = _seeded_repo()
    _use_service(repo)
    _as_user(make_korisnik(id=2))
    resp = client.patch(f"/api/v1/notifications/{o.id}/read")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "NOTIFICATION_NOT_FOUND"
