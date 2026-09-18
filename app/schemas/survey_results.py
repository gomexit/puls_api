import datetime

from pydantic import BaseModel, Field

# ===========================================================================
# ADMIN - opsta statistika + statistika po pitanjima (GET /statistics)
# ===========================================================================


class OdzivOut(BaseModel):
    ukupno_ciljanih: int
    nije_zapocelo: int
    u_toku: int
    predato: int
    nije_predato: int
    procenat_odziva: float


class OpcijaStatOut(BaseModel):
    opcija_id: int
    tekst: str
    broj_izbora: int
    procenat: float


class BooleanStatValueOut(BaseModel):
    broj: int
    procenat: float


class RatingRaspodelaItemOut(BaseModel):
    vrednost: int
    broj: int
    procenat: float


class PitanjeStatOut(BaseModel):
    pitanje_id: int
    sekcija_id: int
    sekcija_naziv: str
    tekst: str
    tip_pitanja: str
    komponenta: str | None = None
    sekcija_redosled: int
    pitanje_redosled: int
    broj_odgovora: int
    # SINGLE_CHOICE / DROPDOWN / MULTI_CHOICE
    opcije: list[OpcijaStatOut] | None = None
    # BOOLEAN
    da: BooleanStatValueOut | None = None
    ne: BooleanStatValueOut | None = None
    # RATING_1_5 / RATING_1_10
    prosek: float | None = None
    medijana: float | None = None
    minimum: int | None = None
    maksimum: int | None = None
    raspodela: list[RatingRaspodelaItemOut] | None = None
    # TEXT: samo zajednicka polja (broj_odgovora) - sirovi tekst se NIKADA ne vraca ovde.


class SurveyStatisticsResponse(BaseModel):
    survey_id: int
    naziv: str
    anonimna: bool
    status: str
    datum_pocetka: datetime.datetime
    datum_zavrsetka: datetime.datetime
    odziv: OdzivOut
    pitanja: list[PitanjeStatOut]


# ===========================================================================
# ADMIN - detaljni odgovori, samo neanonimne ankete (GET /responses)
# ===========================================================================


class KorisnikInfoOut(BaseModel):
    korisnik_id: int
    platni_broj: str
    ime: str
    prezime: str
    # NAPOMENA: dolazi iz TRENUTNOG PULS_KORISNIK_RASPOREDI stanja (nema istorijski
    # snapshot org. jedinice/radnog mesta u trenutku predaje - vidi izvestaj).
    orgjed_sifra: str | None = None
    radno_mesto_sifra: str | None = None


class OpcijaDetailOut(BaseModel):
    opcija_id: int
    tekst: str


class OdgovorDetailOut(BaseModel):
    pitanje_id: int
    tip_pitanja: str
    tekst: str | None = None
    broj: int | None = None
    logicka: bool | None = None
    opcije: list[OpcijaDetailOut] = Field(default_factory=list)


class ResponseItemOut(BaseModel):
    korisnik: KorisnikInfoOut
    datum_predaje: datetime.datetime | None
    odgovori: list[OdgovorDetailOut]


class SurveyResponsesResponse(BaseModel):
    survey_id: int
    page: int
    page_size: int
    total: int
    has_more: bool
    items: list[ResponseItemOut]
