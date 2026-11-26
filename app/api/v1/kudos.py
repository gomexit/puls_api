from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.dependencies.auth import get_current_ready_user
from app.models.korisnik import Korisnik
from app.schemas.common import ErrorResponse
from app.schemas.kudos import (
    ColleagueOut,
    ColleagueSearchResponse,
    KudosCreateRequest,
    KudosFeedResponse,
    KudosMineResponse,
    KudosOut,
    KudosReportRequest,
    KudosReportResponse,
)
from app.services.kudos_service import KudosService

router = APIRouter(prefix="/kudos", tags=["Hvala, kolega!"])
colleagues_router = APIRouter(prefix="/colleagues", tags=["Hvala, kolega!"])

R_404 = {404: {"model": ErrorResponse, "description": "`KUDOS_NOT_AVAILABLE` - modul nije uključen za mene."}}
PAGE_SIZE_DEFAULT = 20
PAGE_SIZE_MAX = 50


def get_kudos_service(db: Session = Depends(get_db)) -> KudosService:
    return KudosService(db)


@router.get(
    "/feed",
    response_model=KudosFeedResponse,
    summary="Zahvalnice (moja prodavnica ili svi)",
    description="Objavljene zahvalnice, najnovije prvo. `prodavnica` = pošiljalac ili primalac je iz "
    "moje primarne org. jedinice.",
    responses={**R_404},
)
def feed(
    opseg: str = Query(default="prodavnica", pattern="^(prodavnica|svi)$"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=PAGE_SIZE_DEFAULT, ge=1, le=PAGE_SIZE_MAX),
    korisnik: Korisnik = Depends(get_current_ready_user),
    service: KudosService = Depends(get_kudos_service),
) -> KudosFeedResponse:
    r = service.feed(korisnik, opseg, page, page_size)
    return KudosFeedResponse(opseg=r["opseg"], items=[KudosOut(**i) for i in r["items"]], ima_jos=r["ima_jos"])


@router.get(
    "/mine",
    response_model=KudosMineResponse,
    summary="Moje zahvalnice (primljene ili poslate)",
    description="Prva strana primljenih označava ih pročitanim (bedž na početnom ekranu).",
    responses={**R_404},
)
def mine(
    smer: str = Query(default="primljene", pattern="^(primljene|poslate)$"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=PAGE_SIZE_DEFAULT, ge=1, le=PAGE_SIZE_MAX),
    korisnik: Korisnik = Depends(get_current_ready_user),
    service: KudosService = Depends(get_kudos_service),
) -> KudosMineResponse:
    r = service.mine(korisnik, smer, page, page_size)
    return KudosMineResponse(smer=r["smer"], items=[KudosOut(**i) for i in r["items"]], ima_jos=r["ima_jos"])


@router.post(
    "",
    response_model=KudosOut,
    status_code=status.HTTP_201_CREATED,
    summary="Pošalji zahvalnicu",
    description="Objavljuje se odmah; primalac dobija obaveštenje. Najviše 5 dnevno, ne sebi, bez "
    "neprimerenih reči.",
    responses={
        **R_404,
        409: {"model": ErrorResponse, "description": "`KUDOS_DAILY_LIMIT`."},
        422: {
            "model": ErrorResponse,
            "description": "`KUDOS_SELF`, `KUDOS_RECIPIENT_INVALID`, `KUDOS_INAPPROPRIATE` ili `VALIDATION_ERROR`.",
        },
    },
)
def create(
    body: KudosCreateRequest,
    korisnik: Korisnik = Depends(get_current_ready_user),
    service: KudosService = Depends(get_kudos_service),
) -> KudosOut:
    return KudosOut(**service.send(korisnik, body.primalac_id, body.povod, body.tekst))


@router.post(
    "/{zahvalnica_id}/report",
    response_model=KudosReportResponse,
    summary="Prijavi neprimerenu zahvalnicu",
    description="Jedna prijava po zaposlenom (ponovljena se ignoriše). Posle 3 prijave zahvalnica se "
    "sklanja dok je HR ne pogleda.",
    responses={
        404: {"model": ErrorResponse, "description": "`KUDOS_NOT_AVAILABLE` ili `KUDOS_NOT_FOUND`."},
        422: {"model": ErrorResponse, "description": "`KUDOS_CANNOT_REPORT` (moja zahvalnica)."},
    },
)
def report(
    zahvalnica_id: int,
    body: KudosReportRequest | None = None,
    korisnik: Korisnik = Depends(get_current_ready_user),
    service: KudosService = Depends(get_kudos_service),
) -> KudosReportResponse:
    return KudosReportResponse(**service.report(korisnik, zahvalnica_id, body.razlog if body else None))


@colleagues_router.get(
    "/search",
    response_model=ColleagueSearchResponse,
    summary="Pretraga kolega (za zahvalnicu)",
    description="Najmanje 3 slova; samo aktivni zaposleni kojima je modul uključen, bez mene. Vraća samo "
    "ime, prezime i naziv org. jedinice (najviše 20).",
    responses={**R_404},
)
def search(
    q: str = Query(min_length=1, max_length=60),
    korisnik: Korisnik = Depends(get_current_ready_user),
    service: KudosService = Depends(get_kudos_service),
) -> ColleagueSearchResponse:
    return ColleagueSearchResponse(items=[ColleagueOut(**c) for c in service.search_colleagues(korisnik, q)])
