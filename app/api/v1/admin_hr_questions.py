from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.dependencies.portal_auth import require_portal_admin_or_hr
from app.models.hr_pitanje import STATUSI
from app.models.korisnik import Korisnik
from app.schemas.common import ErrorResponse
from app.schemas.hr_question import (
    AdminHrAnswerRequest,
    AdminHrCategoryCreateRequest,
    AdminHrCategoryListResponse,
    AdminHrCategoryOut,
    AdminHrCategoryUpdateRequest,
    AdminHrFaqCreateRequest,
    AdminHrFaqListResponse,
    AdminHrFaqOut,
    AdminHrFaqUpdateRequest,
    AdminHrQuestionListResponse,
    AdminHrQuestionOut,
)
from app.services.hr_question_admin_service import HrQuestionAdminService

router = APIRouter(prefix="/admin/hr-questions", tags=["Admin Pitaj HR"])
categories_router = APIRouter(prefix="/admin/hr-categories", tags=["Admin Pitaj HR"])
faq_router = APIRouter(prefix="/admin/hr-faq", tags=["Admin Pitaj HR"])

R_404 = {404: {"model": ErrorResponse, "description": "`HR_QUESTION_NOT_FOUND`."}}
R_CAT_404 = {404: {"model": ErrorResponse, "description": "`HR_CATEGORY_NOT_FOUND`."}}
R_FAQ_404 = {404: {"model": ErrorResponse, "description": "`HR_FAQ_NOT_FOUND`."}}
R_422 = {422: {"model": ErrorResponse, "description": "`VALIDATION_ERROR` ili `HR_QUESTION_CATEGORY_INVALID`."}}
PAGE_SIZE_DEFAULT = 20
PAGE_SIZE_MAX = 100


def get_hr_question_admin_service(db: Session = Depends(get_db)) -> HrQuestionAdminService:
    return HrQuestionAdminService(db)


# ================================================================ kategorije
@categories_router.get("", response_model=AdminHrCategoryListResponse, summary="Šifarnik kategorija pitanja")
def list_categories(
    aktivna: bool | None = Query(default=None),
    actor: Korisnik = Depends(require_portal_admin_or_hr),
    service: HrQuestionAdminService = Depends(get_hr_question_admin_service),
) -> AdminHrCategoryListResponse:
    return AdminHrCategoryListResponse(items=[AdminHrCategoryOut(**k) for k in service.list_categories(aktivna)])


@categories_router.post(
    "",
    response_model=AdminHrCategoryOut,
    status_code=status.HTTP_201_CREATED,
    summary="Nova kategorija",
    description="`sifra` se pretvara u velika slova (A-Z, 0-9, _). Brisanja nema - isključuje se sa `aktivna=false`.",
    responses={409: {"model": ErrorResponse, "description": "`HR_CATEGORY_ALREADY_EXISTS`."}, **R_422},
)
def create_category(
    payload: AdminHrCategoryCreateRequest,
    actor: Korisnik = Depends(require_portal_admin_or_hr),
    service: HrQuestionAdminService = Depends(get_hr_question_admin_service),
) -> AdminHrCategoryOut:
    return AdminHrCategoryOut(
        **service.create_category(actor, payload.sifra, payload.naziv, payload.redosled, payload.aktivna)
    )


@categories_router.put(
    "/{sifra}",
    response_model=AdminHrCategoryOut,
    summary="Izmena kategorije",
    description="Menja naziv, redosled i aktivnost. Šifra se ne menja.",
    responses={**R_CAT_404, **R_422},
)
def update_category(
    sifra: str,
    payload: AdminHrCategoryUpdateRequest,
    actor: Korisnik = Depends(require_portal_admin_or_hr),
    service: HrQuestionAdminService = Depends(get_hr_question_admin_service),
) -> AdminHrCategoryOut:
    return AdminHrCategoryOut(
        **service.update_category(actor, sifra, payload.naziv, payload.redosled, payload.aktivna)
    )


# =================================================================== pitanja
@router.get(
    "",
    response_model=AdminHrQuestionListResponse,
    summary="Lista pitanja",
    description="`status=POSLATO` = čeka odgovor (najduže čeka prvo); ostalo najnovija izmena prva. "
    "Filteri `status` i `kategorija` su opcioni.",
    responses={422: {"model": ErrorResponse, "description": "`INVALID_HR_QUESTION_STATUS`."}},
)
def list_questions(
    status_filter: str | None = Query(default=None, alias="status", json_schema_extra={"enum": list(STATUSI)}),
    kategorija: str | None = Query(default=None, max_length=30),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=PAGE_SIZE_DEFAULT, ge=1, le=PAGE_SIZE_MAX),
    actor: Korisnik = Depends(require_portal_admin_or_hr),
    service: HrQuestionAdminService = Depends(get_hr_question_admin_service),
) -> AdminHrQuestionListResponse:
    r = service.list_questions(status_filter, kategorija, page, page_size)
    return AdminHrQuestionListResponse(
        items=[AdminHrQuestionOut(**i) for i in r["items"]], total=r["total"], page=r["page"], page_size=r["page_size"]
    )


