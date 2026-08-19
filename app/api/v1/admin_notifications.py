import datetime

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.core.exceptions import ValidationBusinessError
from app.db.session import get_db
from app.dependencies.portal_auth import require_portal_admin_or_hr
from app.models.korisnik import Korisnik
from app.models.obavestenje import OBAVESTENJE_STATUSI
from app.schemas.notification import (
    AdminNotificationCategoryCreateRequest,
    AdminNotificationCategoryListResponse,
    AdminNotificationCategoryOut,
    AdminNotificationCategoryUpdateRequest,
    AdminNotificationDetailResponse,
    AdminNotificationListItem,
    AdminNotificationListResponse,
    AdminNotificationStatsResponse,
    AdminNotificationStatusRequest,
    NotificationDraftInput,
    normalize_category_sifra,
)
from app.services.notification_admin_service import NotificationAdminService

router = APIRouter(prefix="/admin", tags=["Admin Notifications"])

PAGE_SIZE_DEFAULT = 50
PAGE_SIZE_MAX = 100


def get_notification_admin_service(db: Session = Depends(get_db)) -> NotificationAdminService:
    return NotificationAdminService(db)


def _normalize_sifra_or_422(sifra: str) -> str:
    # Ista pravila kao schema; ValueError iz normalizacije -> VALIDATION_ERROR (422).
    try:
        return normalize_category_sifra(sifra)
    except ValueError as exc:
        raise ValidationBusinessError("Neispravna šifra kategorije.") from exc


def _normalize_category_filter(category: str | None) -> str | None:
    return None if category is None else _normalize_sifra_or_422(category)


def _normalize_status_filter(status_value: str | None) -> str | None:
    if status_value is None:
        return None
    normalized = status_value.strip().upper()
    if normalized not in OBAVESTENJE_STATUSI:
        raise ValidationBusinessError("Nepoznat status obaveštenja.")
    return normalized


def _category_out(kat) -> AdminNotificationCategoryOut:
    return AdminNotificationCategoryOut(
        sifra=kat.sifra,
        naziv=kat.naziv,
        aktivna=kat.aktivna == "D",
        redosled=int(kat.redosled) if kat.redosled is not None else None,
        datum_kreiranja=kat.datum_kreiranja,
        datum_izmene=kat.datum_izmene,
    )


# ============================================================== KATEGORIJE
@router.get("/notification-categories", response_model=AdminNotificationCategoryListResponse)
def list_categories(
    aktivna: bool | None = Query(default=None),
    actor: Korisnik = Depends(require_portal_admin_or_hr),
    service: NotificationAdminService = Depends(get_notification_admin_service),
) -> AdminNotificationCategoryListResponse:
    return AdminNotificationCategoryListResponse(
        items=[_category_out(k) for k in service.list_categories(aktivna)]
    )


@router.post(
    "/notification-categories",
    response_model=AdminNotificationCategoryOut,
    status_code=status.HTTP_201_CREATED,
)
def create_category(
    payload: AdminNotificationCategoryCreateRequest,
    actor: Korisnik = Depends(require_portal_admin_or_hr),
    service: NotificationAdminService = Depends(get_notification_admin_service),
) -> AdminNotificationCategoryOut:
    kat = service.create_category(actor, payload.sifra, payload.naziv, payload.aktivna, payload.redosled)
    return _category_out(kat)


@router.put("/notification-categories/{sifra}", response_model=AdminNotificationCategoryOut)
def update_category(
    sifra: str,
    payload: AdminNotificationCategoryUpdateRequest,
    actor: Korisnik = Depends(require_portal_admin_or_hr),
    service: NotificationAdminService = Depends(get_notification_admin_service),
) -> AdminNotificationCategoryOut:
    # Normalizuj path sifru (lowercase path pronalazi uppercase kategoriju).
    kat = service.update_category(
        actor, _normalize_sifra_or_422(sifra), payload.naziv, payload.aktivna, payload.redosled
    )
    return _category_out(kat)


# ============================================================== OBAVESTENJA
@router.get("/notifications", response_model=AdminNotificationListResponse)
def list_notifications(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=PAGE_SIZE_DEFAULT, ge=1, le=PAGE_SIZE_MAX),
    status_filter: str | None = Query(default=None, alias="status"),
    category: str | None = Query(default=None),
    datum_od: datetime.datetime | None = Query(default=None),
    datum_do: datetime.datetime | None = Query(default=None),
    actor: Korisnik = Depends(require_portal_admin_or_hr),
    service: NotificationAdminService = Depends(get_notification_admin_service),
) -> AdminNotificationListResponse:
    # Query datumi ne prolaze kroz pydantic validator: proveravamo naive/red ovde
    # i vracamo standardni VALIDATION_ERROR (ne 500).
    if (datum_od is not None and datum_od.tzinfo is not None) or (
        datum_do is not None and datum_do.tzinfo is not None
    ):
        raise ValidationBusinessError("Datum filtera mora biti bez vremenske zone (bez Z ili offseta).")
    if datum_od is not None and datum_do is not None and datum_do < datum_od:
        raise ValidationBusinessError("datum_do ne sme biti pre datum_od.")
    result = service.list_notifications(
        _normalize_status_filter(status_filter),
        _normalize_category_filter(category),
        datum_od,
        datum_do,
        page,
        page_size,
    )
    return AdminNotificationListResponse(
        items=[AdminNotificationListItem(**it) for it in result["items"]],
        total=result["total"],
        page=result["page"],
        page_size=result["page_size"],
    )


@router.post(
    "/notifications",
    response_model=AdminNotificationDetailResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_notification(
    payload: NotificationDraftInput,
    actor: Korisnik = Depends(require_portal_admin_or_hr),
    service: NotificationAdminService = Depends(get_notification_admin_service),
) -> AdminNotificationDetailResponse:
    return AdminNotificationDetailResponse(**service.create(actor, payload))


@router.get("/notifications/{notification_id}", response_model=AdminNotificationDetailResponse)
def get_notification(
    notification_id: int,
    actor: Korisnik = Depends(require_portal_admin_or_hr),
    service: NotificationAdminService = Depends(get_notification_admin_service),
) -> AdminNotificationDetailResponse:
    return AdminNotificationDetailResponse(**service.get_detail(notification_id))


@router.put("/notifications/{notification_id}", response_model=AdminNotificationDetailResponse)
def update_notification(
    notification_id: int,
    payload: NotificationDraftInput,
    actor: Korisnik = Depends(require_portal_admin_or_hr),
    service: NotificationAdminService = Depends(get_notification_admin_service),
) -> AdminNotificationDetailResponse:
    return AdminNotificationDetailResponse(**service.update(actor, notification_id, payload))


@router.patch(
    "/notifications/{notification_id}/status", response_model=AdminNotificationDetailResponse
)
def change_status(
    notification_id: int,
    payload: AdminNotificationStatusRequest,
    actor: Korisnik = Depends(require_portal_admin_or_hr),
    service: NotificationAdminService = Depends(get_notification_admin_service),
) -> AdminNotificationDetailResponse:
    return AdminNotificationDetailResponse(
        **service.change_status(actor, notification_id, payload.status, payload.datum_isteka)
    )


@router.get(
    "/notifications/{notification_id}/stats", response_model=AdminNotificationStatsResponse
)
def notification_stats(
    notification_id: int,
    actor: Korisnik = Depends(require_portal_admin_or_hr),
    service: NotificationAdminService = Depends(get_notification_admin_service),
) -> AdminNotificationStatsResponse:
    return AdminNotificationStatsResponse(**service.get_stats(notification_id))
