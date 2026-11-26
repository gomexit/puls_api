from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.dependencies.auth import get_current_ready_user
from app.models.korisnik import Korisnik
from app.schemas.common import ErrorResponse
from app.schemas.game import (
    GameDailyResponse,
    GameLevelResponse,
    GameResultRequest,
    GameResultResponse,
)
from app.services.game_service import GameService

router = APIRouter(prefix="/game", tags=["Gomex putanja"])

R_404 = {404: {"model": ErrorResponse, "description": "`GAME_NOT_AVAILABLE` - modul nije uključen za mene."}}


def get_game_service(db: Session = Depends(get_db)) -> GameService:
    return GameService(db)


@router.get(
    "/daily",
    response_model=GameDailyResponse,
    summary="Današnji nivo: stanje i moj rezultat",
    description="Veličina table, moj status, moje vreme, niz dana zaredom i prosek moje prodavnice. "
    "Ne sadrži tablu (nju vraća `/game/daily/start`).",
    responses={**R_404},
)
def daily(
    korisnik: Korisnik = Depends(get_current_ready_user),
    service: GameService = Depends(get_game_service),
) -> GameDailyResponse:
    return GameDailyResponse(**service.daily(korisnik))


@router.post(
    "/daily/start",
    response_model=GameLevelResponse,
    summary="Pokretanje igre (tabla današnjeg nivoa)",
    description="Vraća tablu i pokreće serverski sat. Svako novo pokretanje pre rešenja kreće sat "
    "ispočetka. Posle rešenja može da se igra ponovo, ali se ne računa.",
    responses={**R_404},
)
def start(
    korisnik: Korisnik = Depends(get_current_ready_user),
    service: GameService = Depends(get_game_service),
) -> GameLevelResponse:
    return GameLevelResponse(**service.start(korisnik))


@router.post(
    "/daily/result",
    response_model=GameResultResponse,
    summary="Predaja rešenja",
    description="Server proverava putanju i meri vreme. Računa se prvo ispravno rešenje dana.",
    responses={
        **R_404,
        409: {"model": ErrorResponse, "description": "`GAME_NOT_STARTED` ili `GAME_LEVEL_EXPIRED` (prošla ponoć)."},
        422: {"model": ErrorResponse, "description": "`GAME_INVALID_PATH` ili `VALIDATION_ERROR`."},
    },
)
def submit(
    body: GameResultRequest,
    korisnik: Korisnik = Depends(get_current_ready_user),
    service: GameService = Depends(get_game_service),
) -> GameResultResponse:
    return GameResultResponse(**service.submit(korisnik, body.datum, body.putanja))
