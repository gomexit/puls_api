"""Javni (bez autentikacije) endpoint za Android - poziva se pri pokretanju
aplikacije, pre login-a, pa NAMERNO ne zahteva ni Bearer token ni OBO portal
zaglavlja."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.app_version import AppVersionResponse
from app.services.app_version_service import AppVersionService

router = APIRouter(prefix="/app", tags=["App Version"])


def get_app_version_service(db: Session = Depends(get_db)) -> AppVersionService:
    return AppVersionService(db)


@router.get("/version", response_model=AppVersionResponse)
def get_app_version(
    service: AppVersionService = Depends(get_app_version_service),
) -> AppVersionResponse:
    return AppVersionResponse(**service.get_version_info())
