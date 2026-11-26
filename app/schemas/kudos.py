import datetime

from pydantic import BaseModel, Field

POVOD_ENUM = ["POMOC", "TIMSKI_RAD", "LJUBAZNOST"]
STATUS_ENUM = ["OBJAVLJENA", "NA_PROVERI", "SAKRIVENA"]


class KudosPersonOut(BaseModel):
    id: int
    ime: str
    prezime: str
    orgjed_naziv: str | None = Field(description="Naziv primarne org. jedinice; null ako nije poznat.")


class KudosOut(BaseModel):
    id: int
    posiljalac: KudosPersonOut
    primalac: KudosPersonOut
    povod: str = Field(json_schema_extra={"enum": POVOD_ENUM})
    povod_naziv: str
    tekst: str
    datum_kreiranja: datetime.datetime
    moja: bool = Field(description="true = ja sam poslao ili primio.")
    mogu_prijaviti: bool = Field(description="false za moju poslatu zahvalnicu.")
    status: str | None = Field(
        default=None, description="Samo kod poslatih: OBJAVLJENA, NA_PROVERI ili SAKRIVENA.",
        json_schema_extra={"enum": STATUS_ENUM},
    )


class KudosFeedResponse(BaseModel):
    opseg: str = Field(json_schema_extra={"enum": ["prodavnica", "svi"]})
    items: list[KudosOut]
    ima_jos: bool


class KudosMineResponse(BaseModel):
    smer: str = Field(json_schema_extra={"enum": ["primljene", "poslate"]})
    items: list[KudosOut]
    ima_jos: bool


class KudosCreateRequest(BaseModel):
    primalac_id: int = Field(gt=0, description="`id` kolege iz /colleagues/search.")
    povod: str = Field(json_schema_extra={"enum": POVOD_ENUM})
    tekst: str = Field(min_length=1, max_length=400, description="Najviše 280 znakova posle čišćenja razmaka.")


class KudosReportRequest(BaseModel):
    razlog: str | None = Field(default=None, max_length=400)


class KudosReportResponse(BaseModel):
    prijavljena: bool


class ColleagueOut(BaseModel):
    id: int
    ime: str
    prezime: str
    orgjed_naziv: str | None


class ColleagueSearchResponse(BaseModel):
    items: list[ColleagueOut]


class AdminKudosReportOut(BaseModel):
    razlog: str | None
    datum_kreiranja: datetime.datetime


class AdminKudosOut(BaseModel):
    id: int
    posiljalac: KudosPersonOut
    primalac: KudosPersonOut
    povod: str
    povod_naziv: str
    tekst: str
    datum_kreiranja: datetime.datetime
    status: str = Field(json_schema_extra={"enum": STATUS_ENUM})
    broj_prijava: int
    proverena: bool = Field(description="true = HR je pregledao; nove prijave je više ne sklanjaju.")
    datum_izmene: datetime.datetime | None
    prijave: list[AdminKudosReportOut] | None = Field(default=None, description="Samo u detaljima; bez imena.")


class AdminKudosListResponse(BaseModel):
    items: list[AdminKudosOut]
    total: int
    page: int
    page_size: int
