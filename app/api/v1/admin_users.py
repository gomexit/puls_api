from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.exceptions import ValidationBusinessError
from app.db.session import get_db
from app.dependencies.portal_auth import require_portal_admin
from app.models.korisnik import Korisnik
from app.schemas.admin_users import (
    AdminUserListResponse,
    AdminUserOut,
    AdminUserPasswordResetResponse,
)
from app.services.admin_users_service import AdminUsersService

router = APIRouter(prefix="/admin/users", tags=["Admin Users"])

PAGE_SIZE_DEFAULT = 20
PAGE_SIZE_MAX = 100
SEARCH_MAX = 100


def get_admin_users_service(db: Session = Depends(get_db)) -> AdminUsersService:
    return AdminUsersService(db)


def _normalize_search(value: str | None) -> str | None:
    """Trim; prazno posle trimovanja ili predugacko -> 422 (ne 500)."""
    if value is None:
        return None
    v = value.strip()
    if not v:
        raise ValidationBusinessError("search ne sme biti prazan.")
    if len(v) > SEARCH_MAX:
        raise ValidationBusinessError("search je predugačak.")
    return v


@router.get("", response_model=AdminUserListResponse)
def list_users(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=PAGE_SIZE_DEFAULT, ge=1, le=PAGE_SIZE_MAX),
    search: str | None = Query(default=None),
    status_zaposlenja: Literal["AKTIVAN", "NEAKTIVAN"] | None = Query(default=None),
    status_naloga: Literal["OMOGUCEN", "ONEMOGUCEN"] | None = Query(default=None),
    zakljucan: bool | None = Query(default=None),
    uloga: Literal["ADMIN", "HR", "ZAPOSLENI"] | None = Query(default=None),
    _: Korisnik = Depends(require_portal_admin),
    service: AdminUsersService = Depends(get_admin_users_service),
) -> AdminUserListResponse:
    search = _normalize_search(search)
    result = service.list_users(
        page, page_size, search, status_zaposlenja, status_naloga, zakljucan, uloga
    )
    return AdminUserListResponse(
        items=[AdminUserOut(**u) for u in result["items"]],
        page=result["page"],
        page_size=result["page_size"],
        total=result["total"],
        has_more=result["has_more"],
    )


@router.get("/{user_id}", response_model=AdminUserOut)
def get_user(
    user_id: int,
    _: Korisnik = Depends(require_portal_admin),
    service: AdminUsersService = Depends(get_admin_users_service),
) -> AdminUserOut:
    return AdminUserOut(**service.get_user(user_id))


@router.patch("/{user_id}/lock", response_model=AdminUserOut)
def lock_user(
    user_id: int,
    actor: Korisnik = Depends(require_portal_admin),
    service: AdminUsersService = Depends(get_admin_users_service),
) -> AdminUserOut:
    return AdminUserOut(**service.lock(actor, user_id))


@router.patch("/{user_id}/unlock", response_model=AdminUserOut)
def unlock_user(
    user_id: int,
    actor: Korisnik = Depends(require_portal_admin),
    service: AdminUsersService = Depends(get_admin_users_service),
) -> AdminUserOut:
    return AdminUserOut(**service.unlock(actor, user_id))


@router.patch("/{user_id}/deactivate", response_model=AdminUserOut)
def deactivate_user(
    user_id: int,
    actor: Korisnik = Depends(require_portal_admin),
    service: AdminUsersService = Depends(get_admin_users_service),
) -> AdminUserOut:
    return AdminUserOut(**service.deactivate(actor, user_id))


@router.post("/{user_id}/reset-password", response_model=AdminUserPasswordResetResponse)
def reset_password(
    user_id: int,
    actor: Korisnik = Depends(require_portal_admin),
    service: AdminUsersService = Depends(get_admin_users_service),
) -> AdminUserPasswordResetResponse:
    return AdminUserPasswordResetResponse(**service.reset_password(actor, user_id))
