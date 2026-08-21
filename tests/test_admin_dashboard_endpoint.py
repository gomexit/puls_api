"""HTTP-level provera admin DASHBOARD rute: OBO autentikacija (ADMIN i HR dozvoljeni)
+ osnovni ugovori odgovora."""

import pytest
from fastapi.testclient import TestClient

from app.api.v1 import admin_dashboard as dashboard_mod
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.dependencies import portal_auth
from app.main import app
from app.services.admin_dashboard_service import AdminDashboardService
from tests.admin_dashboard_fakes import FakeAdminDashboardRepository
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
    app.dependency_overrides[dashboard_mod.get_admin_dashboard_service] = lambda: service


# ================================================================= OBO auth
def test_dashboard_no_service_key_401(client, monkeypatch):
    _use_portal(monkeypatch, FakePortalRepo([_actor()], {1: ["ADMIN"]}))
    resp = client.get("/api/v1/admin/dashboard")
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "INVALID_SERVICE_CREDENTIALS"


def test_dashboard_wrong_service_key_401(client, monkeypatch):
    _use_portal(monkeypatch, FakePortalRepo([_actor()], {1: ["ADMIN"]}))
    resp = client.get("/api/v1/admin/dashboard", headers={"X-Service-Key": "wrong"})
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "INVALID_SERVICE_CREDENTIALS"


def test_dashboard_zaposleni_role_403(client, monkeypatch):
    _use_portal(monkeypatch, FakePortalRepo([_actor()], {1: ["ZAPOSLENI"]}))
    resp = client.get("/api/v1/admin/dashboard", headers=_headers())
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "FORBIDDEN"


def test_dashboard_admin_role_allowed(client, monkeypatch):
    _use_portal(monkeypatch, FakePortalRepo([_actor()], {1: ["ADMIN"]}))
    _use_service(AdminDashboardService(db=None, repository=FakeAdminDashboardRepository()))
    resp = client.get("/api/v1/admin/dashboard", headers=_headers())
    assert resp.status_code == 200


def test_dashboard_hr_role_allowed(client, monkeypatch):
    _use_portal(monkeypatch, FakePortalRepo([_actor()], {1: ["HR"]}))
    _use_service(AdminDashboardService(db=None, repository=FakeAdminDashboardRepository()))
    resp = client.get("/api/v1/admin/dashboard", headers=_headers())
    assert resp.status_code == 200


# ============================================================ osnovni ugovori
def test_dashboard_full_response_shape(client, monkeypatch):
    _use_portal(monkeypatch, FakePortalRepo([_actor()], {1: ["ADMIN"]}))
    repo = FakeAdminDashboardRepository(
        korisnici={"aktivni": 10, "neaktivni": 2, "aktivirali_aplikaciju": 8, "zakljucani": 1},
        ankete={
            "aktivne": 3,
            "zavrsene": 5,
            "broj_primalaca": 100,
            "broj_predaja": 40,
            "procenat_odziva": 40.0,
        },
        ideje={
            "nove": 7,
            "u_obradi": 4,
            "odobrene": 2,
            "odbijene": 1,
            "top_10": 3,
            "nagradjene": 1,
        },
        obavestenja={
            "objavljena": 6,
            "broj_primalaca": 60,
            "procitane": 40,
            "neprocitane": 20,
            "push_pending": 1,
            "push_sent": 55,
            "push_failed": 2,
            "push_skipped": 2,
        },
    )
    _use_service(AdminDashboardService(db=None, repository=repo))
    resp = client.get("/api/v1/admin/dashboard", headers=_headers())
    assert resp.status_code == 200
    body = resp.json()
    assert set(body.keys()) == {"korisnici", "ankete", "ideje", "obavestenja"}
    assert body["korisnici"]["aktivni"] == 10
    assert body["ankete"]["procenat_odziva"] == 40.0
    assert body["ideje"]["nagradjene"] == 1
    assert body["obavestenja"]["push_sent"] == 55
