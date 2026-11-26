import datetime

from pydantic import BaseModel, Field

STATUS_ENUM = ["POSLATO", "ODGOVORENO", "ZATVORENO"]
AUTOR_ENUM = ["ZAPOSLENI", "HR"]


# ================================================================ zaposleni
class HrCategoryOut(BaseModel):
    sifra: str
    naziv: str


class HrCategoryListResponse(BaseModel):
    items: list[HrCategoryOut]


class HrFaqOut(BaseModel):
    id: int
    kategorija_sifra: str
    kategorija_naziv: str
    pitanje: str
    odgovor: str


class HrFaqListResponse(BaseModel):
    items: list[HrFaqOut]


class HrMessageOut(BaseModel):
    autor: str = Field(description="ZAPOSLENI (ja) ili HR.", json_schema_extra={"enum": AUTOR_ENUM})
    tekst: str
    datum_kreiranja: datetime.datetime


class HrQuestionSummaryOut(BaseModel):
    id: int
    kategorija_sifra: str
    kategorija_naziv: str
    pregled: str = Field(description="Početak pitanja (do 120 znakova).")
    status: str = Field(json_schema_extra={"enum": STATUS_ENUM})
    nov_odgovor: bool = Field(description="true = HR je odgovorio, a ja još nisam otvorio pitanje.")
    datum_kreiranja: datetime.datetime
    datum_izmene: datetime.datetime


class HrQuestionListResponse(BaseModel):
    items: list[HrQuestionSummaryOut]
    ima_jos: bool


class HrQuestionOut(BaseModel):
    id: int
    kategorija_sifra: str
    kategorija_naziv: str
    status: str = Field(json_schema_extra={"enum": STATUS_ENUM})
    mogu_dopuniti: bool = Field(description="true = smem da pošaljem jedno dopunsko pitanje.")
    datum_kreiranja: datetime.datetime
    poruke: list[HrMessageOut]


class HrQuestionCreateRequest(BaseModel):
    kategorija_sifra: str = Field(min_length=1, max_length=30, description="`sifra` iz /hr-questions/categories.")
    tekst: str = Field(min_length=1, max_length=1500, description="Najviše 1000 znakova posle čišćenja razmaka.")


class HrFollowUpRequest(BaseModel):
    tekst: str = Field(min_length=1, max_length=1500, description="Najviše 1000 znakova.")


# ==================================================================== admin
class AdminHrCategoryOut(BaseModel):
    sifra: str
    naziv: str
    redosled: int
    aktivna: bool
    kreirao_platni_broj: str
    izmenio_platni_broj: str
    datum_kreiranja: datetime.datetime
    datum_izmene: datetime.datetime


class AdminHrCategoryListResponse(BaseModel):
    items: list[AdminHrCategoryOut]


class AdminHrCategoryCreateRequest(BaseModel):
    sifra: str = Field(min_length=1, max_length=30, description="Velika slova, cifre i _ (npr. ODMOR).")
    naziv: str = Field(min_length=1, max_length=100)
    redosled: int = Field(default=0, ge=0, le=99999)
    aktivna: bool = True


class AdminHrCategoryUpdateRequest(BaseModel):
    naziv: str = Field(min_length=1, max_length=100)
    redosled: int = Field(default=0, ge=0, le=99999)
    aktivna: bool = True


class AdminHrEmployeeOut(BaseModel):
    id: int
    ime: str
    prezime: str
    platni_broj: str | None
    orgjed_naziv: str | None


class AdminHrMessageOut(BaseModel):
    autor: str = Field(json_schema_extra={"enum": AUTOR_ENUM})
    autor_ime: str
    tekst: str
    datum_kreiranja: datetime.datetime


class AdminHrQuestionOut(BaseModel):
    id: int
    zaposleni: AdminHrEmployeeOut
    kategorija_sifra: str
    kategorija_naziv: str
    status: str = Field(json_schema_extra={"enum": STATUS_ENUM})
    dopuna_poslata: bool = Field(description="true = zaposleni je iskoristio dopunsko pitanje.")
    odgovor_procitan: bool
    datum_kreiranja: datetime.datetime
    datum_izmene: datetime.datetime
    datum_odgovora: datetime.datetime | None
    pregled: str | None = Field(default=None, description="Samo u listi.")
    poruke: list[AdminHrMessageOut] | None = Field(default=None, description="Samo u detaljima.")


class AdminHrQuestionListResponse(BaseModel):
    items: list[AdminHrQuestionOut]
    total: int
    page: int
    page_size: int


class AdminHrAnswerRequest(BaseModel):
    tekst: str = Field(min_length=1, max_length=2500, description="Najviše 2000 znakova.")


class AdminHrFaqOut(BaseModel):
    id: int
    kategorija_sifra: str
    kategorija_naziv: str
    pitanje: str
    odgovor: str
    redosled: int
    aktivno: bool
    izvor_pitanje_id: int | None
    datum_kreiranja: datetime.datetime
    datum_izmene: datetime.datetime


class AdminHrFaqListResponse(BaseModel):
    items: list[AdminHrFaqOut]


class AdminHrFaqUpdateRequest(BaseModel):
    kategorija_sifra: str = Field(min_length=1, max_length=30)
    pitanje: str = Field(min_length=1, max_length=1500, description="Najviše 1000 znakova, bez imena.")
    odgovor: str = Field(min_length=1, max_length=2500, description="Najviše 2000 znakova.")
    redosled: int = Field(default=0, ge=0, le=99999)
    aktivno: bool = True


class AdminHrFaqCreateRequest(AdminHrFaqUpdateRequest):
    izvor_pitanje_id: int | None = Field(default=None, description="Pitanje iz kog je nastalo (samo za portal).")
