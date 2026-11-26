import datetime
from typing import Annotated

from pydantic import BaseModel, BeforeValidator, Field, field_validator

from app.models.kviz import (
    KVIZ_CILJ_TIPOVI,
    KVIZ_STATUSI,
    MAX_OPCIJA,
    MAX_PITANJA,
    MIN_OPCIJA,
    POKUSAJ_STATUSI,
    TRAJANJE_MAX_SEKUNDI,
    TRAJANJE_MIN_SEKUNDI,
    TRAJANJE_PODRAZUMEVANO,
)
from app.schemas.survey import naive_only
from app.services.onboarding_pdf import strip_text, strip_text_or_none


def _text(max_len: int):
    return Annotated[str, BeforeValidator(strip_text), Field(min_length=1, max_length=max_len)]


OptText = Annotated[str | None, BeforeValidator(strip_text_or_none), Field(default=None, max_length=1000)]

STATUS_DESCRIPTION = (
    "Status kviza:\n"
    "- **DRAFT** - u pripremi; sve se menja (pitanja i ciljevi se zamenjuju u celini).\n"
    "- **OBJAVLJEN** - zaposleni ga vide od `datum_od` do `datum_do`. Menjaju se samo `naziv`, "
    "`opis` i produženje `datum_do`.\n"
    "- **ARHIVIRAN** - povučen; zaposleni ga više ne vide. Terminalan status."
)


# ================================================================ kategorije
class QuizCategoryOut(BaseModel):
    sifra: str
    naziv: str
    redosled: int
    aktivna: bool
    kreirao_platni_broj: str
    izmenio_platni_broj: str
    datum_kreiranja: datetime.datetime
    datum_izmene: datetime.datetime


class QuizCategoryListResponse(BaseModel):
    items: list[QuizCategoryOut]


class QuizCategoryCreateRequest(BaseModel):
    sifra: str = Field(min_length=1, max_length=30, description="Velika slova, cifre i _ (npr. ASORTIMAN).")
    naziv: _text(100)
    redosled: int = Field(default=0, ge=0, le=99999)
    aktivna: bool = True


class QuizCategoryUpdateRequest(BaseModel):
    naziv: _text(100)
    redosled: int = Field(default=0, ge=0, le=99999)
    aktivna: bool = True


# ================================================================== kvizovi
class QuizTargetIn(BaseModel):
    tip: str = Field(description="ORGJED ili PLATNI_BROJ.", json_schema_extra={"enum": list(KVIZ_CILJ_TIPOVI)})
    vrednost: _text(50)


class QuizOptionIn(BaseModel):
    tekst: _text(200)
    tacna: bool = False


class QuizQuestionIn(BaseModel):
    tekst: _text(500)
    kategorija_sifra: str = Field(min_length=1, max_length=30)
    slika_id: int | None = Field(default=None, description="ID AKTIVNE slike iz biblioteke slika (opciono).")
    objasnjenje: _text(500) = Field(description="Prikazuje se zaposlenom posle odgovora.")
    opcije: list[QuizOptionIn] = Field(min_length=MIN_OPCIJA, max_length=MAX_OPCIJA)


class _QuizDates(BaseModel):
    @field_validator("datum_od", "datum_do", check_fields=False)
    @classmethod
    def _naive(cls, v):
        return naive_only(v) if v is not None else v


class QuizCreateRequest(_QuizDates):
    naziv: _text(200)
    opis: OptText
    datum_od: datetime.datetime = Field(description="Lokalno vreme, bez vremenske zone.")
    datum_do: datetime.datetime = Field(description="Lokalno vreme, bez vremenske zone. Mora biti posle datum_od.")
    trajanje_sekundi: int = Field(default=TRAJANJE_PODRAZUMEVANO, ge=TRAJANJE_MIN_SEKUNDI, le=TRAJANJE_MAX_SEKUNDI)
    ciljevi: list[QuizTargetIn] = Field(default_factory=list, description="Prazno = svi zaposleni.")
    pitanja: list[QuizQuestionIn] = Field(default_factory=list, max_length=MAX_PITANJA)


class QuizUpdateRequest(_QuizDates):
    """Polja koja se ne pošalju ostaju nepromenjena. Za OBJAVLJEN kviz dozvoljeni su samo
    `naziv`, `opis` i `datum_do` (samo produženje); ostala polja daju 409 `QUIZ_LOCKED`."""

    naziv: _text(200) | None = None
    opis: OptText
    datum_od: datetime.datetime | None = None
    datum_do: datetime.datetime | None = None
    trajanje_sekundi: int | None = Field(default=None, ge=TRAJANJE_MIN_SEKUNDI, le=TRAJANJE_MAX_SEKUNDI)
    ciljevi: list[QuizTargetIn] | None = Field(default=None, description="Ako se pošalje, zamenjuje sve ciljeve.")
    pitanja: list[QuizQuestionIn] | None = Field(
        default=None, max_length=MAX_PITANJA, description="Ako se pošalje, zamenjuje sva pitanja."
    )


class QuizStatusRequest(BaseModel):
    status: str = Field(description="OBJAVLJEN ili ARHIVIRAN.", json_schema_extra={"enum": list(KVIZ_STATUSI)})


