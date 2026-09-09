from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.dependencies.portal_auth import require_portal_admin_or_hr
from app.models.korisnik import Korisnik
from app.schemas.survey_automation import (
    SurveyAutomationIn,
    SurveyAutomationListResponse,
    SurveyAutomationOut,
)
from app.services.onboarding_automation_admin_service import OnboardingAutomationAdminService

router = APIRouter(prefix="/admin/survey-automations", tags=["Admin Survey Automations"])


def get_onboarding_automation_admin_service(
    db: Session = Depends(get_db),
) -> OnboardingAutomationAdminService:
    return OnboardingAutomationAdminService(db)


def _out(pravilo) -> SurveyAutomationOut:
    return SurveyAutomationOut(
        id=pravilo.id,
        anketa_id=pravilo.anketa_id,
        dani_od_zaposlenja=pravilo.dani_od_zaposlenja,
        rok_dana=pravilo.rok_dana,
        datum_primene_od=pravilo.datum_primene_od,
        aktivna=pravilo.aktivna == "D",
        datum_kreiranja=pravilo.datum_kreiranja,
        datum_izmene=pravilo.datum_izmene,
    )


@router.get("", response_model=SurveyAutomationListResponse)
def list_survey_automations(
    _: Korisnik = Depends(require_portal_admin_or_hr),
    service: OnboardingAutomationAdminService = Depends(get_onboarding_automation_admin_service),
) -> SurveyAutomationListResponse:
    return SurveyAutomationListResponse(items=[_out(p) for p in service.list_automations()])


@router.put("/{survey_id}", response_model=SurveyAutomationOut)
def upsert_survey_automation(
    survey_id: int,
    payload: SurveyAutomationIn,
    actor: Korisnik = Depends(require_portal_admin_or_hr),
    service: OnboardingAutomationAdminService = Depends(get_onboarding_automation_admin_service),
) -> SurveyAutomationOut:
    pravilo = service.upsert(actor, survey_id, payload)
    return _out(pravilo)
