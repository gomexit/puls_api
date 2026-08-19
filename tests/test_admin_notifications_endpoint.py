"""HTTP-level provera admin Notification ruta: OBO autentikacija + osnovni ugovori."""

import datetime

import pytest
from fastapi.testclient import TestClient

from app.api.v1 import admin_notifications as admin_mod
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.dependencies import portal_auth
from app.dependencies.portal_auth import require_portal_admin_or_hr
from app.main import app
from app.services.notification_admin_service import NotificationAdminService
from app.services.notification_publishing_service import NotificationPublishingService
from tests.fakes import FakeAuditService, make_korisnik
from tests.notification_fakes import (
    FakeConfigService,
    FakeNotifDb,
    FakeNotificationRepo,
    FakeNotificationTargetingRepo,
    make_kategorija,
)

VALID_KEY = "s" * 40
FIXED_NOW = datetime.datetime(2026, 8, 19, 10, 0, 0)


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


# ---- fake OBO repo (kao u test_portal_auth) ----
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


# ================================================================= OBO auth
def test_no_service_key_401(client, monkeypatch):
    _use_portal(monkeypatch, FakePortalRepo([_admin_user()], {1: ["ADMIN"]}))
    resp = client.get("/api/v1/admin/notifications")
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "INVALID_SERVICE_CREDENTIALS"


def test_wrong_service_key_401(client, monkeypatch):
    _use_portal(monkeypatch, FakePortalRepo([_admin_user()], {1: ["ADMIN"]}))
    resp = client.get("/api/v1/admin/notifications", headers={"X-Service-Key": "wrong-key"})
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "INVALID_SERVICE_CREDENTIALS"


def test_valid_key_no_acting_403(client, monkeypatch):
    _use_portal(monkeypatch, FakePortalRepo([_admin_user()], {1: ["ADMIN"]}))
    resp = client.get("/api/v1/admin/notifications", headers={"X-Service-Key": VALID_KEY})
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "FORBIDDEN"


def test_non_admin_user_403(client, monkeypatch):
    _use_portal(monkeypatch, FakePortalRepo([_admin_user()], {1: ["ZAPOSLENI"]}))
    resp = client.get("/api/v1/admin/notifications", headers=_headers())
    assert resp.status_code == 403


def test_locked_user_403(client, monkeypatch):
    _use_portal(monkeypatch, FakePortalRepo([_admin_user(zakljucan="D")], {1: ["ADMIN"]}))
    resp = client.get("/api/v1/admin/notifications", headers=_headers())
    assert resp.status_code == 403


def test_bearer_only_rejected(client, monkeypatch):
    _use_portal(monkeypatch, FakePortalRepo([_admin_user()], {1: ["ADMIN"]}))
    resp = client.get(
        "/api/v1/admin/notifications", headers={"Authorization": "Bearer x"}
    )
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "INVALID_SERVICE_CREDENTIALS"


# ================================================================= happy path
def _wire_admin_service(repo, targeting=None):
    audit = FakeAuditService()
    db = FakeNotifDb()  # jedna deljena sesija admin+publishing
    pub = NotificationPublishingService(
        db=db,
        repository=repo,
        targeting_repository=targeting or FakeNotificationTargetingRepo(all_ids={1, 2}),
        audit_service=audit,
        configuration_service=FakeConfigService(),
        now_fn=lambda: FIXED_NOW,
    )
    return NotificationAdminService(
        db=db, repository=repo, publishing_service=pub, audit_service=audit
    )


def _as_admin_with_service(repo, targeting=None):
    app.dependency_overrides[require_portal_admin_or_hr] = lambda: _admin_user()
    svc = _wire_admin_service(repo, targeting)
    app.dependency_overrides[admin_mod.get_notification_admin_service] = lambda: svc
    return svc


def test_admin_hr_can_list(client):
    app.dependency_overrides[require_portal_admin_or_hr] = lambda: _admin_user()

    class _Stub:
        def list_notifications(self, *a, **k):
            return {"items": [], "total": 0, "page": 1, "page_size": 50}

    app.dependency_overrides[admin_mod.get_notification_admin_service] = lambda: _Stub()
    resp = client.get("/api/v1/admin/notifications", headers=_headers())
    assert resp.status_code == 200
    assert resp.json()["total"] == 0


def test_create_category_normalizes_sifra(client):
    repo = FakeNotificationRepo()
    _as_admin_with_service(repo)
    resp = client.post(
        "/api/v1/admin/notification-categories",
        headers=_headers(),
        json={"sifra": "benefiti", "naziv": "Benefiti", "aktivna": True, "redosled": 60},
    )
    assert resp.status_code == 201
    assert resp.json()["sifra"] == "BENEFITI"


