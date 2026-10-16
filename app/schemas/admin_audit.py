import datetime

from typing import Literal

from pydantic import BaseModel, Field


class AdminAuditLogItemOut(BaseModel):
    id: int
    korisnik_id: int | None = None
    platni_broj: str | None = None
    sifra_akcije: str
    tip_entiteta: str | None = None
    entitet_id: str | None = None
    izvor: str
    datum_kreiranja: datetime.datetime | None = None


class AdminAuditLogListResponse(BaseModel):
    items: list[AdminAuditLogItemOut]
    page: int
    page_size: int
    total: int
    has_more: bool
    sort_by: str = Field(description="Kolona po kojoj je lista stvarno sortirana.")
    sort_dir: Literal["asc", "desc"] = Field(description="Smer stvarnog sortiranja.")


class AdminAuditLogDetailResponse(AdminAuditLogItemOut):
    detalji: str | None = None
    ip_adresa: str | None = None
    korisnicki_agent: str | None = None
