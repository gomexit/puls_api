from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.dependencies.portal_auth import require_portal_admin
from app.models.korisnik import Korisnik
from app.schemas.admin_configuration import (
    AdminConfigurationItemOut,
    AdminConfigurationListResponse,
    AdminConfigurationUpdateRequest,
)
from app.services.admin_configuration_service import AdminConfigurationService

router = APIRouter(prefix="/admin/configuration", tags=["Admin Configuration"])


def get_admin_configuration_service(db: Session = Depends(get_db)) -> AdminConfigurationService:
    return AdminConfigurationService(db)


@router.get("", response_model=AdminConfigurationListResponse)
def list_configuration(
    _: Korisnik = Depends(require_portal_admin),
    service: AdminConfigurationService = Depends(get_admin_configuration_service),
) -> AdminConfigurationListResponse:
    result = service.list_configuration()
    return AdminConfigurationListResponse(
        items=[AdminConfigurationItemOut(**item) for item in result["items"]]
    )


@router.put("/{key}", response_model=AdminConfigurationItemOut)
def update_configuration(
    key: str,
    payload: AdminConfigurationUpdateRequest,
    actor: Korisnik = Depends(require_portal_admin),
    service: AdminConfigurationService = Depends(get_admin_configuration_service),
) -> AdminConfigurationItemOut:
    result = service.update_configuration(actor, key, payload.vrednost)
    return AdminConfigurationItemOut(**result)
