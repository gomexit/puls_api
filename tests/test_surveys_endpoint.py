"""HTTP-level provera Survey ruta (routing + role/gating wiring), bez prave baze."""

import pytest
from fastapi.testclient import TestClient

from app.core.exceptions import ForbiddenError
from app.dependencies.auth import AuthContext, get_current_context
from app.dependencies.portal_auth import require_portal_admin_or_hr
from app.main import app
from tests.fakes import make_korisnik


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_phone_not_confirmed_blocks_surveys(client):
    korisnik = make_korisnik(obavezna_promena_lozinke="N", telefon_potvrdjen="N")
    app.dependency_overrides[get_current_context] = lambda: AuthContext(korisnik=korisnik, sesija=None)
    resp = client.get("/api/v1/surveys")
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "PHONE_CONFIRMATION_REQUIRED"


def test_employee_gets_forbidden_on_admin_surveys(client):
    def _raise():
        raise ForbiddenError()

    app.dependency_overrides[require_portal_admin_or_hr] = _raise
    resp = client.get("/api/v1/admin/surveys")
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "FORBIDDEN"


def test_patch_survey_type_blank_naziv_returns_422(client):
    app.dependency_overrides[require_portal_admin_or_hr] = lambda: make_korisnik(id=1)
    resp = client.patch("/api/v1/admin/survey-types/PULS", json={"naziv": "   "})
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"


# --- Happy-path (stub servisa, bez baze) ---
import datetime  # noqa: E402

from app.api.v1 import surveys as surveys_module  # noqa: E402
from app.dependencies.auth import get_current_ready_user  # noqa: E402
from app.models.anketa import Anketa  # noqa: E402
from app.models.anketa_ucesce import AnketaUcesce  # noqa: E402
from app.services.survey_service import NormalizedAnswer  # noqa: E402


def _anketa():
    now = datetime.datetime.now()
    return Anketa(
        id=7,
        tip_sifra="PULS",
        naziv="Zadovoljstvo",
        opis="opis",
        anonimna="D",
        status="ACTIVE",
        datum_pocetka=now - datetime.timedelta(days=1),
        datum_zavrsetka=now + datetime.timedelta(days=6),
    )


class _StubSurveyService:
    def list_surveys(self, korisnik):
        return ([{"anketa": _anketa(), "tip_naziv": "Pulse", "broj_pitanja": 3, "moj_status": "NOT_STARTED"}], 1)

    def get_detail(self, korisnik, survey_id):
        return {
            "anketa": _anketa(),
            "tip_naziv": "Pulse",
            "moj_status": "IN_PROGRESS",
            "datum_predaje": None,
            "odgovori_dostupni": True,
            "sections": [],
            "questions": [],
            "opts_by_q": {},
            "uslov_by_q": {},
            "moji_odgovori": [NormalizedAnswer(pitanje_id=1, logicka=True)],
        }

    def save_draft(self, korisnik, survey_id, odgovori):
        return "IN_PROGRESS"

    def submit(self, korisnik, survey_id, odgovori):
        u = AnketaUcesce(anketa_id=survey_id, korisnik_id=1, status="SUBMITTED")
        u.datum_predaje = datetime.datetime.now()
        return u


@pytest.fixture
def employee_client(client):
    app.dependency_overrides[get_current_ready_user] = lambda: make_korisnik(id=1)
    app.dependency_overrides[surveys_module.get_survey_service] = lambda: _StubSurveyService()
    return client


def test_list_happy_path(employee_client):
    resp = employee_client.get("/api/v1/surveys")
    assert resp.status_code == 200
    body = resp.json()
    assert body["za_popunjavanje"] == 1
    assert body["items"][0]["id"] == 7


def test_detail_happy_path(employee_client):
    resp = employee_client.get("/api/v1/surveys/7")
    assert resp.status_code == 200
    assert resp.json()["moj_status"] == "IN_PROGRESS"


def test_draft_happy_path(employee_client):
    resp = employee_client.put("/api/v1/surveys/7/draft", json={"odgovori": []})
    assert resp.status_code == 200
    assert resp.json()["moj_status"] == "IN_PROGRESS"


def test_submit_happy_path(employee_client):
    resp = employee_client.post("/api/v1/surveys/7/submit", json={"odgovori": []})
    assert resp.status_code == 200
    assert resp.json()["moj_status"] == "SUBMITTED"


# --- Admin: timezone ugovor + dupla sifra tipa ---
from app.api.v1 import admin_surveys as admin_surveys_module  # noqa: E402
from app.core.exceptions import ValidationBusinessError  # noqa: E402


def _admin_body(**overrides):
    body = {
        "naziv": "A",
        "tip_sifra": "PULS",
        "anonimna": False,
        "datum_pocetka": "2026-08-20T00:00:00",
        "datum_zavrsetka": "2026-08-25T00:00:00",
        "sekcije": [],
        "ciljevi": [],
    }
    body.update(overrides)
    return body


def test_create_survey_aware_date_returns_422(client):
    app.dependency_overrides[require_portal_admin_or_hr] = lambda: make_korisnik(id=1)
    resp = client.post(
        "/api/v1/admin/surveys", json=_admin_body(datum_pocetka="2026-08-20T00:00:00+02:00")
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"


def test_create_survey_mixed_naive_aware_returns_422_not_500(client):
    app.dependency_overrides[require_portal_admin_or_hr] = lambda: make_korisnik(id=1)
    resp = client.post(
        "/api/v1/admin/surveys",
        json=_admin_body(datum_pocetka="2026-08-20T00:00:00", datum_zavrsetka="2026-08-25T00:00:00Z"),
    )
    assert resp.status_code == 422


def test_list_filter_datum_do_before_od_returns_validation_error(client):
    app.dependency_overrides[require_portal_admin_or_hr] = lambda: make_korisnik(id=1)

    class _Stub:
        def list_surveys(self, *a, **k):
            return [], 0

    app.dependency_overrides[admin_surveys_module.get_survey_admin_service] = lambda: _Stub()
    resp = client.get(
        "/api/v1/admin/surveys",
        params={"datum_od": "2026-08-20T00:00:00", "datum_do": "2026-08-10T00:00:00"},
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"


def test_duplicate_survey_type_returns_422_not_500(client):
    app.dependency_overrides[require_portal_admin_or_hr] = lambda: make_korisnik(id=1)

    class _Stub:
        def create_type(self, *a, **k):
            raise ValidationBusinessError("Tip ankete sa ovom šifrom već postoji.")

    app.dependency_overrides[admin_surveys_module.get_survey_admin_service] = lambda: _Stub()
    resp = client.post("/api/v1/admin/survey-types", json={"sifra": "PULS", "naziv": "Pulse"})
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"