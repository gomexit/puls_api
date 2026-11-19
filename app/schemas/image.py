import datetime
from typing import Annotated

from pydantic import BaseModel, BeforeValidator, Field

from app.models.slika import SLIKA_STATUSI
from app.services.image_processing import NAZIV_MAX
from app.services.onboarding_pdf import strip_text

NazivText = Annotated[str, BeforeValidator(strip_text), Field(min_length=1, max_length=NAZIV_MAX)]

STATUS_DESCRIPTION = (
    "Status slike:\n"
    "- **AKTIVNA** - slika se može koristiti i aplikacija je prikazuje (`GET /images/{id}`).\n"
    "- **ARHIVIRANA** - trajno povučena. Aplikacija dobija 404, a slika ostaje u bazi "
    "(fizičko brisanje ne postoji). Terminalan status."
)


class AdminImageOut(BaseModel):
    """Metadata slike za admin/HR. Nikada ne sadrži BLOB ni SHA-256."""

    id: int
    naziv: str
    originalni_naziv_fajla: str
    mime_tip: str = Field(description="image/jpeg ili image/png.")
    velicina_bajtova: int = Field(description="Veličina sačuvane (smanjene) slike.")
    sirina: int = Field(description="Širina sačuvane slike u pikselima (najviše 1200).")
    visina: int = Field(description="Visina sačuvane slike u pikselima (najviše 1200).")
    status: str = Field(json_schema_extra={"enum": list(SLIKA_STATUSI)})
    kreirao_platni_broj: str
    izmenio_platni_broj: str
    datum_kreiranja: datetime.datetime
    datum_izmene: datetime.datetime
    url: str = Field(description="Putanja za prikaz u aplikaciji (zahteva prijavu zaposlenog).")


class AdminImageListResponse(BaseModel):
    items: list[AdminImageOut]
    total: int
    page: int
    page_size: int
    sort_by: str
    sort_dir: str


class AdminImageUpdateRequest(BaseModel):
    naziv: NazivText


class AdminImageStatusRequest(BaseModel):
    status: str = Field(description="AKTIVNA ili ARHIVIRANA.", json_schema_extra={"enum": list(SLIKA_STATUSI)})
