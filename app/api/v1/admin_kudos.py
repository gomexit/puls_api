from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.dependencies.portal_auth import require_portal_admin_or_hr
from app.models.korisnik import Korisnik
from app.models.zahvalnica import STATUSI
from app.schemas.common import ErrorResponse
from app.schemas.kudos import AdminKudosListResponse, AdminKudosOut
from app.services.kudos_admin_service import KudosAdminService

router = APIRouter(prefix="/admin/kudos", tags=["Admin Hvala, kolega!"])

R_404 = {404: {"model": ErrorResponse, "description": "`KUDOS_NOT_FOUND`."}}
PAGE_SIZE_DEFAULT = 20
PAGE_SIZE_MAX = 100


def get_kudos_admin_service(db: Session = Depends(get_db)) -> KudosAdminService:
    return KudosAdminService(db)


@router.get(
    "",
    response_model=AdminKudosListResponse,
    summary="Lista zahvalnica (npr. prijavljene)",
    description="`status=NA_PROVERI` vraća one koje su kolege prijavile 3 puta i čekaju pregled. "
    "Najnovije prvo.",
    responses={422: {"model": ErrorResponse, "description": "`INVALID_KUDOS_STATUS`."}},
)
def list_kudos(
    status_filter: str | None = Query(default=None, alias="status", json_schema_extra={"enum": list(STATUSI)}),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=PAGE_SIZE_DEFAULT, ge=1, le=PAGE_SIZE_MAX),
    actor: Korisnik = Depends(require_portal_admin_or_hr),
    service: KudosAdminService = Depends(get_kudos_admin_service),
) -> AdminKudosListResponse:
    r = service.list(status_filter, page, page_size)
    return AdminKudosListResponse(
        items=[AdminKudosOut(**i) for i in r["items"]], total=r["total"], page=r["page"], page_size=r["page_size"]
    )


@router.get(
    "/{zahvalnica_id}",
    response_model=AdminKudosOut,
    summary="Detalji zahvalnice sa prijavama",
    description="Prijave sadrže samo razlog i vreme, bez imena prijavilaca.",
    responses={**R_404},
)
def get_kudos(
    zahvalnica_id: int,
    actor: Korisnik = Depends(require_portal_admin_or_hr),
    service: KudosAdminService = Depends(get_kudos_admin_service),
) -> AdminKudosOut:
    return AdminKudosOut(**service.get(zahvalnica_id))


@router.post(
    "/{zahvalnica_id}/hide",
    response_model=AdminKudosOut,
    summary="Sakrij zahvalnicu",
    description="Status SAKRIVENA; nestaje iz aplikacije. Upisuje se u audit.",
    responses={**R_404},
)
def hide(
    zahvalnica_id: int,
    actor: Korisnik = Depends(require_portal_admin_or_hr),
    service: KudosAdminService = Depends(get_kudos_admin_service),
) -> AdminKudosOut:
    return AdminKudosOut(**service.hide(actor, zahvalnica_id))


@router.post(
    "/{zahvalnica_id}/restore",
    response_model=AdminKudosOut,
    summary="Vrati zahvalnicu",
    description="Status OBJAVLJENA i oznaka da je pregledana: nove prijave je više ne sklanjaju same.",
    responses={**R_404},
)
def restore(
    zahvalnica_id: int,
    actor: Korisnik = Depends(require_portal_admin_or_hr),
    service: KudosAdminService = Depends(get_kudos_admin_service),
) -> AdminKudosOut:
    return AdminKudosOut(**service.restore(actor, zahvalnica_id))