class QuizTargetOut(BaseModel):
    tip: str
    vrednost: str


class AdminQuizOptionOut(BaseModel):
    id: int
    redosled: int
    tekst: str
    tacna: bool


class AdminQuizQuestionOut(BaseModel):
    id: int
    redosled: int
    tekst: str
    kategorija_sifra: str
    slika_id: int | None
    slika_url: str | None
    objasnjenje: str
    opcije: list[AdminQuizOptionOut]


class AdminQuizSummaryOut(BaseModel):
    id: int
    naziv: str
    opis: str | None
    datum_od: datetime.datetime
    datum_do: datetime.datetime
    trajanje_sekundi: int
    status: str = Field(json_schema_extra={"enum": list(KVIZ_STATUSI)})
    broj_pitanja: int
    kreirao_platni_broj: str
    izmenio_platni_broj: str
    datum_objave: datetime.datetime | None
    datum_kreiranja: datetime.datetime
    datum_izmene: datetime.datetime


class AdminQuizOut(AdminQuizSummaryOut):
    ciljevi: list[QuizTargetOut]
    pitanja: list[AdminQuizQuestionOut]


class AdminQuizListResponse(BaseModel):
    items: list[AdminQuizSummaryOut]
    total: int
    page: int
    page_size: int


class QuizOrgjedResultOut(BaseModel):
    orgjed_sifra: str | None
    broj_zavrsenih: int
    prosek_tacnih: float | None


class QuizQuestionResultOut(BaseModel):
    pitanje_id: int
    redosled: int
    tekst: str
    broj_odgovora: int
    broj_tacnih: int
    procenat_tacnih: float | None


class AdminQuizResultsOut(BaseModel):
    kviz_id: int
    naziv: str
    status: str
    broj_pitanja: int
    broj_pokusaja: int
    broj_zavrsenih: int
    prosek_tacnih: float | None
    prosek_trajanja_ms: int | None
    po_orgjed: list[QuizOrgjedResultOut]
    po_pitanju: list[QuizQuestionResultOut]


# ================================================================ zaposleni
class QuizCurrentQuizOut(BaseModel):
    id: int
    naziv: str
    opis: str | None
    datum_od: datetime.datetime
    datum_do: datetime.datetime
    trajanje_sekundi: int
    broj_pitanja: int


class QuizMyAttemptOut(BaseModel):
    id: int
    status: str = Field(json_schema_extra={"enum": list(POKUSAJ_STATUSI)})
    broj_tacnih: int


class QuizCurrentResponse(BaseModel):
    kviz: QuizCurrentQuizOut | None = Field(description="null = trenutno nema kviza za mene.")
    pokusaj: QuizMyAttemptOut | None = Field(description="null = još nisam počeo.")


class QuizPlayOptionOut(BaseModel):
    id: int
    tekst: str


class QuizGivenAnswerOut(BaseModel):
    opcija_id: int
    tacan: bool
    tacna_opcija_id: int | None
    objasnjenje: str


class QuizPlayQuestionOut(BaseModel):
    id: int
    redosled: int
    tekst: str
    kategorija: str
    slika_url: str | None
    opcije: list[QuizPlayOptionOut]
    odgovor: QuizGivenAnswerOut | None = Field(description="Popunjeno samo za već odgovorena pitanja.")


class QuizPlayResponse(BaseModel):
    pokusaj_id: int
    kviz_id: int
    naziv: str
    status: str
    trajanje_sekundi: int
    datum_pocetka: datetime.datetime
    rok: datetime.datetime = Field(description="Serversko vreme do kada se odgovara.")
    preostalo_sekundi: int = Field(description="Koliko je ostalo po serveru; aplikacija odbrojava od ove vrednosti.")
    broj_pitanja: int
    broj_tacnih: int
    pitanja: list[QuizPlayQuestionOut]


class QuizAnswerRequest(BaseModel):
    pitanje_id: int
    opcija_id: int


class QuizAnswerResponse(BaseModel):
    pitanje_id: int
    opcija_id: int
    tacan: bool
    tacna_opcija_id: int
    objasnjenje: str
    broj_tacnih: int
    broj_odgovorenih: int
    broj_pitanja: int
    zavrsen: bool


class QuizResultOptionOut(BaseModel):
    id: int
    tekst: str
    tacna: bool


class QuizResultQuestionOut(BaseModel):
    id: int
    redosled: int
    tekst: str
    kategorija: str
    slika_url: str | None
    opcije: list[QuizResultOptionOut]
    moja_opcija_id: int | None
    tacan: bool
    objasnjenje: str


class QuizResultResponse(BaseModel):
    pokusaj_id: int
    kviz_id: int
    naziv: str
    status: str
    broj_tacnih: int
    broj_pitanja: int
    trajanje_ms: int | None
    datum_pocetka: datetime.datetime
    datum_zavrsetka: datetime.datetime | None
    prosek_orgjed: float | None = Field(description="Prosek tačnih u mojoj org. jedinici (od 3 učesnika).")
    broj_ucesnika_orgjed: int | None
    pitanja: list[QuizResultQuestionOut]
