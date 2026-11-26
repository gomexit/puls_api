from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.dependencies.auth import get_current_ready_user
from app.models.korisnik import Korisnik
from app.schemas.common import ErrorResponse
from app.schemas.hr_question import (
    HrCategoryListResponse,
    HrCategoryOut,
    HrFaqListResponse,
    HrFaqOut,
    HrFollowUpRequest,
    HrQuestionCreateRequest,
    HrQuestionListResponse,
    HrQuestionOut,
    HrQuestionSummaryOut,
)
from app.services.hr_question_service import HrQuestionService

router = APIRouter(prefix="/hr-questions", tags=["Pitaj HR"])

R_404 = {404: {"model": ErrorResponse, "description": "`HR_QUESTION_NOT_AVAILABLE` - modul nije uključen za mene."}}
R_Q404 = {
    404: {"model": ErrorResponse, "description": "`HR_QUESTION_NOT_AVAILABLE` ili `HR_QUESTION_NOT_FOUND`."}
}
PAGE_SIZE_DEFAULT = 20
PAGE_SIZE_MAX = 50


def get_hr_question_service(db: Session = Depends(get_db)) -> HrQuestionService:
    return HrQuestionService(db)


@router.get("/categories", response_model=HrCategoryListResponse, summary="Kategorije pitanja", responses={**R_404})
def categories(
    korisnik: Korisnik = Depends(get_current_ready_user),
    service: HrQuestionService = Depends(get_hr_question_service),
) -> HrCategoryListResponse:
    return HrCategoryListResponse(items=[HrCategoryOut(**k) for k in service.categories(korisnik)])


@router.get(
    "/faq",
    response_model=HrFaqListResponse,
    summary="Česta pitanja",
    description="Odgovori koje je HR objavio svima, bez imena onoga ko je pitao. Filter `kategorija` je opcion.",
    responses={**R_404},
)
def faq(
    kategorija: str | None = Query(default=None, max_length=30),
    korisnik: Korisnik = Depends(get_current_ready_user),
    service: HrQuestionService = Depends(get_hr_question_service),
) -> HrFaqListResponse:
    return HrFaqListResponse(items=[HrFaqOut(**f) for f in service.faq(korisnik, kategorija)])


@router.get(
    "",
    response_model=HrQuestionListResponse,
    summary="Moja pitanja",
    description="Moja pitanja, poslednja izmena prva. `nov_odgovor=true` dok ne otvorim pitanje.",
    responses={**R_404},
)
def mine(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=PAGE_SIZE_DEFAULT, ge=1, le=PAGE_SIZE_MAX),
    korisnik: Korisnik = Depends(get_current_ready_user),
    service: HrQuestionService = Depends(get_hr_question_service),
) -> HrQuestionListResponse:
    r = service.mine(korisnik, page, page_size)
    return HrQuestionListResponse(items=[HrQuestionSummaryOut(**i) for i in r["items"]], ima_jos=r["ima_jos"])


@router.post(
    "",
    response_model=HrQuestionOut,
    status_code=status.HTTP_201_CREATED,
    summary="Novo pitanje",
    description="Pitanje vide samo ja i HR. Najviše 5 novih pitanja dnevno.",
    responses={
        **R_404,
        409: {"model": ErrorResponse, "description": "`HR_QUESTION_DAILY_LIMIT`."},
        422: {"model": ErrorResponse, "description": "`HR_QUESTION_CATEGORY_INVALID` ili `VALIDATION_ERROR`."},
    },
)
def ask(
    payload: HrQuestionCreateRequest,
    korisnik: Korisnik = Depends(get_current_ready_user),
    service: HrQuestionService = Depends(get_hr_question_service),
) -> HrQuestionOut:
    return HrQuestionOut(**service.ask(korisnik, payload.kategorija_sifra, payload.tekst))


@router.get(
    "/{pitanje_id}",
    response_model=HrQuestionOut,
    summary="Pitanje sa odgovorima",
    description="Otvaranje označava odgovor pročitanim (bedž na početnom ekranu).",
    responses={**R_Q404},
)
def detail(
    pitanje_id: int,
    korisnik: Korisnik = Depends(get_current_ready_user),
    service: HrQuestionService = Depends(get_hr_question_service),
) -> HrQuestionOut:
    return HrQuestionOut(**service.detail(korisnik, pitanje_id))


@router.post(
    "/{pitanje_id}/follow-up",
    response_model=HrQuestionOut,
    summary="Dopunsko pitanje",
    description="Jednom, posle odgovora HR-a. Sledeći odgovor HR-a zatvara pitanje.",
    responses={
        **R_Q404,
        409: {"model": ErrorResponse, "description": "`HR_QUESTION_FOLLOW_UP_NOT_ALLOWED`."},
    },
)
def follow_up(
    pitanje_id: int,
    payload: HrFollowUpRequest,
    korisnik: Korisnik = Depends(get_current_ready_user),
    service: HrQuestionService = Depends(get_hr_question_service),
) -> HrQuestionOut:
    return HrQuestionOut(**service.follow_up(korisnik, pitanje_id, payload.tekst))
