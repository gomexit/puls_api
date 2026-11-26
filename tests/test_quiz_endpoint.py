"""HTTP provera modula PULS IZAZOV: OBO admin, Bearer zaposleni, greske i OpenAPI."""

import pytest
from fastapi.testclient import TestClient

from app.api.v1 import admin_quizzes as admin_mod
from app.api.v1 import home as home_mod
from app.api.v1 import quizzes as employee_mod
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.dependencies import portal_auth
from app.dependencies.auth import get_current_ready_user
from app.main import app
from app.services.home_summary_service import HomeSummaryService
from app.services.quiz_admin_service import QuizAdminService
from app.services.quiz_service import QuizService
from tests.fakes import FakeAuditService, FakeSystemNotificationService, make_korisnik
from tests.quiz_fakes import (
    FIXED_NOW,
    FakeAccessRepo,
    FakeModuleAccess,
    FakeQuizDb,
    FakeQuizRepo,
    quiz_payload,
    seed_quiz,
)

VALID_KEY = "q" * 40
ADMIN = "/api/v1/admin/quizzes"
CATS = "/api/v1/admin/quiz-categories"


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


class Env:
    def __init__(self):
        self.db = FakeQuizDb()
        self.repo = FakeQuizRepo()
        self.audit = FakeAuditService()
        self.notif = FakeSystemNotificationService()
        self.module = FakeModuleAccess()

    def admin(self):
        return QuizAdminService(
            db=self.db, repository=self.repo, audit_service=self.audit,
            system_notification_service=self.notif, settings=Settings(_env_file=None), now_fn=lambda: FIXED_NOW,
        )

    def employee(self):
        return QuizService(
            db=self.db, repository=self.repo, module_access=self.module,
            access_repository=FakeAccessRepo(), now_fn=lambda: FIXED_NOW,
        )


def _wire(env):
    app.dependency_overrides[admin_mod.get_quiz_admin_service] = env.admin
    app.dependency_overrides[employee_mod.get_quiz_service] = env.employee


class FakePortalRepo:
    def __init__(self, users, roles):
        self._users = {u.platni_broj: u for u in users}
        self._roles = roles

    def get_by_platni_broj(self, pb):
        return self._users.get(pb)

    def get_active_role_codes(self, kid):
        return self._roles.get(kid, [])


def _use_portal(monkeypatch, roles=("HR",)):
    repo = FakePortalRepo([make_korisnik(id=1, platni_broj="admin1")], {1: list(roles)})
    monkeypatch.setattr(portal_auth, "KorisnikRepository", lambda db: db)
    app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None, portal_service_key=VALID_KEY)
    app.dependency_overrides[get_db] = lambda: repo


H = {"X-Service-Key": VALID_KEY, "X-Acting-Platni-Broj": "admin1"}


def _json(payload):
    out = dict(payload)
    out["datum_od"] = payload["datum_od"].isoformat()
    out["datum_do"] = payload["datum_do"].isoformat()
    return out


def _as_employee(id=10):
    app.dependency_overrides[get_current_ready_user] = lambda: make_korisnik(
        id=id, platni_broj=f"E{id}", obavezna_promena_lozinke="N", telefon_potvrdjen="D"
    )


# ================================================================= admin
def test_admin_requires_key_and_role(client, monkeypatch):
    _use_portal(monkeypatch, roles=("ZAPOSLENI",))
    _wire(Env())
    assert client.get(ADMIN).status_code == 401
    assert client.get(ADMIN, headers=H).status_code == 403
    assert client.get(CATS, headers=H).status_code == 403


