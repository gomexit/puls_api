from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.dependencies.portal_auth import require_portal_admin_or_hr
from app.models.korisnik import Korisnik
from app.models.kviz import KVIZ_STATUSI
from app.schemas.common import ErrorResponse
from app.schemas.quiz import (
    STATUS_DESCRIPTION,
    AdminQuizListResponse,
    AdminQuizOut,
    AdminQuizResultsOut,
    AdminQuizSummaryOut,
    QuizCategoryCreateRequest,
    QuizCategoryListResponse,
    QuizCategoryOut,
    QuizCategoryUpdateRequest,
    QuizCreateRequest,
    QuizStatusRequest,
    QuizUpdateRequest,
)
from app.services.quiz_admin_service import QuizAdminService

router = APIRouter(prefix="/admin/quizzes", tags=["Admin Puls izazov"])
categories_router = APIRouter(prefix="/admin/quiz-categories", tags=["Admin Puls izazov"])

R_404 = {404: {"model": ErrorResponse, "description": "`QUIZ_NOT_FOUND` - kviz ne postoji."}}
R_422 = {422: {"model": ErrorResponse, "description": "`VALIDATION_ERROR`, `INVALID_QUIZ_STATUS` ili `QUIZ_NOT_READY`."}}
R_409 = {
    409: {
        "model": ErrorResponse,
        "description": "`QUIZ_LOCKED`, `QUIZ_ARCHIVED`, `QUIZ_PERIOD_OVERLAP` ili `INVALID_QUIZ_STATUS_TRANSITION`.",
    }
}
R_CAT_404 = {404: {"model": ErrorResponse, "description": "`QUIZ_CATEGORY_NOT_FOUND`."}}
R_CAT_409 = {409: {"model": ErrorResponse, "description": "`QUIZ_CATEGORY_ALREADY_EXISTS`."}}

PAGE_SIZE_DEFAULT = 20
PAGE_SIZE_MAX = 100


def get_quiz_admin_service(db: Session = Depends(get_db)) -> QuizAdminService:
    return QuizAdminService(db)


# ================================================================ kategorije
@categories_router.get(
    "",
    response_model=QuizCategoryListResponse,
    summary="Šifarnik kategorija pitanja",
    description="Sve kategorije po `redosled`. Filter `aktivna` je opcion.",
)
def list_categories(
    aktivna: bool | None = Query(default=None),
    actor: Korisnik = Depends(require_portal_admin_or_hr),
    service: QuizAdminService = Depends(get_quiz_admin_service),
) -> QuizCategoryListResponse:
    return QuizCategoryListResponse(items=[QuizCategoryOut(**k) for k in service.list_categories(aktivna)])


@categories_router.post(
    "",
    response_model=QuizCategoryOut,
    status_code=status.HTTP_201_CREATED,
    summary="Nova kategorija",
    description="`sifra` se pretvara u velika slova; dozvoljeno A-Z, 0-9 i _. Brisanja nema - "
    "kategorija se isključuje sa `aktivna=false` (ostaje na postojećim pitanjima).",
    responses={**R_CAT_409, **R_422},
)
def create_category(
    payload: QuizCategoryCreateRequest,
    actor: Korisnik = Depends(require_portal_admin_or_hr),
    service: QuizAdminService = Depends(get_quiz_admin_service),
) -> QuizCategoryOut:
    return QuizCategoryOut(
        **service.create_category(actor, payload.sifra, payload.naziv, payload.redosled, payload.aktivna)
    )


@categories_router.put(
    "/{sifra}",
    response_model=QuizCategoryOut,
    summary="Izmena kategorije",
    description="Menja naziv, redosled i aktivnost. Šifra se ne menja. Identična izmena je no-op.",
    responses={**R_CAT_404, **R_422},
)
def update_category(
    sifra: str,
    payload: QuizCategoryUpdateRequest,
    actor: Korisnik = Depends(require_portal_admin_or_hr),
    service: QuizAdminService = Depends(get_quiz_admin_service),
) -> QuizCategoryOut:
    return QuizCategoryOut(
        **service.update_category(actor, sifra, payload.naziv, payload.redosled, payload.aktivna)
    )


