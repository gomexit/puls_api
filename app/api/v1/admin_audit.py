import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.exceptions import ValidationBusinessError
from app.db.session import get_db
from app.dependencies.portal_auth import require_portal_admin_or_hr
from app.models.korisnik import Korisnik
from app.schemas.admin_audit import (
    AdminAuditLogDetailResponse,
    AdminAuditLogItemOut,
    AdminAuditLogListResponse,
)
from app.services.admin_audit_service import AdminAuditService

router = APIRouter(prefix="/admin/audit-logs", tags=["Admin Audit Log"])

PAGE_SIZE_DEFAULT = 20
PAGE_SIZE_MAX = 100
PLATNI_BROJ_MAX = 30
SIFRA_AKCIJE_MAX = 100
TIP_ENTITETA_MAX = 100
ENTITET_ID_MAX = 50
IZVOR_MAX = 20


def get_admin_audit_service(db: Session = Depends(get_db)) -> AdminAuditService:
    return AdminAuditService(db)


def _normalize_filter(
    value: str | None, max_len: int, label: str, *, upper: bool = False
) -> str | None:
    """Trim (+ upper ako trazeno); prazno posle trimovanja ili predugacko -> 422."""
    if value is None:
        return None
    v = value.strip()
    if not v:
        raise ValidationBusinessError(f"{label} ne sme biti prazan.")
    if len(v) > max_len:
        raise ValidationBusinessError(f"{label} je predugačak.")
    return v.upper() if upper else v


def _validate_naive_range(
    datum_od: datetime.datetime | None, datum_do: datetime.datetime | None
) -> None:
    if (datum_od is not None and datum_od.tzinfo is not None) or (
        datum_do is not None and datum_do.tzinfo is not None
    ):
        raise ValidationBusinessError("Datum filtera mora biti bez vremenske zone (bez Z ili offseta).")
    if datum_od is not None and datum_do is not None and datum_do < datum_od:
        raise ValidationBusinessError("datum_do ne sme biti pre datum_od.")


@router.get("", response_model=AdminAuditLogListResponse)
def list_audit_logs(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=PAGE_SIZE_DEFAULT, ge=1, le=PAGE_SIZE_MAX),
    platni_broj: str | None = Query(default=None),
    sifra_akcije: str | None = Query(default=None),
    tip_entiteta: str | None = Query(default=None),
    entitet_id: str | None = Query(default=None),
    izvor: str | None = Query(default=None),
    datum_od: datetime.datetime | None = Query(default=None),
    datum_do: datetime.datetime | None = Query(default=None),
    _: Korisnik = Depends(require_portal_admin_or_hr),
    service: AdminAuditService = Depends(get_admin_audit_service),
) -> AdminAuditLogListResponse:
    _validate_naive_range(datum_od, datum_do)
    platni_broj = _normalize_filter(platni_broj, PLATNI_BROJ_MAX, "platni_broj")
    sifra_akcije = _normalize_filter(sifra_akcije, SIFRA_AKCIJE_MAX, "sifra_akcije", upper=True)
    tip_entiteta = _normalize_filter(tip_entiteta, TIP_ENTITETA_MAX, "tip_entiteta", upper=True)
    entitet_id = _normalize_filter(entitet_id, ENTITET_ID_MAX, "entitet_id")
    izvor = _normalize_filter(izvor, IZVOR_MAX, "izvor", upper=True)
    result = service.list_logs(
        page, page_size, platni_broj, sifra_akcije, tip_entiteta, entitet_id, izvor, datum_od, datum_do
    )
    return AdminAuditLogListResponse(
        items=[AdminAuditLogItemOut(**item) for item in result["items"]],
        page=result["page"],
        page_size=result["page_size"],
        total=result["total"],
        has_more=result["has_more"],
    )


@router.get("/{audit_id}", response_model=AdminAuditLogDetailResponse)
def get_audit_log(
    audit_id: int,
    _: Korisnik = Depends(require_portal_admin_or_hr),
    service: AdminAuditService = Depends(get_admin_audit_service),
) -> AdminAuditLogDetailResponse:
    return AdminAuditLogDetailResponse(**service.get_log(audit_id))
