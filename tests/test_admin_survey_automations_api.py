"""HTTP-level provera admin SURVEY-AUTOMATIONS ruta: OBO autentikacija + poslovna
pravila (404/409/422) + idempotentnost."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from app.api.v1 import admin_survey_automations as automations_mod
from app.core.config import Settings, get_settings
from app.core.exceptions import SurveyAutomationConflictError
from app.db.session import get_db
from app.dependencies import portal_auth
from app.main import app
from app.repositories.onboarding_automation_repository import OnboardingAutomationRepository
from app.services.audit_service import AuditService
from app.services.onboarding_automation_admin_service import OnboardingAutomationAdminService
from tests.fakes import FakeDb, make_korisnik
from tests.survey_fakes import FakeSurveyRepo, make_anketa

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


def _actor(pb="admin1", **ov):
    return make_korisnik(id=1, platni_broj=pb, **ov)


def _use_portal(monkeypatch, repo, key=VALID_KEY):
    monkeypatch.setattr(portal_auth, "KorisnikRepository", lambda db: db)
    app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None, portal_service_key=key)
    app.dependency_overrides[get_db] = lambda: repo


def _headers(acting="admin1"):
    return {"X-Service-Key": VALID_KEY, "X-Acting-Platni-Broj": acting}


def _authed(monkeypatch, role="ADMIN"):
    _use_portal(monkeypatch, FakePortalRepo([_actor()], {1: [role]}))


class FakeAuditRepo:
    def __init__(self):
        self.entries = []

    def add(self, **kwargs):
        self.entries.append(kwargs)


class Harness:
    """Drzi zajednicko stanje (repo/db/audit) izmedju vise poziva u jednom testu."""

    def __init__(self):
        self.survey_repo = FakeSurveyRepo()
        self.automation_repo = OnboardingAutomationRepository.__new__(OnboardingAutomationRepository)
        # Koristimo pravi repo ali sa in-memory SQLite sesijom bi bilo tesko bez prave baze;
        # umesto toga koristimo lagani in-memory fake repo iste povrsine.
        self.rules: dict[int, object] = {}
        self._id = 0
        self.db = FakeDb()
        self.audit_repo = FakeAuditRepo()

    def service(self) -> OnboardingAutomationAdminService:
        return OnboardingAutomationAdminService(
            self.db,
            repository=_FakeAutomationRepo(self),
            survey_repository=self.survey_repo,
            audit_service=AuditService(self.audit_repo, izvor="TEST"),
        )


class _FakeAutomationRepo:
    def __init__(self, harness: Harness):
        self.h = harness

    def list_all(self):
        return list(self.h.rules.values())

    def get(self, automatika_id):
        return self.h.rules.get(automatika_id)

    def get_by_survey_id(self, anketa_id):
        return next((p for p in self.h.rules.values() if p.anketa_id == anketa_id), None)

    def get_for_update(self, automatika_id):
        return self.h.rules.get(automatika_id)

    def find_active_rules(self):
        return [p for p in self.h.rules.values() if p.aktivna == "D"]

    def add(self, automatika):
        self.h._id += 1
        automatika.id = self.h._id
        self.h.rules[automatika.id] = automatika
        return automatika


def _use_service(service):
    app.dependency_overrides[automations_mod.get_onboarding_automation_admin_service] = lambda: service


def _payload(**ov):
    body = {
        "dani_od_zaposlenja": 7,
        "rok_dana": 7,
        "datum_primene_od": "2025-01-01",
        "aktivna": True,
    }
    body.update(ov)
    return body


# ================================================================= OBO auth
def test_list_no_service_key_401(client, monkeypatch):
    _authed(monkeypatch)
    resp = client.get("/api/v1/admin/survey-automations")
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "INVALID_SERVICE_CREDENTIALS"


def test_put_zaposleni_role_403(client, monkeypatch):
    _authed(monkeypatch, role="ZAPOSLENI")
    h = Harness()
    anketa = make_anketa(h.survey_repo)
    _use_service(h.service())
    resp = client.put(f"/api/v1/admin/survey-automations/{anketa.id}", headers=_headers(), json=_payload())
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "FORBIDDEN"


def test_hr_role_allowed(client, monkeypatch):
    _authed(monkeypatch, role="HR")
    h = Harness()
    anketa = make_anketa(h.survey_repo)
    _use_service(h.service())
    resp = client.put(f"/api/v1/admin/survey-automations/{anketa.id}", headers=_headers(), json=_payload())
    assert resp.status_code == 200


# ================================================================= poslovna pravila
def test_put_nonexistent_survey_404(client, monkeypatch):
    _authed(monkeypatch)
    h = Harness()
    _use_service(h.service())
    resp = client.put("/api/v1/admin/survey-automations/999999", headers=_headers(), json=_payload())
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "SURVEY_NOT_FOUND"


def test_put_anonymous_survey_422(client, monkeypatch):
    _authed(monkeypatch)
    h = Harness()
    anketa = make_anketa(h.survey_repo, anonimna="D")
    _use_service(h.service())
    resp = client.put(f"/api/v1/admin/survey-automations/{anketa.id}", headers=_headers(), json=_payload())
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "SURVEY_AUTOMATION_NOT_ALLOWED_FOR_ANONYMOUS"


def test_put_bad_milestone_422(client, monkeypatch):
    _authed(monkeypatch)
    h = Harness()
    anketa = make_anketa(h.survey_repo)
    _use_service(h.service())
    resp = client.put(
        f"/api/v1/admin/survey-automations/{anketa.id}",
        headers=_headers(),
        json=_payload(dani_od_zaposlenja=15),
    )
    assert resp.status_code == 422


def test_put_rok_out_of_range_422(client, monkeypatch):
    _authed(monkeypatch)
    h = Harness()
    anketa = make_anketa(h.survey_repo)
    _use_service(h.service())
    resp = client.put(
        f"/api/v1/admin/survey-automations/{anketa.id}", headers=_headers(), json=_payload(rok_dana=0)
    )
    assert resp.status_code == 422


def test_put_extra_field_422(client, monkeypatch):
    _authed(monkeypatch)
    h = Harness()
    anketa = make_anketa(h.survey_repo)
    _use_service(h.service())
    resp = client.put(
        f"/api/v1/admin/survey-automations/{anketa.id}", headers=_headers(), json=_payload(nepoznato="x")
    )
    assert resp.status_code == 422


def test_put_happy_path_200(client, monkeypatch):
    _authed(monkeypatch)
    h = Harness()
    anketa = make_anketa(h.survey_repo)
    _use_service(h.service())
    resp = client.put(f"/api/v1/admin/survey-automations/{anketa.id}", headers=_headers(), json=_payload())
    assert resp.status_code == 200
    body = resp.json()
    assert body["anketa_id"] == anketa.id
    assert body["dani_od_zaposlenja"] == 7
    assert body["aktivna"] is True


def test_put_duplicate_active_milestone_409(client, monkeypatch):
    _authed(monkeypatch)
    h = Harness()
    anketa1 = make_anketa(h.survey_repo)
    anketa2 = make_anketa(h.survey_repo)
    _use_service(h.service())
    resp1 = client.put(
        f"/api/v1/admin/survey-automations/{anketa1.id}", headers=_headers(), json=_payload()
    )
    assert resp1.status_code == 200
    resp2 = client.put(
        f"/api/v1/admin/survey-automations/{anketa2.id}", headers=_headers(), json=_payload()
    )
    assert resp2.status_code == 409
    assert resp2.json()["error"]["code"] == "SURVEY_AUTOMATION_CONFLICT"


def test_put_concurrent_ux_anketa_automatika_anketa_conflict_maps_to_409():
    """Konkurentni INSERT je pogodio UX_ANKETA_AUTOMATIKA_ANKETA (druga anketa vec
    ima red) iako je pre-provera prosla - mora se mapirati na 409, ne 500."""
    h = Harness()
    anketa = make_anketa(h.survey_repo)
    service = h.service()

    def _boom(_automatika):
        raise IntegrityError("stmt", {}, Exception("ORA-00001: UX_ANKETA_AUTOMATIKA_ANKETA violated"))

    service.repo.add = _boom
    with pytest.raises(SurveyAutomationConflictError):
        service.upsert(_actor(), anketa.id, _make_payload_obj())


def test_put_concurrent_ux_anketa_automatika_aktivna_milestone_conflict_maps_to_409():
    """Konkurentni UPDATE je pogodio UX_ANKETA_AUTOMATIKA_AKTIVNA_MILESTONE (drugo
    pravilo vec aktivno na istom milestone-u) - mora se mapirati na 409."""
    h = Harness()
    anketa = make_anketa(h.survey_repo)
    service = h.service()

    def _boom(_automatika):
        raise IntegrityError(
            "stmt", {}, Exception("ORA-00001: UX_ANKETA_AUTOMATIKA_AKTIVNA_MILESTONE violated")
        )

    service.repo.add = _boom
    with pytest.raises(SurveyAutomationConflictError):
        service.upsert(_actor(), anketa.id, _make_payload_obj())


def test_put_unrelated_integrity_error_propagates():
    """Nepovezana IntegrityError (npr. FK ka nepostojecoj anketi) NIKAD ne sme biti
    tiho progutana/mapirana na SurveyAutomationConflictError - mora se propagirati."""
    h = Harness()
    anketa = make_anketa(h.survey_repo)
    service = h.service()

    def _boom(_automatika):
        raise IntegrityError("stmt", {}, Exception("ORA-02291: FK_NEKI_DRUGI_CONSTRAINT violated"))

    service.repo.add = _boom
    with pytest.raises(IntegrityError):
        service.upsert(_actor(), anketa.id, _make_payload_obj())


def _make_payload_obj():
    import datetime as _dt
    from types import SimpleNamespace

    return SimpleNamespace(
        dani_od_zaposlenja=7, rok_dana=7, datum_primene_od=_dt.date(2025, 1, 1), aktivna=True
    )


def test_get_list_returns_items(client, monkeypatch):
    _authed(monkeypatch)
    h = Harness()
    anketa = make_anketa(h.survey_repo)
    _use_service(h.service())
    client.put(f"/api/v1/admin/survey-automations/{anketa.id}", headers=_headers(), json=_payload())
    resp = client.get("/api/v1/admin/survey-automations", headers=_headers())
    assert resp.status_code == 200
    assert len(resp.json()["items"]) == 1


def test_put_idempotent_no_extra_audit(client, monkeypatch):
    _authed(monkeypatch)
    h = Harness()
    anketa = make_anketa(h.survey_repo)
    _use_service(h.service())
    resp1 = client.put(f"/api/v1/admin/survey-automations/{anketa.id}", headers=_headers(), json=_payload())
    assert resp1.status_code == 200
    count_after_first = len(h.audit_repo.entries)
    assert count_after_first == 1
    resp2 = client.put(f"/api/v1/admin/survey-automations/{anketa.id}", headers=_headers(), json=_payload())
    assert resp2.status_code == 200
    assert len(h.audit_repo.entries) == count_after_first
    assert resp1.json()["datum_izmene"] == resp2.json()["datum_izmene"]


def test_put_actual_change_writes_audit(client, monkeypatch):
    _authed(monkeypatch)
    h = Harness()
    anketa = make_anketa(h.survey_repo)
    _use_service(h.service())
    client.put(f"/api/v1/admin/survey-automations/{anketa.id}", headers=_headers(), json=_payload())
    assert len(h.audit_repo.entries) == 1
    resp = client.put(
        f"/api/v1/admin/survey-automations/{anketa.id}", headers=_headers(), json=_payload(rok_dana=10)
    )
    assert resp.status_code == 200
    assert resp.json()["rok_dana"] == 10
    assert len(h.audit_repo.entries) == 2