def test_admin_category_and_quiz_lifecycle(client, monkeypatch):
    _use_portal(monkeypatch)
    env = Env()
    _wire(env)

    resp = client.post(CATS, headers=H, json={"sifra": "akcije", "naziv": " Akcije ", "redosled": 3})
    assert resp.status_code == 201 and resp.json()["sifra"] == "AKCIJE"
    assert client.post(CATS, headers=H, json={"sifra": "AKCIJE", "naziv": "X"}).json()["error"]["code"] == "QUIZ_CATEGORY_ALREADY_EXISTS"
    assert client.put(f"{CATS}/NEMA", headers=H, json={"naziv": "X"}).status_code == 404
    assert len(client.get(CATS, headers=H).json()["items"]) == 3

    resp = client.post(ADMIN, headers=H, json=_json(quiz_payload()))
    assert resp.status_code == 201, resp.text
    quiz = resp.json()
    assert quiz["status"] == "DRAFT" and len(quiz["pitanja"]) == 5

    aware = _json(quiz_payload())
    aware["datum_od"] += "+01:00"
    assert client.post(ADMIN, headers=H, json=aware).status_code == 422

    resp = client.patch(f"{ADMIN}/{quiz['id']}/status", headers=H, json={"status": "OBJAVLJEN"})
    assert resp.status_code == 200 and resp.json()["status"] == "OBJAVLJEN"
    resp = client.put(f"{ADMIN}/{quiz['id']}", headers=H, json={"trajanje_sekundi": 60})
    assert resp.status_code == 409 and resp.json()["error"]["code"] == "QUIZ_LOCKED"
    resp = client.put(f"{ADMIN}/{quiz['id']}", headers=H, json={"naziv": "Novi"})
    assert resp.status_code == 200 and resp.json()["naziv"] == "Novi" and resp.json()["opis"] == "Prvi nedeljni kviz"

    body = client.get(ADMIN, headers=H, params={"status": "objavljen"}).json()
    assert body["total"] == 1 and body["items"][0]["broj_pitanja"] == 5
    assert client.get(ADMIN, headers=H, params={"status": "X"}).json()["error"]["code"] == "INVALID_QUIZ_STATUS"
    assert client.get(f"{ADMIN}/999", headers=H).status_code == 404
    res = client.get(f"{ADMIN}/{quiz['id']}/results", headers=H).json()
    assert res["broj_pokusaja"] == 0 and len(res["po_pitanju"]) == 5
    assert [e["sifra_akcije"] for e in env.audit.entries] == [
        "ADMIN_QUIZ_CATEGORY_CREATED", "ADMIN_QUIZ_CREATED", "ADMIN_QUIZ_PUBLISHED", "ADMIN_QUIZ_UPDATED",
    ]


# ============================================================== zaposleni
def test_employee_requires_bearer(client):
    assert client.get("/api/v1/quizzes/current").status_code == 401


def test_employee_play_over_http(client):
    env = Env()
    kviz = seed_quiz(env.repo)
    _wire(env)
    _as_employee()
    cur = client.get("/api/v1/quizzes/current").json()
    assert cur["kviz"]["id"] == kviz.id and cur["pokusaj"] is None

    play = client.post(f"/api/v1/quizzes/{kviz.id}/start")
    assert play.status_code == 200
    body = play.json()
    assert "tacna" not in play.text and body["preostalo_sekundi"] == 120
    pid = body["pokusaj_id"]
    q = body["pitanja"][0]
    resp = client.post(f"/api/v1/quiz-attempts/{pid}/answers", json={"pitanje_id": q["id"], "opcija_id": q["opcije"][0]["id"]})
    assert resp.status_code == 200 and resp.json()["tacna_opcija_id"] == q["opcije"][1]["id"]
    assert client.get(f"/api/v1/quiz-attempts/{pid}/result").json()["error"]["code"] == "QUIZ_ATTEMPT_IN_PROGRESS"
    res = client.post(f"/api/v1/quiz-attempts/{pid}/finish").json()
    assert res["broj_tacnih"] == 0 and res["broj_pitanja"] == 5
    again = client.post(f"/api/v1/quizzes/{kviz.id}/start")
    assert again.status_code == 409 and again.json()["error"]["code"] == "QUIZ_ALREADY_PLAYED"

    _as_employee(id=11)
    assert client.get(f"/api/v1/quiz-attempts/{pid}/result").status_code == 404


def test_home_summary_shows_quiz_badge(client):
    env = Env()
    seed_quiz(env.repo)
    app.dependency_overrides[home_mod.get_home_summary_service] = lambda: HomeSummaryService(
        env.module, badge_counters={"KVIZ": env.employee().badge_count}
    )
    _as_employee()
    moduli = {m["kod"]: m for m in client.get("/api/v1/home/summary").json()["moduli"]}
    assert moduli["KVIZ"]["aktivan"] is True and moduli["KVIZ"]["broj_novih"] == 1
    assert moduli["POGODNOSTI"]["broj_novih"] == 0


def test_openapi_documents_quiz_routes():
    paths = app.openapi()["paths"]
    for path in (
        "/api/v1/quizzes/current",
        "/api/v1/quizzes/{kviz_id}/start",
        "/api/v1/quiz-attempts/{pokusaj_id}/answers",
        "/api/v1/quiz-attempts/{pokusaj_id}/finish",
        "/api/v1/quiz-attempts/{pokusaj_id}/result",
        "/api/v1/admin/quizzes",
        "/api/v1/admin/quizzes/{kviz_id}/status",
        "/api/v1/admin/quizzes/{kviz_id}/results",
        "/api/v1/admin/quiz-categories",
        "/api/v1/admin/quiz-categories/{sifra}",
    ):
        assert path in paths
