from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.dependencies.portal_auth import require_portal_admin_or_hr
from app.models.korisnik import Korisnik
from app.schemas.admin_dashboard import AdminDashboardResponse
from app.services.admin_dashboard_service import AdminDashboardService

router = APIRouter(prefix="/admin", tags=["Admin Dashboard"])


def get_admin_dashboard_service(db: Session = Depends(get_db)) -> AdminDashboardService:
    return AdminDashboardService(db)


@router.get("/dashboard", response_model=AdminDashboardResponse)
def get_dashboard(
    _: Korisnik = Depends(require_portal_admin_or_hr),
    service: AdminDashboardService = Depends(get_admin_dashboard_service),
) -> AdminDashboardResponse:
    return AdminDashboardResponse(**service.get_dashboard())
