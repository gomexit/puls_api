from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.dependencies.portal_auth import require_portal_admin_or_hr
from app.models.idea_ciklus import IdeaCiklus
from app.models.ideja import Ideja
from app.models.korisnik import Korisnik
from app.schemas.idea import (
    AdminCycleCreateRequest,
    AdminCycleListResponse,
    AdminCyclePatchRequest,
    AdminCycleResponse,
    AdminIdeaHrScoreRequest,
    AdminIdeaListResponse,
    AdminIdeaResponse,
    AdminIdeaStatusRequest,
)
from app.services.idea_admin_service import IdeaAdminService

router = APIRouter(prefix="/admin", tags=["Admin Ideas"])

PAGE_SIZE_DEFAULT = 50
PAGE_SIZE_MAX = 100


def get_idea_admin_service(db: Session = Depends(get_db)) -> IdeaAdminService:
    return IdeaAdminService(db)


def _to_cycle_response(ciklus: IdeaCiklus) -> AdminCycleResponse:
    return AdminCycleResponse(
        id=ciklus.id,
        naziv=ciklus.naziv,
        datum_pocetka=ciklus.datum_pocetka,
        datum_zavrsetka=ciklus.datum_zavrsetka,
        status=ciklus.status,
        datum_kreiranja=ciklus.datum_kreiranja,
        datum_izmene=ciklus.datum_izmene,
    )


def _to_admin_idea_response(ideja: Ideja) -> AdminIdeaResponse:
    return AdminIdeaResponse(
        id=ideja.id,
        korisnik_id=ideja.korisnik_id,
        ciklus_id=ideja.ciklus_id,
        platni_broj=ideja.platni_broj,
        ime_autora=ideja.ime_autora,
        prezime_autora=ideja.prezime_autora,
        orgjed_sifra=ideja.orgjed_sifra,
        naslov=ideja.naslov,
        opis=ideja.opis,
        status=ideja.status,
        hr_ocena=int(ideja.hr_ocena) if ideja.hr_ocena is not None else None,
        ai_ocena=ideja.ai_ocena,
        konacna_ocena=ideja.konacna_ocena,
        datum_kreiranja=ideja.datum_kreiranja,
        datum_izmene=ideja.datum_izmene,
    )


# --- Ciklusi ---
@router.get("/idea-cycles", response_model=AdminCycleListResponse)
def list_idea_cycles(
    _: Korisnik = Depends(require_portal_admin_or_hr),
    service: IdeaAdminService = Depends(get_idea_admin_service),
) -> AdminCycleListResponse:
    cycles = service.list_cycles()
    return AdminCycleListResponse(items=[_to_cycle_response(c) for c in cycles])


@router.post("/idea-cycles", response_model=AdminCycleResponse, status_code=status.HTTP_201_CREATED)
def create_idea_cycle(
    payload: AdminCycleCreateRequest,
    actor: Korisnik = Depends(require_portal_admin_or_hr),
    service: IdeaAdminService = Depends(get_idea_admin_service),
) -> AdminCycleResponse:
    ciklus = service.create_cycle(
        actor, payload.naziv, payload.datum_pocetka, payload.datum_zavrsetka
    )
    return _to_cycle_response(ciklus)


@router.patch("/idea-cycles/{cycle_id}", response_model=AdminCycleResponse)
def patch_idea_cycle(
    cycle_id: int,
    payload: AdminCyclePatchRequest,
    actor: Korisnik = Depends(require_portal_admin_or_hr),
    service: IdeaAdminService = Depends(get_idea_admin_service),
) -> AdminCycleResponse:
    ciklus = service.change_cycle_status(actor, cycle_id, payload.status)
    return _to_cycle_response(ciklus)


# --- Ideje ---
@router.get("/ideas", response_model=AdminIdeaListResponse)
def list_ideas(
    cycle_id: int | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    korisnik_id: int | None = Query(default=None),
    platni_broj: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=PAGE_SIZE_DEFAULT, ge=1, le=PAGE_SIZE_MAX),
    _: Korisnik = Depends(require_portal_admin_or_hr),
    service: IdeaAdminService = Depends(get_idea_admin_service),
) -> AdminIdeaListResponse:
    items, total = service.list_ideas(
        cycle_id, status_filter, korisnik_id, platni_broj, page, page_size
    )
    return AdminIdeaListResponse(
        items=[_to_admin_idea_response(i) for i in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/ideas/{idea_id}", response_model=AdminIdeaResponse)
def get_idea(
    idea_id: int,
    _: Korisnik = Depends(require_portal_admin_or_hr),
    service: IdeaAdminService = Depends(get_idea_admin_service),
) -> AdminIdeaResponse:
    return _to_admin_idea_response(service.get_idea(idea_id))


@router.patch("/ideas/{idea_id}/status", response_model=AdminIdeaResponse)
def change_idea_status(
    idea_id: int,
    payload: AdminIdeaStatusRequest,
    actor: Korisnik = Depends(require_portal_admin_or_hr),
    service: IdeaAdminService = Depends(get_idea_admin_service),
) -> AdminIdeaResponse:
    ideja = service.change_idea_status(actor, idea_id, payload.status)
    return _to_admin_idea_response(ideja)


@router.put("/ideas/{idea_id}/hr-score", response_model=AdminIdeaResponse)
def set_hr_score(
    idea_id: int,
    payload: AdminIdeaHrScoreRequest,
    actor: Korisnik = Depends(require_portal_admin_or_hr),
    service: IdeaAdminService = Depends(get_idea_admin_service),
) -> AdminIdeaResponse:
    ideja = service.set_hr_score(actor, idea_id, payload.hr_ocena)
    return _to_admin_idea_response(ideja)