import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.exceptions import ValidationBusinessError
from app.db.session import get_db
from app.dependencies.portal_auth import require_portal_admin_or_hr
from app.models.korisnik import Korisnik
from app.schemas.survey_results import SurveyResponsesResponse, SurveyStatisticsResponse
from app.services.survey_results_service import SurveyResultsService

router = APIRouter(prefix="/admin/surveys", tags=["Admin Survey Results"])

PAGE_SIZE_DEFAULT = 20
PAGE_SIZE_MAX = 100
PLATNI_BROJ_MAX = 30
ORGJED_MAX = 50
RADNO_MESTO_MAX = 50


def get_survey_results_service(db: Session = Depends(get_db)) -> SurveyResultsService:
    return SurveyResultsService(db)


def _normalize_filter(value: str | None, max_len: int, label: str) -> str | None:
    """Trim; prazno posle trimovanja ili predugacko -> 422 (ne 500)."""
    if value is None:
        return None
    v = value.strip()
    if not v:
        raise ValidationBusinessError(f"{label} ne sme biti prazan.")
    if len(v) > max_len:
        raise ValidationBusinessError(f"{label} je predugačak.")
    return v


def _validate_naive_range(
    datum_od: datetime.datetime | None, datum_do: datetime.datetime | None
) -> None:
    # Isti naive-datetime ugovor kao postojeci Survey admin API (list_surveys).
    if (datum_od is not None and datum_od.tzinfo is not None) or (
        datum_do is not None and datum_do.tzinfo is not None
    ):
        raise ValidationBusinessError("Datum filtera mora biti bez vremenske zone (bez Z ili offseta).")
    if datum_od is not None and datum_do is not None and datum_do < datum_od:
        raise ValidationBusinessError("datum_do ne sme biti pre datum_od.")


@router.get(
    "/{survey_id}/statistics",
    response_model=SurveyStatisticsResponse,
    response_model_exclude_none=True,
)
def get_survey_statistics(
    survey_id: int,
    _: Korisnik = Depends(require_portal_admin_or_hr),
    service: SurveyResultsService = Depends(get_survey_results_service),
) -> SurveyStatisticsResponse:
    return SurveyStatisticsResponse(**service.get_statistics(survey_id))


@router.get("/{survey_id}/responses", response_model=SurveyResponsesResponse)
def get_survey_responses(
    survey_id: int,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=PAGE_SIZE_DEFAULT, ge=1, le=PAGE_SIZE_MAX),
    platni_broj: str | None = Query(default=None),
    orgjed_sifra: str | None = Query(default=None),
    radno_mesto_sifra: str | None = Query(default=None),
    datum_od: datetime.datetime | None = Query(default=None),
    datum_do: datetime.datetime | None = Query(default=None),
    _: Korisnik = Depends(require_portal_admin_or_hr),
    service: SurveyResultsService = Depends(get_survey_results_service),
) -> SurveyResponsesResponse:
    _validate_naive_range(datum_od, datum_do)
    platni_broj = _normalize_filter(platni_broj, PLATNI_BROJ_MAX, "platni_broj")
    orgjed_sifra = _normalize_filter(orgjed_sifra, ORGJED_MAX, "orgjed_sifra")
    radno_mesto_sifra = _normalize_filter(radno_mesto_sifra, RADNO_MESTO_MAX, "radno_mesto_sifra")
    return SurveyResponsesResponse(
        **service.get_responses(
            survey_id, page, page_size, platni_broj, orgjed_sifra, radno_mesto_sifra, datum_od, datum_do
        )
    )
