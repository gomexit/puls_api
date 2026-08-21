import datetime

from pydantic import BaseModel, Field


class AdminUserOut(BaseModel):
    id: int
    platni_broj: str
    ime: str
    prezime: str
    broj_telefona: str | None = None
    status_zaposlenja: str
    status_naloga: str
    zakljucan: bool
    broj_neuspesnih_prijava: int
    obavezna_promena_lozinke: bool
    telefon_potvrdjen: bool
    datum_poslednje_prijave: datetime.datetime | None = None
    datum_sinhronizacije: datetime.datetime | None = None
    orgjed_sifra: str | None = None
    radno_mesto_sifra: str | None = None
    uloge: list[str] = Field(default_factory=list)


class AdminUserListResponse(BaseModel):
    items: list[AdminUserOut]
    page: int
    page_size: int
    total: int
    has_more: bool


class AdminUserPasswordResetResponse(BaseModel):
    message: str
