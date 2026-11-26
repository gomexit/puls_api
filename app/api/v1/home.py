from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.dependencies.auth import get_current_ready_user
from app.models.korisnik import Korisnik
from app.repositories.configuration_repository import ConfigurationRepository
from app.repositories.module_access_repository import ModuleAccessRepository
from app.schemas.home import HomeModuleOut, HomeSummaryResponse
from app.services.game_service import MODULE_CODE as GAME_MODULE_CODE
from app.services.game_service import GameService
from app.services.home_summary_service import HomeSummaryService
from app.services.kudos_service import MODULE_CODE as KUDOS_MODULE_CODE
from app.services.kudos_service import KudosService
from app.services.module_access_service import ModuleAccessService
from app.services.quiz_service import MODULE_CODE as QUIZ_MODULE_CODE
from app.services.quiz_service import QuizService

router = APIRouter(prefix="/home", tags=["Home"])


def get_home_summary_service(db: Session = Depends(get_db)) -> HomeSummaryService:
    access_repo = ModuleAccessRepository(db)
    module_access = ModuleAccessService(ConfigurationRepository(db), access_repo)
    quiz = QuizService(db, module_access=module_access, access_repository=access_repo)
    game = GameService(db, module_access=module_access)
    kudos = KudosService(db, module_access=module_access)
    return HomeSummaryService(
        module_access,
        badge_counters={
            QUIZ_MODULE_CODE: quiz.badge_count,
            GAME_MODULE_CODE: game.badge_count,
            KUDOS_MODULE_CODE: kudos.badge_count,
        },
    )


@router.get(
    "/summary",
    response_model=HomeSummaryResponse,
    summary="Početni ekran „Moj kutak“",
    description=(
        "Vraća sve nove module (Moje pogodnosti, Pitaj HR, Puls izazov, Gomex putanja, "
        "Hvala, kolega!) u redosledu pločica, sa oznakom da li ih korisnik vidi i brojem "
        "novih stavki. Modul se uključuje ključem `MODUL_<NAZIV>` u konfiguraciji "
        "(`ISKLJUCEN`, `PILOT`, `SVI`); `PILOT` važi za `MODUL_PILOT_ORGJED` i "
        "`MODUL_PILOT_PLATNI_BROJ`."
    ),
)
def get_home_summary(
    korisnik: Korisnik = Depends(get_current_ready_user),
    service: HomeSummaryService = Depends(get_home_summary_service),
) -> HomeSummaryResponse:
    result = service.summary(korisnik)
    return HomeSummaryResponse(moduli=[HomeModuleOut(**m) for m in result["moduli"]])
