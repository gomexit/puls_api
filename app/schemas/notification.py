import datetime
import re
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.obavestenje import (
    AKCIJA_NONE,
    AKCIJA_TIPOVI,
    AKCIJE_SA_RESURSOM,
    AKCIJE_SA_URL,
    CILJEVI_BEZ_VREDNOSTI,
    CILJEVI_SA_VREDNOSCU,
    OBAVESTENJE_STATUS_ARCHIVED,
    OBAVESTENJE_STATUSI,
    TIPOVI_CILJA,
)

# Aplikacioni maksimum sadrzaja (NCLOB u bazi; ovde razuman limit protiv abuse-a).
SADRZAJ_MAX = 10_000
NASLOV_MAX = 200
KRATAK_TEKST_MAX = 500
KATEGORIJA_MAX = 50
URL_MAX = 1000
CILJ_VREDNOST_MAX = 100
KATEGORIJA_NAZIV_MAX = 100
REDOSLED_MAX = 1_000_000

_SIFRA_RE = re.compile(r"^[A-Z0-9_]+$")


def normalize_category_sifra(value: str) -> str:
    """Jedinstvena normalizacija/validacija sifre kategorije: trim, uppercase,
    1-50 karaktera, samo A-Z/0-9/underscore. Koristi je create/draft schema i router
    (path param + list filter). Baca ValueError (schema -> 422)."""
    v = (value or "").strip().upper()
    if not v or len(v) > KATEGORIJA_MAX:
        raise ValueError("Šifra kategorije mora imati 1-50 karaktera.")
    if not _SIFRA_RE.match(v):
        raise ValueError("Šifra sme sadržati samo A-Z, 0-9 i _.")
    return v


def naive_only(value: datetime.datetime) -> datetime.datetime:
    if value.tzinfo is not None:
        raise ValueError("Datum mora biti lokalni, bez vremenske zone (bez Z ili offseta).")
    return value


