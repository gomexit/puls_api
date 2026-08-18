"""Audit mora zabeležiti stvarnog acting korisnika (iz X-Acting-Platni-Broj) kao
korisnik_id + platni_broj — i za postojeće mutacije i za novo pokrivene tipove anketa."""

import datetime

from app.services.audit_service import AuditAction
from app.services.idea_admin_service import IdeaAdminService
from app.services.survey_admin_service import SurveyAdminService
from tests.fakes import (
    FakeAuditService,
    FakeDb,
    FakeIdeaCycleRepository,
    FakeIdeaRepository,
    make_ideja,
    make_korisnik,
)
from tests.survey_fakes import FakeSurveyDb, FakeSurveyRepo, FakeTargetingRepo, make_tip


def _actor():
    return make_korisnik(id=42, platni_broj="admin42")


def _find(audit: FakeAuditService, sifra: str) -> dict:
    return next(e for e in audit.entries if e["sifra_akcije"] == sifra)


# ------------------------------------------------------------------ ANKETE tipovi (tačka 19)
def _survey_service():
    audit = FakeAuditService()
    service = SurveyAdminService(
        db=FakeSurveyDb(), repository=FakeSurveyRepo(), targeting_repository=FakeTargetingRepo(),
        audit_service=audit,
    )
    return service, audit


def test_create_type_audits_acting_user():
    service, audit = _survey_service()
    service.create_type(_actor(), "NPS", "NPS anketa")
    e = _find(audit, AuditAction.SURVEY_TYPE_CREATED)
    assert e["korisnik_id"] == 42
    assert e["platni_broj"] == "admin42"
    assert e["entitet_id"] == "NPS"


def test_update_type_audits_acting_user():
    service, audit = _survey_service()
    service.repo.add_type(make_tip(sifra="NPS", naziv="Staro"))
    service.update_type(_actor(), "NPS", "Novo", True)
    e = _find(audit, AuditAction.SURVEY_TYPE_UPDATED)
    assert e["korisnik_id"] == 42
    assert e["platni_broj"] == "admin42"


# ------------------------------------------------------------------ IDEJE mutacije (tačka 18)
def test_idea_cycle_create_audits_acting_user():
    audit = FakeAuditService()
    service = IdeaAdminService(
        db=FakeDb(), idea_repository=FakeIdeaRepository(),
        cycle_repository=FakeIdeaCycleRepository(), audit_service=audit,
    )
    now = datetime.datetime.now()
    service.create_cycle(_actor(), "Ciklus", now, now + datetime.timedelta(days=5))
    e = _find(audit, AuditAction.IDEA_CYCLE_CREATED)
    assert e["korisnik_id"] == 42
    assert e["platni_broj"] == "admin42"


def test_idea_hr_score_audits_acting_user():
    audit = FakeAuditService()
    ideja = make_ideja(id=7)
    service = IdeaAdminService(
        db=FakeDb(), idea_repository=FakeIdeaRepository([ideja]),
        cycle_repository=FakeIdeaCycleRepository(), audit_service=audit,
    )
    service.set_hr_score(_actor(), 7, 8)
    e = _find(audit, AuditAction.IDEA_HR_SCORE_SET)
    assert e["korisnik_id"] == 42
    assert e["platni_broj"] == "admin42"
