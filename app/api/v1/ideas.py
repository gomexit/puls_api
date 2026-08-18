from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.dependencies.auth import get_current_ready_user
from app.models.ideja import Ideja
from app.models.korisnik import Korisnik
from app.schemas.idea import (
    CurrentCycleResponse,
    CycleSummary,
    IdeaCreateRequest,
    IdeaResponse,
    IdeaUpdateRequest,
    MyIdeasResponse,
    TopIdeaItem,
    TopIdeasResponse,
)
from app.services.idea_service import CurrentCycleOverview, IdeaService

router = APIRouter(prefix="/ideas", tags=["Ideas"])


def get_idea_service(db: Session = Depends(get_db)) -> IdeaService:
    return IdeaService(db)


def _to_idea_response(ideja: Ideja) -> IdeaResponse:
    return IdeaResponse(
        id=ideja.id,
        ciklus_id=ideja.ciklus_id,
        naslov=ideja.naslov,
        opis=ideja.opis,
        status=ideja.status,
        datum_kreiranja=ideja.datum_kreiranja,
        datum_izmene=ideja.datum_izmene,
    )


def _to_current_cycle_response(overview: CurrentCycleOverview) -> CurrentCycleResponse:
    cycle_summary = None
    if overview.cycle is not None:
        cycle_summary = CycleSummary(
            id=overview.cycle.id,
            naziv=overview.cycle.naziv,
            datum_pocetka=overview.cycle.datum_pocetka,
            datum_zavrsetka=overview.cycle.datum_zavrsetka,
            status=overview.cycle.status,
        )
    return CurrentCycleResponse(
        cycle=cycle_summary,
        submission_open=overview.submission_open,
        max_ideas=overview.max_ideas,
        used_ideas=overview.used_ideas,
        remaining_ideas=overview.remaining_ideas,
    )


@router.get("/current-cycle", response_model=CurrentCycleResponse)
def get_current_cycle(
    korisnik: Korisnik = Depends(get_current_ready_user),
    service: IdeaService = Depends(get_idea_service),
) -> CurrentCycleResponse:
    overview = service.get_current_cycle_overview(korisnik)
    return _to_current_cycle_response(overview)


@router.post("", response_model=IdeaResponse, status_code=status.HTTP_201_CREATED)
def create_idea(
    payload: IdeaCreateRequest,
    korisnik: Korisnik = Depends(get_current_ready_user),
    service: IdeaService = Depends(get_idea_service),
) -> IdeaResponse:
    ideja = service.create_idea(korisnik, payload.naslov, payload.opis)
    return _to_idea_response(ideja)


@router.get("/mine", response_model=MyIdeasResponse)
def list_my_ideas(
    cycle_id: int | None = Query(default=None),
    korisnik: Korisnik = Depends(get_current_ready_user),
    service: IdeaService = Depends(get_idea_service),
) -> MyIdeasResponse:
    ideje = service.list_my_ideas(korisnik, cycle_id)
    return MyIdeasResponse(items=[_to_idea_response(i) for i in ideje])


@router.get("/top", response_model=TopIdeasResponse)
def list_top_ideas(
    cycle_id: int | None = Query(default=None),
    korisnik: Korisnik = Depends(get_current_ready_user),
    service: IdeaService = Depends(get_idea_service),
) -> TopIdeasResponse:
    ranked = service.list_top(cycle_id)
    return TopIdeasResponse(
        items=[
            TopIdeaItem(
                id=r.ideja.id,
                rang=r.rang,
                ime=r.ideja.ime_autora,
                prezime=r.ideja.prezime_autora,
                naslov=r.ideja.naslov,
                status=r.ideja.status,
            )
            for r in ranked
        ]
    )


@router.get("/{idea_id}", response_model=IdeaResponse)
def get_my_idea(
    idea_id: int,
    korisnik: Korisnik = Depends(get_current_ready_user),
    service: IdeaService = Depends(get_idea_service),
) -> IdeaResponse:
    ideja = service.get_my_idea(korisnik, idea_id)
    return _to_idea_response(ideja)


@router.put("/{idea_id}", response_model=IdeaResponse)
def update_my_idea(
    idea_id: int,
    payload: IdeaUpdateRequest,
    korisnik: Korisnik = Depends(get_current_ready_user),
    service: IdeaService = Depends(get_idea_service),
) -> IdeaResponse:
    ideja = service.update_my_idea(korisnik, idea_id, payload.naslov, payload.opis)
    return _to_idea_response(ideja)
