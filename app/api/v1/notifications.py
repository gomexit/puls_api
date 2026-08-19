from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.exceptions import ValidationBusinessError
from app.db.session import get_db
from app.dependencies.auth import get_current_ready_user
from app.models.korisnik import Korisnik
from app.schemas.notification import (
    MarkReadResponse,
    NotificationDetailResponse,
    NotificationListItem,
    NotificationListResponse,
    UnreadCountResponse,
)
from app.services.notification_service import NotificationService

router = APIRouter(prefix="/notifications", tags=["Notifications"])

PAGE_SIZE_DEFAULT = 20
PAGE_SIZE_MAX = 100
CATEGORY_MAX = 50


def get_notification_service(db: Session = Depends(get_db)) -> NotificationService:
    return NotificationService(db)


def _normalize_category(category: str | None) -> str | None:
    """Trim + uppercase sifre kategorije. Prazno posle trima ili preko 50 karaktera
    je VALIDATION_ERROR (422). None (filter nije prosledjen) prolazi kao None."""
    if category is None:
        return None
    normalized = category.strip()
    if not normalized or len(normalized) > CATEGORY_MAX:
        raise ValidationBusinessError("Neispravna šifra kategorije.")
    return normalized.upper()


@router.get("", response_model=NotificationListResponse)
def list_notifications(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=PAGE_SIZE_DEFAULT, ge=1, le=PAGE_SIZE_MAX),
    read_status: Literal["ALL", "READ", "UNREAD"] = Query(default="ALL"),
    category: str | None = Query(default=None),
    korisnik: Korisnik = Depends(get_current_ready_user),
    service: NotificationService = Depends(get_notification_service),
) -> NotificationListResponse:
    result = service.list_inbox(korisnik, page, page_size, read_status, _normalize_category(category))
    return NotificationListResponse(
        items=[NotificationListItem(**it) for it in result["items"]],
        page=result["page"],
        page_size=result["page_size"],
        total=result["total"],
        has_more=result["has_more"],
        unread_count=result["unread_count"],
    )


# VAZNO: staticka ruta pre /{notification_id} da ne dodje do route konflikta.
@router.get("/unread-count", response_model=UnreadCountResponse)
def unread_count(
    korisnik: Korisnik = Depends(get_current_ready_user),
    service: NotificationService = Depends(get_notification_service),
) -> UnreadCountResponse:
    return UnreadCountResponse(unread_count=service.unread_count(korisnik))


@router.get("/{notification_id}", response_model=NotificationDetailResponse)
def get_notification(
    notification_id: int,
    korisnik: Korisnik = Depends(get_current_ready_user),
    service: NotificationService = Depends(get_notification_service),
) -> NotificationDetailResponse:
    return NotificationDetailResponse(**service.get_detail(korisnik, notification_id))


@router.patch("/{notification_id}/read", response_model=MarkReadResponse)
def mark_read(
    notification_id: int,
    korisnik: Korisnik = Depends(get_current_ready_user),
    service: NotificationService = Depends(get_notification_service),
) -> MarkReadResponse:
    primalac, unread = service.mark_read(korisnik, notification_id)
    return MarkReadResponse(
        id=notification_id,
        procitano=primalac.procitano == "D",
        datum_citanja=primalac.datum_citanja,
        unread_count=unread,
    )


@router.patch("/{notification_id}/unread", response_model=MarkReadResponse)
def mark_unread(
    notification_id: int,
    korisnik: Korisnik = Depends(get_current_ready_user),
    service: NotificationService = Depends(get_notification_service),
) -> MarkReadResponse:
    primalac, unread = service.mark_unread(korisnik, notification_id)
    return MarkReadResponse(
        id=notification_id,
        procitano=primalac.procitano == "D",
        datum_citanja=primalac.datum_citanja,
        unread_count=unread,
    )
