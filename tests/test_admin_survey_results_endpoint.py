"""HTTP-level provera admin SURVEY-RESULT ruta: OBO autentikacija + osnovni ugovori."""

import datetime

import pytest
from fastapi.testclient import TestClient

from app.api.v1 import admin_survey_results as results_mod
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.dependencies import portal_auth
from app.main import app
from app.services.survey_results_service import SurveyResultsService
from tests.fakes import make_korisnik
from tests.survey_fakes import FakeSurveyRepo, add_opcija, add_pitanje, add_sekcija, make_anketa
from tests.survey_results_fakes import FakeSurveyResultsRepo, make_odgovor, make_odgovor_opcija, make_predaja

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
    app.dependency_overrides[results_mod.get_survey_results_service] = lambda: service


# ================================================================= OBO auth
def test_statistics_no_service_key_401(client, monkeypatch):
    _use_portal(monkeypatch, FakePortalRepo([_admin_user()], {1: ["ADMIN"]}))
    resp = client.get("/api/v1/admin/surveys/1/statistics")
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "INVALID_SERVICE_CREDENTIALS"


def test_statistics_wrong_service_key_401(client, monkeypatch):
    _use_portal(monkeypatch, FakePortalRepo([_admin_user()], {1: ["ADMIN"]}))
    resp = client.get("/api/v1/admin/surveys/1/statistics", headers={"X-Service-Key": "wrong"})
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "INVALID_SERVICE_CREDENTIALS"


def test_statistics_no_acting_header_403(client, monkeypatch):
    _use_portal(monkeypatch, FakePortalRepo([_admin_user()], {1: ["ADMIN"]}))
    resp = client.get("/api/v1/admin/surveys/1/statistics", headers={"X-Service-Key": VALID_KEY})
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "FORBIDDEN"


def test_statistics_nonexistent_acting_user_403(client, monkeypatch):
    _use_portal(monkeypatch, FakePortalRepo([], {}))
    resp = client.get("/api/v1/admin/surveys/1/statistics", headers=_headers("nepostojeci"))
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "FORBIDDEN"


def test_statistics_zaposleni_role_403(client, monkeypatch):
    _use_portal(monkeypatch, FakePortalRepo([_admin_user()], {1: ["ZAPOSLENI"]}))
    resp = client.get("/api/v1/admin/surveys/1/statistics", headers=_headers())
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "FORBIDDEN"


def test_statistics_admin_role_allowed(client, monkeypatch):
    repo = FakeSurveyRepo()
    a = make_anketa(repo, status="CLOSED")
    _use_portal(monkeypatch, FakePortalRepo([_admin_user()], {1: ["ADMIN"]}))
    _use_service(SurveyResultsService(db=None, results_repository=FakeSurveyResultsRepo(repo), survey_repository=repo))
    resp = client.get(f"/api/v1/admin/surveys/{a.id}/statistics", headers=_headers())
    assert resp.status_code == 200
    assert resp.json()["survey_id"] == a.id


def test_statistics_hr_role_allowed(client, monkeypatch):
    repo = FakeSurveyRepo()
    a = make_anketa(repo, status="CLOSED")
    _use_portal(monkeypatch, FakePortalRepo([_admin_user()], {1: ["HR"]}))
    _use_service(SurveyResultsService(db=None, results_repository=FakeSurveyResultsRepo(repo), survey_repository=repo))
    resp = client.get(f"/api/v1/admin/surveys/{a.id}/statistics", headers=_headers())
    assert resp.status_code == 200


def test_responses_bearer_only_rejected(client, monkeypatch):
    _use_portal(monkeypatch, FakePortalRepo([_admin_user()], {1: ["ADMIN"]}))
    resp = client.get(
        "/api/v1/admin/surveys/1/responses", headers={"Authorization": "Bearer nekitoken"}
    )
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "INVALID_SERVICE_CREDENTIALS"


# ============================================================ osnovni ugovori
def _authed(monkeypatch):
    _use_portal(monkeypatch, FakePortalRepo([_admin_user()], {1: ["ADMIN"]}))


def test_statistics_survey_not_found_404(client, monkeypatch):
    _authed(monkeypatch)
    repo = FakeSurveyRepo()
    _use_service(SurveyResultsService(db=None, results_repository=FakeSurveyResultsRepo(repo), survey_repository=repo))
    resp = client.get("/api/v1/admin/surveys/999/statistics", headers=_headers())
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "SURVEY_NOT_FOUND"


def test_statistics_full_shape(client, monkeypatch):
    _authed(monkeypatch)
    repo = FakeSurveyRepo()
    a = make_anketa(repo, status="CLOSED")
    sec = add_sekcija(repo, a.id)
    q = add_pitanje(repo, sec.id, "SINGLE_CHOICE", redosled=1)
    opt = add_opcija(repo, q.id, redosled=1, tekst="OK")
    p = make_predaja(repo, a.id, korisnik_id=1)
    od = make_odgovor(repo, p.id, q.id)
    make_odgovor_opcija(repo, od.id, opt.id)
    _use_service(SurveyResultsService(db=None, results_repository=FakeSurveyResultsRepo(repo), survey_repository=repo))

    resp = client.get(f"/api/v1/admin/surveys/{a.id}/statistics", headers=_headers())
    assert resp.status_code == 200
    body = resp.json()
    assert set(body.keys()) >= {"survey_id", "naziv", "anonimna", "status", "odziv", "pitanja"}
    assert body["pitanja"][0]["opcije"][0]["opcija_id"] == opt.id


