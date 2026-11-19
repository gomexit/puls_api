from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.dependencies.auth import get_current_ready_user
from app.models.korisnik import Korisnik
from app.repositories.configuration_repository import ConfigurationRepository
from app.repositories.module_access_repository import ModuleAccessRepository
from app.schemas.home import HomeModuleOut, HomeSummaryResponse
from app.services.home_summary_service import HomeSummaryService
from app.services.module_access_service import ModuleAccessService

router = APIRouter(prefix="/home", tags=["Home"])


def get_home_summary_service(db: Session = Depends(get_db)) -> HomeSummaryService:
    return HomeSummaryService(
        ModuleAccessService(ConfigurationRepository(db), ModuleAccessRepository(db))
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
