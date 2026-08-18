import datetime
from decimal import Decimal

from pydantic import BaseModel, field_validator

from app.models.ideja import IDEJA_STATUSI

NASLOV_MAX = 200
OPIS_MAX = 4000


def _validate_naslov(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("Naslov je obavezan.")
    if len(value) > NASLOV_MAX:
        raise ValueError(f"Naslov može imati najviše {NASLOV_MAX} karaktera.")
    return value


def _validate_opis(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("Opis je obavezan.")
    if len(value) > OPIS_MAX:
        raise ValueError(f"Opis može imati najviše {OPIS_MAX} karaktera.")
    return value


# ---------------------------------------------------------------------------
# Employee (Ideas)
# ---------------------------------------------------------------------------
class IdeaCreateRequest(BaseModel):
    naslov: str
    opis: str

    @field_validator("naslov")
    @classmethod
    def _naslov(cls, v: str) -> str:
        return _validate_naslov(v)

    @field_validator("opis")
    @classmethod
    def _opis(cls, v: str) -> str:
        return _validate_opis(v)


class IdeaUpdateRequest(IdeaCreateRequest):
    pass


class IdeaResponse(BaseModel):
    """Employee DTO - namerno NE sadrzi interne ocene ni AI analizu."""

    id: int
    ciklus_id: int
    naslov: str
    opis: str
    status: str
    datum_kreiranja: datetime.datetime | None = None
    datum_izmene: datetime.datetime | None = None


class MyIdeasResponse(BaseModel):
    items: list[IdeaResponse]


class CycleSummary(BaseModel):
    id: int
    naziv: str
    datum_pocetka: datetime.datetime
    datum_zavrsetka: datetime.datetime
    status: str


class CurrentCycleResponse(BaseModel):
    cycle: CycleSummary | None = None
    submission_open: bool
    max_ideas: int
    used_ideas: int
    remaining_ideas: int


class TopIdeaItem(BaseModel):
    id: int
    rang: int
    ime: str
    prezime: str
    naslov: str
    status: str


class TopIdeasResponse(BaseModel):
    items: list[TopIdeaItem]


# ---------------------------------------------------------------------------
# Admin / HR
# ---------------------------------------------------------------------------
class AdminCycleCreateRequest(BaseModel):
    naziv: str
    datum_pocetka: datetime.datetime
    datum_zavrsetka: datetime.datetime

    @field_validator("naziv")
    @classmethod
    def _naziv(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Naziv je obavezan.")
        if len(v) > 200:
            raise ValueError("Naziv može imati najviše 200 karaktera.")
        return v


class AdminCyclePatchRequest(BaseModel):
    status: str

    @field_validator("status")
    @classmethod
    def _status(cls, v: str) -> str:
        from app.models.idea_ciklus import CIKLUS_STATUSI

        v = v.strip().upper()
        if v not in CIKLUS_STATUSI:
            raise ValueError("Nepoznat status ciklusa.")
        return v


class AdminCycleResponse(BaseModel):
    id: int
    naziv: str
    datum_pocetka: datetime.datetime
    datum_zavrsetka: datetime.datetime
    status: str
    datum_kreiranja: datetime.datetime | None = None
    datum_izmene: datetime.datetime | None = None


class AdminCycleListResponse(BaseModel):
    items: list[AdminCycleResponse]


class AdminIdeaResponse(BaseModel):
    """Admin/HR DTO - sadrzi sve podatke ideje ukljucujuci autora i ocene."""

    id: int
    korisnik_id: int
    ciklus_id: int
    platni_broj: str
    ime_autora: str
    prezime_autora: str
    orgjed_sifra: str | None = None
    naslov: str
    opis: str
    status: str
    hr_ocena: int | None = None
    ai_ocena: Decimal | None = None
    konacna_ocena: Decimal | None = None
    datum_kreiranja: datetime.datetime | None = None
    datum_izmene: datetime.datetime | None = None


class AdminIdeaListResponse(BaseModel):
    items: list[AdminIdeaResponse]
    total: int
    page: int
    page_size: int


class AdminIdeaStatusRequest(BaseModel):
    status: str

    @field_validator("status")
    @classmethod
    def _status(cls, v: str) -> str:
        v = v.strip().upper()
        if v not in IDEJA_STATUSI:
            raise ValueError("Nepoznat status ideje.")
        return v


class AdminIdeaHrScoreRequest(BaseModel):
    hr_ocena: int

    @field_validator("hr_ocena")
    @classmethod
    def _hr_ocena(cls, v: int) -> int:
        if v < 1 or v > 10:
            raise ValueError("HR ocena mora biti između 1 i 10.")
        return v