def test_statistics_text_question_excludes_null_fields(client, monkeypatch):
    _authed(monkeypatch)
    repo = FakeSurveyRepo()
    a = make_anketa(repo, status="CLOSED")
    sec = add_sekcija(repo, a.id)
    q = add_pitanje(repo, sec.id, "TEXT", redosled=1)
    p = make_predaja(repo, a.id, korisnik_id=1)
    make_odgovor(repo, p.id, q.id, tekst="neki odgovor")
    _use_service(SurveyResultsService(db=None, results_repository=FakeSurveyResultsRepo(repo), survey_repository=repo))

    resp = client.get(f"/api/v1/admin/surveys/{a.id}/statistics", headers=_headers())
    assert resp.status_code == 200
    pitanje = resp.json()["pitanja"][0]
    for field in ("opcije", "da", "ne", "prosek", "medijana", "minimum", "maksimum", "raspodela"):
        assert field not in pitanje


def test_responses_anonymous_survey_409(client, monkeypatch):
    _authed(monkeypatch)
    repo = FakeSurveyRepo()
    a = make_anketa(repo, status="CLOSED", anonimna="D")
    _use_service(SurveyResultsService(db=None, results_repository=FakeSurveyResultsRepo(repo), survey_repository=repo))
    resp = client.get(f"/api/v1/admin/surveys/{a.id}/responses", headers=_headers())
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "ANONYMOUS_SURVEY_RESPONSES_NOT_AVAILABLE"


def test_responses_datum_do_before_od_422(client, monkeypatch):
    _authed(monkeypatch)
    repo = FakeSurveyRepo()
    a = make_anketa(repo, status="CLOSED", anonimna="N")
    _use_service(SurveyResultsService(db=None, results_repository=FakeSurveyResultsRepo(repo), survey_repository=repo))
    resp = client.get(
        f"/api/v1/admin/surveys/{a.id}/responses",
        headers=_headers(),
        params={"datum_od": "2026-02-01T00:00:00", "datum_do": "2026-01-01T00:00:00"},
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"


def test_responses_timezone_aware_datum_422(client, monkeypatch):
    _authed(monkeypatch)
    repo = FakeSurveyRepo()
    a = make_anketa(repo, status="CLOSED", anonimna="N")
    _use_service(SurveyResultsService(db=None, results_repository=FakeSurveyResultsRepo(repo), survey_repository=repo))
    resp = client.get(
        f"/api/v1/admin/surveys/{a.id}/responses",
        headers=_headers(),
        params={"datum_od": "2026-01-01T00:00:00+02:00"},
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"


def test_responses_blank_platni_broj_filter_422(client, monkeypatch):
    _authed(monkeypatch)
    repo = FakeSurveyRepo()
    a = make_anketa(repo, status="CLOSED", anonimna="N")
    _use_service(SurveyResultsService(db=None, results_repository=FakeSurveyResultsRepo(repo), survey_repository=repo))
    resp = client.get(
        f"/api/v1/admin/surveys/{a.id}/responses", headers=_headers(), params={"platni_broj": "   "}
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"


def test_responses_too_long_orgjed_filter_422(client, monkeypatch):
    _authed(monkeypatch)
    repo = FakeSurveyRepo()
    a = make_anketa(repo, status="CLOSED", anonimna="N")
    _use_service(SurveyResultsService(db=None, results_repository=FakeSurveyResultsRepo(repo), survey_repository=repo))
    resp = client.get(
        f"/api/v1/admin/surveys/{a.id}/responses",
        headers=_headers(),
        params={"orgjed_sifra": "X" * 51},
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"


def test_responses_happy_path_shape(client, monkeypatch):
    _authed(monkeypatch)
    repo = FakeSurveyRepo()
    a = make_anketa(repo, status="CLOSED", anonimna="N")
    sec = add_sekcija(repo, a.id)
    q = add_pitanje(repo, sec.id, "SINGLE_CHOICE", redosled=1)
    opt = add_opcija(repo, q.id, redosled=1, tekst="Zadovoljan")
    k = make_korisnik(id=15, platni_broj="12345", ime="Petar", prezime="Petrović")
    now = datetime.datetime(2026, 1, 1, 10, 0, 0)
    p = make_predaja(repo, a.id, korisnik_id=15, datum_predaje=now)
    od = make_odgovor(repo, p.id, q.id)
    make_odgovor_opcija(repo, od.id, opt.id)
    results_repo = FakeSurveyResultsRepo(repo, korisnici=[k])
    _use_service(SurveyResultsService(db=None, results_repository=results_repo, survey_repository=repo))

    resp = client.get(f"/api/v1/admin/surveys/{a.id}/responses", headers=_headers())
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    item = body["items"][0]
    assert item["korisnik"]["korisnik_id"] == 15
    assert item["korisnik"]["platni_broj"] == "12345"
    assert item["odgovori"][0]["opcije"][0]["opcija_id"] == opt.id
