import datetime
from typing import Annotated

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field

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


# ============================================================== EMPLOYEE
class OnboardingDocumentOut(BaseModel):
    """Metadata dokumenta za zaposlenog. Nikada ne sadrzi BLOB ni SHA-256."""

    id: int
    naziv: str
    opis: str | None = None
    originalni_naziv_fajla: str
    velicina_bajtova: int
    redosled: int
    verzija: int
    datum_objave: datetime.datetime | None = None


class OnboardingDocumentListResponse(BaseModel):
    items: list[OnboardingDocumentOut]


# ================================================================= ADMIN
class AdminOnboardingDocumentOut(BaseModel):
    """Admin metadata: status, SHA-256 i audit akteri/datumi. Nikada BLOB."""

    id: int
    naziv: str
    opis: str | None = None
    originalni_naziv_fajla: str
    mime_tip: str
    velicina_bajtova: int
    sha256: str
    status: str
    redosled: int
    verzija: int
    kreirao_platni_broj: str
    izmenio_platni_broj: str
    datum_kreiranja: datetime.datetime
    datum_izmene: datetime.datetime
    datum_objave: datetime.datetime | None = None


class AdminOnboardingDocumentListResponse(BaseModel):
    items: list[AdminOnboardingDocumentOut]
    total: int
    page: int
    page_size: int


class AdminOnboardingDocumentUpdateRequest(BaseModel):
    """Izmena metadata. extra='forbid' odbija svako nepoznato polje (npr. lazno
    'izmenio_platni_broj'); akter se uzima iskljucivo iz OBO konteksta."""

    model_config = ConfigDict(extra="forbid")

    naziv: NazivText
    opis: OpisText = None
    redosled: int = Field(ge=REDOSLED_MIN, le=REDOSLED_MAX)


class AdminOnboardingDocumentStatusRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Vrednost se proverava u servisu: nepoznat status daje
    # INVALID_ONBOARDING_DOCUMENT_STATUS (422), a ne generican VALIDATION_ERROR.
    status: str = Field(min_length=1, max_length=50)