def test_create_category_invalid_sifra_422(client):
    repo = FakeNotificationRepo()
    _as_admin_with_service(repo)
    resp = client.post(
        "/api/v1/admin/notification-categories",
        headers=_headers(),
        json={"sifra": "bad sifra!", "naziv": "X"},
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"


def test_full_create_publish_flow(client):
    repo = FakeNotificationRepo()
    repo.add_category(make_kategorija(sifra="ANKETA", naziv="Ankete"))
    repo.survey_ids = {25}
    _as_admin_with_service(repo, targeting=FakeNotificationTargetingRepo(all_ids={1, 2}))

    create = client.post(
        "/api/v1/admin/notifications",
        headers=_headers(),
        json={
            "kategorija_sifra": "ANKETA",
            "naslov": "Nova anketa",
            "kratak_tekst": "Popunite.",
            "sadrzaj": "Dostupna je nova anketa.",
            "akcija_tip": "SURVEY",
            "resurs_id": 25,
            "ciljevi": [{"tip_cilja": "SVI"}],
        },
    )
    assert create.status_code == 201
    body = create.json()
    nid = body["id"]
    assert body["status"] == "DRAFT" and body["kreirao_platni_broj"] == "admin1"
    assert body["sadrzaj"] == "Dostupna je nova anketa."

    pub = client.patch(
        f"/api/v1/admin/notifications/{nid}/status",
        headers=_headers(),
        json={"status": "PUBLISHED", "datum_isteka": None},
    )
    assert pub.status_code == 200
    assert pub.json()["status"] == "PUBLISHED" and pub.json()["broj_primalaca"] == 2

    stats = client.get(f"/api/v1/admin/notifications/{nid}/stats", headers=_headers())
    assert stats.status_code == 200
    assert stats.json()["broj_primalaca"] == 2 and stats.json()["procenat_procitanih"] == 0.0


def test_create_notification_rejects_extra_author_field(client):
    repo = FakeNotificationRepo()
    repo.add_category(make_kategorija())
    _as_admin_with_service(repo)
    resp = client.post(
        "/api/v1/admin/notifications",
        headers=_headers(),
        json={
            "kategorija_sifra": "OPSTE",
            "naslov": "N",
            "kratak_tekst": "K",
            "sadrzaj": "S",
            "akcija_tip": "NONE",
            "kreirao_platni_broj": "9999",
            "ciljevi": [{"tip_cilja": "SVI"}],
        },
    )
    assert resp.status_code == 422


def test_archive_with_expiry_422(client):
    repo = FakeNotificationRepo()
    repo.add_category(make_kategorija())
    _as_admin_with_service(repo)
    resp = client.patch(
        "/api/v1/admin/notifications/1/status",
        headers=_headers(),
        json={"status": "ARCHIVED", "datum_isteka": "2026-09-30T23:59:59"},
    )
    assert resp.status_code == 422


def test_list_datum_do_before_od_422(client):
    repo = FakeNotificationRepo()
    _as_admin_with_service(repo)
    resp = client.get(
        "/api/v1/admin/notifications",
        headers=_headers(),
        params={"datum_od": "2026-08-20T00:00:00", "datum_do": "2026-08-10T00:00:00"},
    )
    assert resp.status_code == 422


def test_list_aware_datum_422(client):
    repo = FakeNotificationRepo()
    _as_admin_with_service(repo)
    resp = client.get(
        "/api/v1/admin/notifications",
        headers=_headers(),
        params={"datum_od": "2026-08-20T00:00:00+02:00"},
    )
    assert resp.status_code == 422


# ---------------------------------------------------- status filter (item 2)
def _seed_draft(repo):
    from tests.notification_fakes import make_obavestenje

    repo.add_category(make_kategorija())
    return repo.seed_notification(make_obavestenje(status="DRAFT", datum_objave=None, datum_isteka=None))


def test_list_status_filter_lowercase_ok(client):
    repo = FakeNotificationRepo()
    _seed_draft(repo)
    _as_admin_with_service(repo)
    resp = client.get("/api/v1/admin/notifications", headers=_headers(), params={"status": "draft"})
    assert resp.status_code == 200
    assert resp.json()["total"] == 1


def test_list_status_filter_empty_422(client):
    repo = FakeNotificationRepo()
    _as_admin_with_service(repo)
    resp = client.get("/api/v1/admin/notifications", headers=_headers(), params={"status": "   "})
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"


def test_list_status_filter_unknown_422(client):
    repo = FakeNotificationRepo()
    _as_admin_with_service(repo)
    resp = client.get("/api/v1/admin/notifications", headers=_headers(), params={"status": "FOO"})
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"


# ---------------------------------------------- kategorija normalizacija (item 3)
def test_update_category_lowercase_path_finds_uppercase(client):
    repo = FakeNotificationRepo()
    repo.add_category(make_kategorija(sifra="ANKETA", naziv="Staro"))
    _as_admin_with_service(repo)
    resp = client.put(
        "/api/v1/admin/notification-categories/anketa",
        headers=_headers(),
        json={"naziv": "Novo", "aktivna": True, "redosled": 5},
    )
    assert resp.status_code == 200
    assert resp.json()["sifra"] == "ANKETA" and resp.json()["naziv"] == "Novo"


def test_update_category_invalid_path_422(client):
    repo = FakeNotificationRepo()
    _as_admin_with_service(repo)
    resp = client.put(
        "/api/v1/admin/notification-categories/bad%20sifra",
        headers=_headers(),
        json={"naziv": "X", "aktivna": True},
    )
    assert resp.status_code == 422


def test_draft_payload_category_lowercase_normalized(client):
    repo = FakeNotificationRepo()
    repo.add_category(make_kategorija(sifra="OPSTE"))
    _as_admin_with_service(repo)
    resp = client.post(
        "/api/v1/admin/notifications",
        headers=_headers(),
        json={
            "kategorija_sifra": "  opste  ",
            "naslov": "N",
            "kratak_tekst": "K",
            "sadrzaj": "S",
            "akcija_tip": "NONE",
            "ciljevi": [{"tip_cilja": "SVI"}],
        },
    )
    assert resp.status_code == 201
    assert resp.json()["kategorija"]["sifra"] == "OPSTE"


def test_list_category_filter_invalid_422(client):
    repo = FakeNotificationRepo()
    _as_admin_with_service(repo)
    resp = client.get(
        "/api/v1/admin/notifications", headers=_headers(), params={"category": "bad!sifra"}
    )
    assert resp.status_code == 422