def _validate_https_url(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("URL ne sme biti prazan.")
    if len(value) > URL_MAX:
        raise ValueError(f"URL može imati najviše {URL_MAX} karaktera.")
    try:
        parsed = urlparse(value)
    except ValueError as exc:  # pragma: no cover - urlparse retko baca
        raise ValueError("URL nije validan.") from exc
    # Dozvoli iskljucivo https:// sa host-om. Odbij javascript:, file:, custom scheme, itd.
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError("Dozvoljeni su samo https:// URL-ovi.")
    return value


# ===========================================================================
# EMPLOYEE - izlazni ugovor (stabilan za Android Inbox)
# ===========================================================================
class NotificationCategoryOut(BaseModel):
    sifra: str
    naziv: str


class NotificationActionOut(BaseModel):
    tip: str
    resurs_id: int | None = None
    url: str | None = None


class NotificationListItem(BaseModel):
    id: int
    kategorija: NotificationCategoryOut
    naslov: str
    kratak_tekst: str
    datum_objave: datetime.datetime | None
    datum_isteka: datetime.datetime | None
    procitano: bool
    datum_citanja: datetime.datetime | None = None
    akcija: NotificationActionOut


class NotificationListResponse(BaseModel):
    items: list[NotificationListItem]
    page: int
    page_size: int
    total: int
    has_more: bool
    unread_count: int


class NotificationDetailResponse(NotificationListItem):
    sadrzaj: str


class UnreadCountResponse(BaseModel):
    unread_count: int


class MarkReadResponse(BaseModel):
    id: int
    procitano: bool
    datum_citanja: datetime.datetime | None = None
    unread_count: int


# ===========================================================================
# INTERNO - ulaz za publishing servis (koristi ga i buduci admin API)
# ===========================================================================
class NotificationTargetIn(BaseModel):
    tip_cilja: str
    vrednost: str | None = None

    @field_validator("tip_cilja")
    @classmethod
    def _tip(cls, v: str) -> str:
        v = v.strip()
        if v not in TIPOVI_CILJA:
            raise ValueError("Nepoznat tip cilja.")
        return v

    @field_validator("vrednost")
    @classmethod
    def _vrednost(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        if v == "":
            return None
        if len(v) > CILJ_VREDNOST_MAX:
            raise ValueError(f"Vrednost cilja može imati najviše {CILJ_VREDNOST_MAX} karaktera.")
        return v

    @model_validator(mode="after")
    def _cross(self) -> "NotificationTargetIn":
        if self.tip_cilja in CILJEVI_BEZ_VREDNOSTI and self.vrednost is not None:
            raise ValueError("SVI/CENTRALA/MALOPRODAJA ne smeju imati vrednost.")
        if self.tip_cilja in CILJEVI_SA_VREDNOSCU and not self.vrednost:
            raise ValueError("ORGJED/PLATNI_BROJ zahtevaju nepraznu vrednost.")
        return self


class NotificationDraftInput(BaseModel):
    """Ulaz za kreiranje DRAFT obavestenja. Sva polja se ovde field-level validiraju;
    postojanje/aktivnost kategorije i razresavanje ciljeva proverava publishing servis.

    NAPOMENA (autor): identitet autora se NE prima iz payload-a. KREIRAO_PLATNI_BROJ
    postavlja iskljucivo servis iz actor.platni_broj (ili NULL za sistemski dogadjaj).
    extra='forbid' odbija svako nepoznato polje (npr. lazni 'kreirao_platni_broj')."""

    model_config = ConfigDict(extra="forbid")

    kategorija_sifra: str = Field(min_length=1, max_length=KATEGORIJA_MAX)
    naslov: str = Field(min_length=1, max_length=NASLOV_MAX)
    kratak_tekst: str = Field(min_length=1, max_length=KRATAK_TEKST_MAX)
    sadrzaj: str = Field(min_length=1)
    akcija_tip: str = AKCIJA_NONE
    resurs_id: int | None = None
    akcija_url: str | None = None
    datum_isteka: datetime.datetime | None = None
    ciljevi: list[NotificationTargetIn] = Field(default_factory=list)

    @field_validator("kategorija_sifra")
    @classmethod
    def _kat(cls, v: str) -> str:
        return normalize_category_sifra(v)

    @field_validator("naslov", "kratak_tekst")
    @classmethod
    def _nb(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Vrednost ne sme biti prazna.")
        return v

    @field_validator("sadrzaj")
    @classmethod
    def _sadrzaj(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Sadržaj ne sme biti prazan.")
        if len(v) > SADRZAJ_MAX:
            raise ValueError(f"Sadržaj može imati najviše {SADRZAJ_MAX} karaktera.")
        return v

    @field_validator("akcija_tip")
    @classmethod
    def _akcija_tip(cls, v: str) -> str:
        v = v.strip()
        if v not in AKCIJA_TIPOVI:
            raise ValueError("Nepoznat tip akcije.")
        return v

    @field_validator("datum_isteka")
    @classmethod
    def _naive(cls, v: datetime.datetime | None) -> datetime.datetime | None:
        return None if v is None else naive_only(v)

    @model_validator(mode="after")
    def _action_and_targets(self) -> "NotificationDraftInput":
        # Pravila akcije (ogledalo CK_OBAV_AKCIJA_PODACI):
        if self.akcija_tip == AKCIJA_NONE:
            if self.resurs_id is not None or self.akcija_url is not None:
                raise ValueError("NONE akcija ne sme imati resurs_id ni url.")
        elif self.akcija_tip in AKCIJE_SA_RESURSOM:
            if self.resurs_id is None or self.akcija_url is not None:
                raise ValueError("SURVEY/IDEA akcija zahteva resurs_id i ne sme imati url.")
            # RESURS_ID mora biti pozitivan (ogledalo DDL CHECK-a RESURS_ID > 0).
            # NAPOMENA: postojanje konkretne ankete/ideje se NE proverava ovde - to
            # je ugovor admin/automatske integracije, ne ovog ulaznog modela.
            if self.resurs_id <= 0:
                raise ValueError("resurs_id mora biti pozitivan broj.")
        elif self.akcija_tip in AKCIJE_SA_URL:
            if self.akcija_url is None or self.resurs_id is not None:
                raise ValueError("URL akcija zahteva url i ne sme imati resurs_id.")
            self.akcija_url = _validate_https_url(self.akcija_url)

        # Ciljevi: neprazni i jedinstveni.
        if not self.ciljevi:
            raise ValueError("Ciljne grupe su obavezne.")
        seen: set[tuple[str, str | None]] = set()
        for c in self.ciljevi:
            key = (c.tip_cilja, c.vrednost)
            if key in seen:
                raise ValueError("Duplirani ciljevi nisu dozvoljeni.")
            seen.add(key)
        return self


# ===========================================================================
# ADMIN - kategorije
# ===========================================================================
class AdminNotificationCategoryOut(BaseModel):
    sifra: str
    naziv: str
    aktivna: bool
    redosled: int | None = None
    datum_kreiranja: datetime.datetime | None = None
    datum_izmene: datetime.datetime | None = None


class AdminNotificationCategoryListResponse(BaseModel):
    items: list[AdminNotificationCategoryOut]


class AdminNotificationCategoryCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sifra: str = Field(min_length=1, max_length=KATEGORIJA_MAX)
    naziv: str = Field(min_length=1, max_length=KATEGORIJA_NAZIV_MAX)
    aktivna: bool = True
    redosled: int | None = None

    @field_validator("sifra")
    @classmethod
    def _sifra(cls, v: str) -> str:
        return normalize_category_sifra(v)

    @field_validator("naziv")
    @classmethod
    def _naziv(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Naziv ne sme biti prazan.")
        return v

    @field_validator("redosled")
    @classmethod
    def _redosled(cls, v: int | None) -> int | None:
        if v is None:
            return None
        if v < 0 or v > REDOSLED_MAX:
            raise ValueError("Redosled mora biti nenegativan razuman broj.")
        return v


class AdminNotificationCategoryUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    naziv: str = Field(min_length=1, max_length=KATEGORIJA_NAZIV_MAX)
    aktivna: bool
    redosled: int | None = None

    @field_validator("naziv")
    @classmethod
    def _naziv(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Naziv ne sme biti prazan.")
        return v

    @field_validator("redosled")
    @classmethod
    def _redosled(cls, v: int | None) -> int | None:
        if v is None:
            return None
        if v < 0 or v > REDOSLED_MAX:
            raise ValueError("Redosled mora biti nenegativan razuman broj.")
        return v


# ===========================================================================
# ADMIN - obavestenja (list / detalj / status / statistika)
# ===========================================================================
class AdminNotificationListItem(BaseModel):
    id: int
    kategorija: NotificationCategoryOut
    naslov: str
    kratak_tekst: str
    status: str
    akcija: NotificationActionOut
    kreirao_platni_broj: str | None = None
    datum_objave: datetime.datetime | None = None
    datum_isteka: datetime.datetime | None = None
    datum_kreiranja: datetime.datetime | None = None
    datum_izmene: datetime.datetime | None = None
    broj_primalaca: int
    broj_procitanih: int
    broj_neprocitanih: int


class AdminNotificationListResponse(BaseModel):
    items: list[AdminNotificationListItem]
    total: int
    page: int
    page_size: int


class AdminNotificationTargetOut(BaseModel):
    tip_cilja: str
    vrednost: str | None = None


class AdminNotificationDetailResponse(BaseModel):
    id: int
    kategorija: NotificationCategoryOut
    naslov: str
    kratak_tekst: str
    sadrzaj: str
    status: str
    akcija: NotificationActionOut
    ciljevi: list[AdminNotificationTargetOut]
    kreirao_platni_broj: str | None = None
    datum_objave: datetime.datetime | None = None
    datum_isteka: datetime.datetime | None = None
    datum_kreiranja: datetime.datetime | None = None
    datum_izmene: datetime.datetime | None = None
    broj_primalaca: int
    broj_procitanih: int
    broj_neprocitanih: int


class AdminNotificationStatsResponse(BaseModel):
    notification_id: int
    broj_primalaca: int
    broj_procitanih: int
    broj_neprocitanih: int
    procenat_procitanih: float
    # Aditivna push polja. NAPOMENA: push_sent = "FCM prihvatio poruku",
    # NIJE potvrda da je poruka dostavljena uredjaju.
    push_pending: int
    push_sent: int
    push_failed: int
    push_skipped: int


class AdminNotificationResendResponse(BaseModel):
    notification_id: int
    resent_count: int


class AdminNotificationStatusRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
    datum_isteka: datetime.datetime | None = None

    @field_validator("status")
    @classmethod
    def _status(cls, v: str) -> str:
        v = v.strip().upper()
        if v not in OBAVESTENJE_STATUSI:
            raise ValueError("Nepoznat status obaveštenja.")
        return v

    @field_validator("datum_isteka")
    @classmethod
    def _naive(cls, v: datetime.datetime | None) -> datetime.datetime | None:
        return None if v is None else naive_only(v)

    @model_validator(mode="after")
    def _archive_no_expiry(self) -> "AdminNotificationStatusRequest":
        # ARCHIVED ne sme nositi datum_isteka (ne ignorisati tiho -> 422).
        if self.status == OBAVESTENJE_STATUS_ARCHIVED and self.datum_isteka is not None:
            raise ValueError("Arhiviranje ne prima datum_isteka.")
        return self