# ================================================================== kvizovi
@router.get(
    "",
    response_model=AdminQuizListResponse,
    summary="Lista kvizova",
    description="Najnoviji `datum_od` prvi. Filteri `status` i `search` (naziv) su opcioni.\n\n" + STATUS_DESCRIPTION,
)
def list_quizzes(
    status_filter: str | None = Query(default=None, alias="status", json_schema_extra={"enum": list(KVIZ_STATUSI)}),
    search: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=PAGE_SIZE_DEFAULT, ge=1, le=PAGE_SIZE_MAX),
    actor: Korisnik = Depends(require_portal_admin_or_hr),
    service: QuizAdminService = Depends(get_quiz_admin_service),
) -> AdminQuizListResponse:
    result = service.list_quizzes(status_filter, search, page, page_size)
    return AdminQuizListResponse(
        items=[AdminQuizSummaryOut(**it) for it in result["items"]],
        total=result["total"],
        page=result["page"],
        page_size=result["page_size"],
    )


@router.get("/{kviz_id}", response_model=AdminQuizOut, summary="Detalj kviza (sa tačnim odgovorima)", responses={**R_404})
def get_quiz(
    kviz_id: int,
    actor: Korisnik = Depends(require_portal_admin_or_hr),
    service: QuizAdminService = Depends(get_quiz_admin_service),
) -> AdminQuizOut:
    return AdminQuizOut(**service.get_quiz(kviz_id))


@router.post(
    "",
    response_model=AdminQuizOut,
    status_code=status.HTTP_201_CREATED,
    summary="Novi kviz (DRAFT)",
    description=(
        "Kviz se pravi u statusu DRAFT. Pitanja (do 10, preporuka 5): 2-4 odgovora, tačno jedan "
        "`tacna=true`, `kategorija_sifra` iz aktivnog šifarnika, opciono `slika_id` aktivne slike. "
        "`ciljevi` prazno = svi zaposleni kojima je modul uključen; inače `ORGJED` (šifra org. "
        "jedinice) ili `PLATNI_BROJ`. Datumi su lokalno vreme bez zone."
    ),
    responses={**R_422},
)
def create_quiz(
    payload: QuizCreateRequest,
    actor: Korisnik = Depends(require_portal_admin_or_hr),
    service: QuizAdminService = Depends(get_quiz_admin_service),
) -> AdminQuizOut:
    return AdminQuizOut(**service.create_quiz(actor, payload.model_dump()))


@router.put(
    "/{kviz_id}",
    response_model=AdminQuizOut,
    summary="Izmena kviza",
    description=(
        "Šalju se samo polja koja se menjaju. DRAFT: sve; `pitanja` i `ciljevi` se zamenjuju u "
        "celini ako se pošalju. OBJAVLJEN: samo `naziv`, `opis` i `datum_do` (samo produženje, bez "
        "preklapanja sa drugim objavljenim kvizom); ostalo daje 409 `QUIZ_LOCKED`. ARHIVIRAN: 409 "
        "`QUIZ_ARCHIVED`."
    ),
    responses={**R_404, **R_409, **R_422},
)
def update_quiz(
    kviz_id: int,
    payload: QuizUpdateRequest,
    actor: Korisnik = Depends(require_portal_admin_or_hr),
    service: QuizAdminService = Depends(get_quiz_admin_service),
) -> AdminQuizOut:
    return AdminQuizOut(**service.update_quiz(actor, kviz_id, payload.model_dump(exclude_unset=True)))


@router.patch(
    "/{kviz_id}/status",
    response_model=AdminQuizOut,
    summary="Objava ili arhiviranje kviza",
    description=STATUS_DESCRIPTION
    + "\n\nPrelazi: DRAFT -> OBJAVLJEN, DRAFT -> ARHIVIRAN, OBJAVLJEN -> ARHIVIRAN. Ista vrednost je "
    "idempotentna. Objava traži bar jedno pitanje, `datum_do` u budućnosti i period bez preklapanja "
    "sa drugim objavljenim kvizom. Zaposleni dobijaju push kad kviz počne i dan pre isteka.",
    responses={**R_404, **R_409, **R_422},
)
def change_quiz_status(
    kviz_id: int,
    payload: QuizStatusRequest,
    actor: Korisnik = Depends(require_portal_admin_or_hr),
    service: QuizAdminService = Depends(get_quiz_admin_service),
) -> AdminQuizOut:
    return AdminQuizOut(**service.change_status(actor, kviz_id, payload.status))


@router.get(
    "/{kviz_id}/results",
    response_model=AdminQuizResultsOut,
    summary="Rezultati kviza",
    description="Ukupno, po org. jedinici (snimak u trenutku početka) i po pitanju. Bez pojedinačnih "
    "rezultata zaposlenih.",
    responses={**R_404},
)
def quiz_results(
    kviz_id: int,
    actor: Korisnik = Depends(require_portal_admin_or_hr),
    service: QuizAdminService = Depends(get_quiz_admin_service),
) -> AdminQuizResultsOut:
    return AdminQuizResultsOut(**service.results(kviz_id))
