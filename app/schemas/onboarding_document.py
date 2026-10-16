import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field

from app.models.onboarding_dokument import ONB_DOKUMENT_STATUSI
from app.services.onboarding_pdf import (
    NAZIV_MAX,
    OPIS_MAX,
    REDOSLED_MAX,
    REDOSLED_MIN,
    strip_text,
    strip_text_or_none,
)

# Trim PRE provere duzine (BeforeValidator), pa Field ogranicenja idu i u OpenAPI
# (minLength/maxLength) i vaze za stvarnu validaciju - bez vestackih granica.
NazivText = Annotated[
    str, BeforeValidator(strip_text), Field(min_length=1, max_length=NAZIV_MAX)
]
# max_length ide na str granu unije: na `str | None` bi padao TypeError kada opis
# posle trima postane None.
OpisText = Annotated[
    Annotated[str, Field(max_length=OPIS_MAX)] | None, BeforeValidator(strip_text_or_none)
]

# ------------------------------------------------------------ opis statusa (Swagger)
STATUS_DESCRIPTION = (
    "Status dokumenta:\n"
    "- **DRAFT** - radna verzija. Vidi je samo admin/HR; zaposleni je NE vide (404). "
    "Naziv, opis i redosled se mogu menjati, a PDF se sme zameniti samo u ovom statusu.\n"
    "- **PUBLISHED** - objavljen: vidljiv zaposlenima u aplikaciji. Mogu se menjati naziv, "
    "opis i redosled, ali PDF se NE zamenjuje (prvo vrati u DRAFT). `datum_objave` je postavljen.\n"
    "- **ARCHIVED** - trajno povucen iz upotrebe. Terminalan status: dokument se vise ne menja "
    "i ne vidi se zaposlenima. Ostaje u bazi (fizicko brisanje ne postoji)."
)

STATUS_TRANSITIONS_MD = (
    "**Dozvoljeni prelazi statusa**\n\n"
    "| Iz | U | Efekat |\n"
    "|---|---|---|\n"
    "| DRAFT | PUBLISHED | objava; postavlja `datum_objave` na trenutno vreme |\n"
    "| PUBLISHED | DRAFT | povlacenje iz objave; `datum_objave` postaje `null` |\n"
    "| DRAFT | ARCHIVED | arhiviranje bez objave |\n"
    "| PUBLISHED | ARCHIVED | arhiviranje objavljenog; `datum_objave` ostaje (istorija) |\n"
    "| ARCHIVED | bilo koji drugi | **409** `ONBOARDING_DOCUMENT_ARCHIVED` (terminalan) |\n\n"
    "Ista vrednost kao trenutni status je idempotentna: **200** bez izmene i bez audit zapisa. "
    "Nepoznata vrednost vraca **422** `INVALID_ONBOARDING_DOCUMENT_STATUS`. "
    "Vrednost se poredi bez obzira na velika/mala slova (`published` == `PUBLISHED`)."
)

_STATUS_VALUES = list(ONB_DOKUMENT_STATUSI)


# ============================================================== EMPLOYEE
class OnboardingDocumentOut(BaseModel):
    """Metadata PUBLISHED dokumenta za zaposlenog. Nikada ne sadrzi BLOB ni SHA-256."""

    id: int
    naziv: str
    opis: str | None = None
    originalni_naziv_fajla: str = Field(description="Ime originalnog PDF fajla (sanitizovano).")
    velicina_bajtova: int
    redosled: int = Field(description="Redosled prikaza (manji broj je ranije); ID je tie-breaker.")
    verzija: int = Field(description="Raste za 1 pri svakoj zameni PDF sadrzaja; pocinje od 1.")
    datum_objave: datetime.datetime | None = Field(
        default=None, description="Kada je dokument objavljen (PUBLISHED)."
    )


class OnboardingDocumentListResponse(BaseModel):
    items: list[OnboardingDocumentOut] = Field(
        description="Samo dokumenti u statusu PUBLISHED, sortirani po `redosled`, pa `id`."
    )


# ================================================================= ADMIN
class AdminOnboardingDocumentOut(BaseModel):
    """Admin metadata: status, SHA-256 i audit akteri/datumi. Nikada BLOB."""

    id: int
    naziv: str
    opis: str | None = None
    originalni_naziv_fajla: str
    mime_tip: str = Field(description="Uvek `application/pdf`.")
    velicina_bajtova: int
    sha256: str = Field(description="SHA-256 PDF sadrzaja (racuna backend).")
    status: Literal["DRAFT", "PUBLISHED", "ARCHIVED"] = Field(description=STATUS_DESCRIPTION)
    redosled: int
    verzija: int = Field(description="Raste za 1 samo pri zameni PDF sadrzaja.")
    kreirao_platni_broj: str
    izmenio_platni_broj: str
    datum_kreiranja: datetime.datetime
    datum_izmene: datetime.datetime
    datum_objave: datetime.datetime | None = Field(
        default=None,
        description="Postavlja se pri objavi (DRAFT -> PUBLISHED); `null` kada je dokument u DRAFT-u.",
    )


class AdminOnboardingDocumentListResponse(BaseModel):
    items: list[AdminOnboardingDocumentOut]
    total: int = Field(description="Ukupan broj dokumenata posle filtera (za paginaciju).")
    page: int
    page_size: int
    sort_by: str = Field(description="Kolona po kojoj je lista stvarno sortirana.")
    sort_dir: Literal["asc", "desc"] = Field(description="Smer stvarnog sortiranja.")


class AdminOnboardingDocumentUpdateRequest(BaseModel):
    """Izmena metadata (naziv, opis, redosled). Dozvoljena u DRAFT i PUBLISHED statusu;
    ARCHIVED se ne menja (409). PDF sadrzaj se menja posebnom rutom.
    extra='forbid' odbija svako nepoznato polje (npr. lazno 'izmenio_platni_broj');
    akter se uzima iskljucivo iz OBO konteksta."""

    model_config = ConfigDict(extra="forbid")

    naziv: NazivText
    opis: OpisText = None
    redosled: int = Field(ge=REDOSLED_MIN, le=REDOSLED_MAX)


class AdminOnboardingDocumentStatusRequest(BaseModel):
    """Ciljni status dokumenta. Prelazi su opisani u opisu rute."""

    model_config = ConfigDict(extra="forbid")

    # Vrednost se proverava u servisu (a ne Literal-om): nepoznat status daje
    # INVALID_ONBOARDING_DOCUMENT_STATUS (422), a ne generican VALIDATION_ERROR.
    # `enum` je ovde samo dokumentacija za Swagger.
    status: str = Field(
        min_length=1,
        max_length=50,
        description="Ciljni status. " + STATUS_DESCRIPTION,
        json_schema_extra={"enum": _STATUS_VALUES, "examples": ["PUBLISHED"]},
    )
