"""HTTP-level tests for the Ideas / Admin Ideas endpoints using dependency
overrides, so no real Oracle connection is required."""

import pytest
from fastapi.testclient import TestClient

from app.core.exceptions import ForbiddenError
from app.dependencies import roles as roles_module
from app.dependencies.auth import AuthContext, get_current_context
from app.dependencies.roles import require_admin_or_hr, require_roles
from app.main import app
from app.api.v1 import admin_ideas as admin_ideas_module
from app.api.v1 import ideas as ideas_module
from app.services.idea_service import RankedIdea
from tests.fakes import make_ciklus, make_ideja, make_korisnik


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


# --- First-login gating (points 13 & 14) ---
def test_password_change_required_blocks_ideas(client):
    korisnik = make_korisnik(obavezna_promena_lozinke="D", telefon_potvrdjen="D")
    app.dependency_overrides[get_current_context] = lambda: AuthContext(
        korisnik=korisnik, sesija=None
    )
    resp = client.get("/api/v1/ideas/current-cycle")
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "PASSWORD_CHANGE_REQUIRED"


def test_phone_confirmation_required_blocks_ideas(client):
    korisnik = make_korisnik(obavezna_promena_lozinke="N", telefon_potvrdjen="N")
    app.dependency_overrides[get_current_context] = lambda: AuthContext(
        korisnik=korisnik, sesija=None
    )
    resp = client.get("/api/v1/ideas/current-cycle")
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "PHONE_CONFIRMATION_REQUIRED"


# --- Admin authorization (points 15 & 16) ---
def test_employee_gets_forbidden_on_admin_route(client):
    def _raise_forbidden():
        raise ForbiddenError()

    app.dependency_overrides[require_admin_or_hr] = _raise_forbidden
    resp = client.get("/api/v1/admin/idea-cycles")
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "FORBIDDEN"


def test_hr_can_access_admin_route(client):
    hr_user = make_korisnik(id=1, obavezna_promena_lozinke="N", telefon_potvrdjen="D")
    app.dependency_overrides[require_admin_or_hr] = lambda: hr_user

    class _StubAdminService:
        def list_cycles(self):
            return [make_ciklus(id=1, status="PLANIRAN")]

    app.dependency_overrides[admin_ideas_module.get_idea_admin_service] = lambda: _StubAdminService()
    resp = client.get("/api/v1/admin/idea-cycles")
    assert resp.status_code == 200
    assert len(resp.json()["items"]) == 1


# --- Top list DTO hides sensitive data (point 12) ---
def test_top_list_hides_sensitive_fields(client):
    ready = make_korisnik(obavezna_promena_lozinke="N", telefon_potvrdjen="D")
    app.dependency_overrides[ideas_module.get_current_ready_user] = lambda: ready

    sensitive = make_ideja(
        id=5,
        status="TOP_10",
        opis="TAJNI OPIS",
        platni_broj="99999",
        orgjed_sifra="ORG-SECRET",
        hr_ocena=9,
    )

    class _StubIdeaService:
        def list_top(self, cycle_id=None):
            return [RankedIdea(rang=1, ideja=sensitive)]

    app.dependency_overrides[ideas_module.get_idea_service] = lambda: _StubIdeaService()
    resp = client.get("/api/v1/ideas/top")
    assert resp.status_code == 200
    item = resp.json()["items"][0]
    assert set(item.keys()) == {"id", "rang", "ime", "prezime", "naslov", "status"}
    body = resp.text
    assert "TAJNI OPIS" not in body
    assert "99999" not in body
    assert "ORG-SECRET" not in body


# --- require_roles unit-level behavior ---
def test_require_roles_allows_matching_role(monkeypatch):
    class _Repo:
        def __init__(self, db):
            pass

        def get_active_role_codes(self, korisnik_id):
            return ["HR"]

    monkeypatch.setattr(roles_module, "KorisnikRepository", _Repo)
    dep = require_roles("ADMIN", "HR")
    korisnik = make_korisnik(id=1)
    assert dep(korisnik=korisnik, db=None) is korisnik


def test_require_roles_denies_without_role(monkeypatch):
    class _Repo:
        def __init__(self, db):
            pass

        def get_active_role_codes(self, korisnik_id):
            return ["ZAPOSLENI"]

    monkeypatch.setattr(roles_module, "KorisnikRepository", _Repo)
    dep = require_roles("ADMIN", "HR")
    with pytest.raises(ForbiddenError):
        dep(korisnik=make_korisnik(id=1), db=None)