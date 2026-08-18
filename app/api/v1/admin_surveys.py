import datetime

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.core.exceptions import ValidationBusinessError
from app.db.session import get_db
from app.dependencies.portal_auth import require_portal_admin_or_hr
from app.models.korisnik import Korisnik
from app.schemas.survey import (
    AdminCiljOut,
    AdminOpcijaOut,
    AdminPitanjeOut,
    AdminSekcijaOut,
    AdminSurveyCreatedResponse,
    AdminSurveyCreateRequest,
    AdminSurveyDetailResponse,
    AdminSurveyExtendRequest,
    AdminSurveyListItem,
    AdminSurveyListResponse,
    AdminSurveyStatusRequest,
    AdminSurveyUpdateRequest,
    AdminUslovOut,
    SurveyTypeCreateRequest,
    SurveyTypeListResponse,
    SurveyTypePatchRequest,
    SurveyTypeResponse,
)
from app.services.survey_admin_service import SurveyAdminService

router = APIRouter(prefix="/admin", tags=["Admin Surveys"])

PAGE_SIZE_DEFAULT = 50
PAGE_SIZE_MAX = 100


def get_survey_admin_service(db: Session = Depends(get_db)) -> SurveyAdminService:
    return SurveyAdminService(db)


def _type_out(tip) -> SurveyTypeResponse:
    return SurveyTypeResponse(sifra=tip.sifra, naziv=tip.naziv, aktivan=tip.aktivan == "D")


# ------------------------------------------------------------------ survey types
@router.get("/survey-types", response_model=SurveyTypeListResponse)
def list_survey_types(
    _: Korisnik = Depends(require_portal_admin_or_hr),
    service: SurveyAdminService = Depends(get_survey_admin_service),
) -> SurveyTypeListResponse:
    return SurveyTypeListResponse(items=[_type_out(t) for t in service.list_types()])


@router.post("/survey-types", response_model=SurveyTypeResponse, status_code=status.HTTP_201_CREATED)
def create_survey_type(
    payload: SurveyTypeCreateRequest,
    actor: Korisnik = Depends(require_portal_admin_or_hr),
    service: SurveyAdminService = Depends(get_survey_admin_service),
) -> SurveyTypeResponse:
    return _type_out(service.create_type(actor, payload.sifra, payload.naziv))


@router.patch("/survey-types/{type_code}", response_model=SurveyTypeResponse)
def patch_survey_type(
    type_code: str,
    payload: SurveyTypePatchRequest,
    actor: Korisnik = Depends(require_portal_admin_or_hr),
    service: SurveyAdminService = Depends(get_survey_admin_service),
) -> SurveyTypeResponse:
    return _type_out(service.update_type(actor, type_code, payload.naziv, payload.aktivan))


# ------------------------------------------------------------------ surveys
@router.post("/surveys", response_model=AdminSurveyCreatedResponse, status_code=status.HTTP_201_CREATED)
def create_survey(
    payload: AdminSurveyCreateRequest,
    actor: Korisnik = Depends(require_portal_admin_or_hr),
    service: SurveyAdminService = Depends(get_survey_admin_service),
) -> AdminSurveyCreatedResponse:
    anketa = service.create_survey(actor, payload)
    return AdminSurveyCreatedResponse(id=anketa.id, status=anketa.status)


@router.get("/surveys", response_model=AdminSurveyListResponse)
def list_surveys(
    status_filter: str | None = Query(default=None, alias="status"),
    tip: str | None = Query(default=None),
    datum_od: datetime.datetime | None = Query(default=None),
    datum_do: datetime.datetime | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=PAGE_SIZE_DEFAULT, ge=1, le=PAGE_SIZE_MAX),
    _: Korisnik = Depends(require_portal_admin_or_hr),
    service: SurveyAdminService = Depends(get_survey_admin_service),
) -> AdminSurveyListResponse:
    # Isti timezone ugovor kao za admin datume + logicki redosled filtera.
    # Query parametri ne prolaze kroz pydantic validator, pa timezone proveravamo ovde
    # i vracamo standardni VALIDATION_ERROR (ne 500).
    if (datum_od is not None and datum_od.tzinfo is not None) or (
        datum_do is not None and datum_do.tzinfo is not None
    ):
        raise ValidationBusinessError("Datum filtera mora biti bez vremenske zone (bez Z ili offseta).")
    if datum_od is not None and datum_do is not None and datum_do < datum_od:
        raise ValidationBusinessError("datum_do ne sme biti pre datum_od.")
    enriched, total = service.list_surveys(status_filter, tip, datum_od, datum_do, page, page_size)
    return AdminSurveyListResponse(
        items=[
            AdminSurveyListItem(
                id=a.id,
                naziv=a.naziv,
                tip=a.tip_sifra,
                status=a.status,
                anonimna=a.is_anonimna,
                datum_pocetka=a.datum_pocetka,
                datum_zavrsetka=a.datum_zavrsetka,
                broj_ciljanih=ciljanih,
                broj_predatih=predatih,
                procenat_odziva=procenat,
            )
            for (a, ciljanih, predatih, procenat) in enriched
        ],
        total=total,
        page=page,
        page_size=page_size,
    )