@router.get("/{pitanje_id}", response_model=AdminHrQuestionOut, summary="Pitanje sa prepiskom", responses={**R_404})
def get_question(
    pitanje_id: int,
    actor: Korisnik = Depends(require_portal_admin_or_hr),
    service: HrQuestionAdminService = Depends(get_hr_question_admin_service),
) -> AdminHrQuestionOut:
    return AdminHrQuestionOut(**service.get_question(pitanje_id))


@router.post(
    "/{pitanje_id}/answer",
    response_model=AdminHrQuestionOut,
    summary="Odgovor na pitanje",
    description="Samo za `POSLATO`. Zaposleni dobija obaveštenje i push (bez teksta odgovora). "
    "Odgovor na dopunsko pitanje zatvara pitanje.",
    responses={
        **R_404,
        409: {"model": ErrorResponse, "description": "`HR_QUESTION_ANSWER_NOT_ALLOWED`."},
        **R_422,
    },
)
def answer(
    pitanje_id: int,
    payload: AdminHrAnswerRequest,
    actor: Korisnik = Depends(require_portal_admin_or_hr),
    service: HrQuestionAdminService = Depends(get_hr_question_admin_service),
) -> AdminHrQuestionOut:
    return AdminHrQuestionOut(**service.answer(actor, pitanje_id, payload.tekst))


@router.post(
    "/{pitanje_id}/close",
    response_model=AdminHrQuestionOut,
    summary="Zatvori pitanje",
    description="Bez obaveštenja zaposlenom; posle zatvaranja nema novih poruka.",
    responses={**R_404},
)
def close(
    pitanje_id: int,
    actor: Korisnik = Depends(require_portal_admin_or_hr),
    service: HrQuestionAdminService = Depends(get_hr_question_admin_service),
) -> AdminHrQuestionOut:
    return AdminHrQuestionOut(**service.close(actor, pitanje_id))


# ============================================================= cesta pitanja
@faq_router.get("", response_model=AdminHrFaqListResponse, summary="Česta pitanja")
def list_faq(
    aktivno: bool | None = Query(default=None),
    kategorija: str | None = Query(default=None, max_length=30),
    actor: Korisnik = Depends(require_portal_admin_or_hr),
    service: HrQuestionAdminService = Depends(get_hr_question_admin_service),
) -> AdminHrFaqListResponse:
    return AdminHrFaqListResponse(items=[AdminHrFaqOut(**f) for f in service.list_faq(aktivno, kategorija)])


@faq_router.post(
    "",
    response_model=AdminHrFaqOut,
    status_code=status.HTTP_201_CREATED,
    summary="Objavi često pitanje",
    description="HR piše tekst bez imena i ličnih podataka. `izvor_pitanje_id` je opcion i aplikacija ga ne vidi.",
    responses={**R_404, **R_422},
)
def create_faq(
    payload: AdminHrFaqCreateRequest,
    actor: Korisnik = Depends(require_portal_admin_or_hr),
    service: HrQuestionAdminService = Depends(get_hr_question_admin_service),
) -> AdminHrFaqOut:
    return AdminHrFaqOut(
        **service.create_faq(actor, payload.kategorija_sifra, payload.pitanje, payload.odgovor, payload.redosled,
                             payload.aktivno, payload.izvor_pitanje_id)
    )


@faq_router.put(
    "/{faq_id}",
    response_model=AdminHrFaqOut,
    summary="Izmena čestog pitanja",
    description="`aktivno=false` ga sklanja iz aplikacije.",
    responses={**R_FAQ_404, **R_422},
)
def update_faq(
    faq_id: int,
    payload: AdminHrFaqUpdateRequest,
    actor: Korisnik = Depends(require_portal_admin_or_hr),
    service: HrQuestionAdminService = Depends(get_hr_question_admin_service),
) -> AdminHrFaqOut:
    return AdminHrFaqOut(
        **service.update_faq(actor, faq_id, payload.kategorija_sifra, payload.pitanje, payload.odgovor,
                             payload.redosled, payload.aktivno)
    )
