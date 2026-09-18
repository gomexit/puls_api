import datetime

from pydantic import BaseModel, Field, field_validator


def _non_blank(value: str) -> str:
    if value is None or value.strip() == "":
        raise ValueError("Vrednost ne sme biti prazna.")
    return value.strip()


def naive_only(value: datetime.datetime) -> datetime.datetime:
    """Ugovor za MVP: admin datumi moraju biti lokalni ISO-8601 bez Z/UTC offseta.
    Timezone-aware vrednost se odbija (nikad tiho ne menjamo znacenje vremena)."""
    if value.tzinfo is not None:
        raise ValueError("Datum mora biti lokalni, bez vremenske zone (bez Z ili offseta).")
    return value


def _opt_key(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    if value == "":
        raise ValueError("Ključ ne sme biti prazan kada je prosleđen.")
    return value

# ===========================================================================
# EMPLOYEE
# ===========================================================================


class SurveyListItem(BaseModel):
    id: int
    naziv: str
    tip: str
    tip_naziv: str
    anonimna: bool
    datum_pocetka: datetime.datetime
    datum_zavrsetka: datetime.datetime
    broj_pitanja: int
    moj_status: str


class SurveyListResponse(BaseModel):
    items: list[SurveyListItem]
    za_popunjavanje: int


class OpcijaOut(BaseModel):
    id: int
    tekst: str
    redosled: int


class UslovOut(BaseModel):
    pitanje_id: int
    operator: str
    vrednosti: list[str]


class PitanjeOut(BaseModel):
    id: int
    tekst: str
    tip: str
    # Familija UI kontrole + parametri iz PULS_ANKETA_TIPOVI_PITANJA - klijent crta
    # po `komponenta`, a `tip` ostaje sifra tipa (kompatibilnost sa starijim klijentima).
    komponenta: str | None = None
    min_vrednost: int | None = None
    max_vrednost: int | None = None
    obavezno: bool
    redosled: int
    opcije: list[OpcijaOut]
    uslov: UslovOut | None = None


class SekcijaOut(BaseModel):
    id: int
    naziv: str
    redosled: int
    pitanja: list[PitanjeOut]


class MojOdgovorOut(BaseModel):
    pitanje_id: int
    tekst: str | None = None
    broj: int | None = None
    logicka: bool | None = None
    opcija_ids: list[int] = Field(default_factory=list)


class SurveyDetailResponse(BaseModel):
    id: int
    naziv: str
    opis: str | None = None
    tip: str
    tip_naziv: str
    anonimna: bool
    datum_pocetka: datetime.datetime
    datum_zavrsetka: datetime.datetime
    moj_status: str
    datum_predaje: datetime.datetime | None = None
    odgovori_dostupni: bool
    sekcije: list[SekcijaOut]
    moji_odgovori: list[MojOdgovorOut]


class OdgovorIn(BaseModel):
    pitanje_id: int
    tekst: str | None = None
    broj: int | None = None
    logicka: bool | None = None
    opcija_ids: list[int] = Field(default_factory=list)


class DraftRequest(BaseModel):
    odgovori: list[OdgovorIn] = Field(default_factory=list)


class DraftResponse(BaseModel):
    message: str
    moj_status: str


class SubmitResponse(BaseModel):
    message: str
    moj_status: str
    datum_predaje: datetime.datetime


# ===========================================================================
# ADMIN - tipovi anketa
# ===========================================================================


class SurveyTypeCreateRequest(BaseModel):
    sifra: str = Field(min_length=1, max_length=50)
    naziv: str = Field(min_length=1, max_length=200)

    @field_validator("sifra", "naziv")
    @classmethod
    def _nb(cls, v: str) -> str:
        return _non_blank(v)


class SurveyTypePatchRequest(BaseModel):
    naziv: str | None = Field(default=None, max_length=200)
    aktivan: bool | None = None

    @field_validator("naziv")
    @classmethod
    def _nb_naziv(cls, v: str | None) -> str | None:
        # Kada je prosledjen, naziv ne sme biti prazan ni samo razmaci.
        return None if v is None else _non_blank(v)


class SurveyTypeResponse(BaseModel):
    sifra: str
    naziv: str
    aktivan: bool


class SurveyTypeListResponse(BaseModel):
    items: list[SurveyTypeResponse]


# ===========================================================================
# ADMIN - kreiranje/izmena ankete (privremeni kljucevi za uslove i opcije)
# ===========================================================================


class AdminOpcijaIn(BaseModel):
    kljuc: str | None = None  # privremeni identifikator za referenciranje iz uslova
    tekst: str = Field(min_length=1, max_length=500)
    redosled: int = Field(ge=1)

    @field_validator("tekst")
    @classmethod
    def _nb(cls, v: str) -> str:
        return _non_blank(v)

    @field_validator("kljuc")
    @classmethod
    def _k(cls, v: str | None) -> str | None:
        return _opt_key(v)


class AdminUslovIn(BaseModel):
    pitanje_kljuc: str  # kljuc kontrolnog pitanja
    operator: str
    vrednosti: list[str] = Field(default_factory=list)

    @field_validator("pitanje_kljuc")
    @classmethod
    def _pk(cls, v: str) -> str:
        return _non_blank(v)

    @field_validator("vrednosti")
    @classmethod
    def _vrednosti(cls, v: list[str]) -> list[str]:
        # Vrednosti idu u VARCHAR2(100) (kontrolisani tokeni); ne stripujemo jer
        # boolean/rating/option-id tokeni nemaju razmake, ali namecemo max duzinu.
        for item in v:
            if len(item) > 100:
                raise ValueError("Vrednost uslova može imati najviše 100 karaktera.")
        return v


class AdminPitanjeIn(BaseModel):
    kljuc: str | None = None
    tekst: str = Field(min_length=1)
    tip: str
    obavezno: bool = False
    redosled: int = Field(ge=1)
    opcije: list[AdminOpcijaIn] = Field(default_factory=list)
    uslov: AdminUslovIn | None = None

    @field_validator("tekst")
    @classmethod
    def _nb(cls, v: str) -> str:
        return _non_blank(v)

    @field_validator("kljuc")
    @classmethod
    def _k(cls, v: str | None) -> str | None:
        return _opt_key(v)


class AdminSekcijaIn(BaseModel):
    naziv: str = Field(min_length=1, max_length=200)
    redosled: int = Field(ge=1)
    pitanja: list[AdminPitanjeIn] = Field(default_factory=list)

    @field_validator("naziv")
    @classmethod
    def _nb(cls, v: str) -> str:
        return _non_blank(v)


class AdminCiljIn(BaseModel):
    tip_cilja: str
    vrednost: str | None = None

    @field_validator("vrednost")
    @classmethod
    def _vrednost(cls, v: str | None) -> str | None:
        # Normalizuj (strip) i sacuvaj normalizovanu vrednost; max VARCHAR2(100).
        if v is None:
            return None
        v = v.strip()
        if v == "":
            return None
        if len(v) > 100:
            raise ValueError("Vrednost cilja može imati najviše 100 karaktera.")
        return v


class AdminSurveyCreateRequest(BaseModel):
    naziv: str = Field(min_length=1, max_length=200)
    opis: str | None = None
    tip_sifra: str = Field(min_length=1, max_length=50)
    anonimna: bool = False
    datum_pocetka: datetime.datetime
    datum_zavrsetka: datetime.datetime
    sekcije: list[AdminSekcijaIn] = Field(default_factory=list)
    ciljevi: list[AdminCiljIn] = Field(default_factory=list)

    @field_validator("naziv", "tip_sifra")
    @classmethod
    def _nb(cls, v: str) -> str:
        return _non_blank(v)

    @field_validator("datum_pocetka", "datum_zavrsetka")
    @classmethod
    def _naive(cls, v: datetime.datetime) -> datetime.datetime:
        return naive_only(v)


class AdminSurveyUpdateRequest(AdminSurveyCreateRequest):
    pass


class AdminSurveyStatusRequest(BaseModel):
    status: str


class AdminSurveyExtendRequest(BaseModel):
    datum_zavrsetka: datetime.datetime

    @field_validator("datum_zavrsetka")
    @classmethod
    def _naive(cls, v: datetime.datetime) -> datetime.datetime:
        return naive_only(v)


# --- Admin izlazni DTO ---
class AdminUslovOut(BaseModel):
    pitanje_id: int
    operator: str
    vrednosti: list[str]


class AdminOpcijaOut(BaseModel):
    id: int
    tekst: str
    redosled: int


class QuestionTypeOut(BaseModel):
    sifra: str
    naziv: str
    komponenta: str
    min_vrednost: int | None = None
    max_vrednost: int | None = None


class QuestionTypeListResponse(BaseModel):
    items: list[QuestionTypeOut]


class AdminPitanjeOut(BaseModel):
    id: int
    tekst: str
    tip: str
    # Familija UI kontrole + parametri iz PULS_ANKETA_TIPOVI_PITANJA - klijent crta
    # po `komponenta`, a `tip` ostaje sifra tipa (kompatibilnost sa starijim klijentima).
    komponenta: str | None = None
    min_vrednost: int | None = None
    max_vrednost: int | None = None
    obavezno: bool
    redosled: int
    opcije: list[AdminOpcijaOut]
    uslov: AdminUslovOut | None = None


class AdminSekcijaOut(BaseModel):
    id: int
    naziv: str
    redosled: int
    pitanja: list[AdminPitanjeOut]


class AdminCiljOut(BaseModel):
    id: int
    tip_cilja: str
    vrednost: str | None = None


class AdminSurveyDetailResponse(BaseModel):
    id: int
    naziv: str
    opis: str | None = None
    tip: str
    anonimna: bool
    status: str
    datum_pocetka: datetime.datetime
    datum_zavrsetka: datetime.datetime
    sekcije: list[AdminSekcijaOut]
    ciljevi: list[AdminCiljOut]


class AdminSurveyListItem(BaseModel):
    id: int
    naziv: str
    tip: str
    status: str
    anonimna: bool
    datum_pocetka: datetime.datetime
    datum_zavrsetka: datetime.datetime
    broj_ciljanih: int
    broj_predatih: int
    procenat_odziva: float


class AdminSurveyListResponse(BaseModel):
    items: list[AdminSurveyListItem]
    total: int
    page: int
    page_size: int


class AdminSurveyCreatedResponse(BaseModel):
    id: int
    status: str