def _build_admin_detail(service: SurveyAdminService, anketa) -> AdminSurveyDetailResponse:
    repo = service.repo
    sections = repo.get_sections(anketa.id)
    questions = repo.get_questions_for_survey(anketa.id)
    options = repo.get_options_for_survey(anketa.id)
    uslov_values = repo.get_uslov_values_for_survey(anketa.id)
    targets = repo.get_targets(anketa.id)

    opts_by_q: dict[int, list] = {}
    for o in options:
        opts_by_q.setdefault(o.pitanje_id, []).append(o)
    uslov_by_q: dict[int, list[str]] = {}
    for uv in uslov_values:
        uslov_by_q.setdefault(uv.pitanje_id, []).append(uv.vrednost)
    q_by_section: dict[int, list] = {}
    for q in questions:
        q_by_section.setdefault(q.sekcija_id, []).append(q)

    sekcije_out = []
    for s in sections:
        pitanja = []
        for q in q_by_section.get(s.id, []):
            uslov = None
            if q.uslov_pitanje_id is not None:
                uslov = AdminUslovOut(
                    pitanje_id=q.uslov_pitanje_id,
                    operator=q.uslov_operator,
                    vrednosti=uslov_by_q.get(q.id, []),
                )
            pitanja.append(
                AdminPitanjeOut(
                    id=q.id,
                    tekst=q.tekst,
                    tip=q.tip_pitanja,
                    obavezno=q.obavezno_bool,
                    redosled=int(q.redosled),
                    opcije=[
                        AdminOpcijaOut(id=o.id, tekst=o.tekst, redosled=int(o.redosled))
                        for o in opts_by_q.get(q.id, [])
                    ],
                    uslov=uslov,
                )
            )
        sekcije_out.append(
            AdminSekcijaOut(id=s.id, naziv=s.naziv, redosled=int(s.redosled), pitanja=pitanja)
        )

    return AdminSurveyDetailResponse(
        id=anketa.id,
        naziv=anketa.naziv,
        opis=anketa.opis,
        tip=anketa.tip_sifra,
        anonimna=anketa.is_anonimna,
        status=anketa.status,
        datum_pocetka=anketa.datum_pocetka,
        datum_zavrsetka=anketa.datum_zavrsetka,
        sekcije=sekcije_out,
        ciljevi=[
            AdminCiljOut(id=c.id, tip_cilja=c.tip_cilja, vrednost=c.vrednost) for c in targets
        ],
    )


@router.get("/surveys/{survey_id}", response_model=AdminSurveyDetailResponse)
def get_survey(
    survey_id: int,
    _: Korisnik = Depends(require_portal_admin_or_hr),
    service: SurveyAdminService = Depends(get_survey_admin_service),
) -> AdminSurveyDetailResponse:
    anketa = service.get_survey(survey_id)
    return _build_admin_detail(service, anketa)


@router.put("/surveys/{survey_id}", response_model=AdminSurveyDetailResponse)
def update_survey(
    survey_id: int,
    payload: AdminSurveyUpdateRequest,
    actor: Korisnik = Depends(require_portal_admin_or_hr),
    service: SurveyAdminService = Depends(get_survey_admin_service),
) -> AdminSurveyDetailResponse:
    anketa = service.update_survey(actor, survey_id, payload)
    return _build_admin_detail(service, anketa)


@router.patch("/surveys/{survey_id}/status", response_model=AdminSurveyDetailResponse)
def change_survey_status(
    survey_id: int,
    payload: AdminSurveyStatusRequest,
    actor: Korisnik = Depends(require_portal_admin_or_hr),
    service: SurveyAdminService = Depends(get_survey_admin_service),
) -> AdminSurveyDetailResponse:
    anketa = service.change_status(actor, survey_id, payload.status)
    return _build_admin_detail(service, anketa)


@router.patch("/surveys/{survey_id}", response_model=AdminSurveyDetailResponse)
def extend_survey_deadline(
    survey_id: int,
    payload: AdminSurveyExtendRequest,
    actor: Korisnik = Depends(require_portal_admin_or_hr),
    service: SurveyAdminService = Depends(get_survey_admin_service),
) -> AdminSurveyDetailResponse:
    anketa = service.extend_deadline(actor, survey_id, payload.datum_zavrsetka)
    return _build_admin_detail(service, anketa)