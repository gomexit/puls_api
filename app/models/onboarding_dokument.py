import datetime

from sqlalchemy import BLOB, CHAR, TIMESTAMP, VARCHAR, Numeric
from sqlalchemy.dialects.oracle import NCLOB, NVARCHAR2
from sqlalchemy.orm import Mapped, deferred, mapped_column

from app.db.session import Base

# --- Statusi onboarding dokumenta ---
ONB_DOKUMENT_STATUS_DRAFT = "DRAFT"
ONB_DOKUMENT_STATUS_PUBLISHED = "PUBLISHED"
ONB_DOKUMENT_STATUS_ARCHIVED = "ARCHIVED"

ONB_DOKUMENT_STATUSI = (
    ONB_DOKUMENT_STATUS_DRAFT,
    ONB_DOKUMENT_STATUS_PUBLISHED,
    ONB_DOKUMENT_STATUS_ARCHIVED,
)

# Dozvoljeni prelazi. ARCHIVED je terminalan; PUBLISHED se moze vratiti u DRAFT.
ONB_DOKUMENT_DOZVOLJENI_PRELAZI: dict[str, frozenset[str]] = {
    ONB_DOKUMENT_STATUS_DRAFT: frozenset(
        {ONB_DOKUMENT_STATUS_PUBLISHED, ONB_DOKUMENT_STATUS_ARCHIVED}
    ),
    ONB_DOKUMENT_STATUS_PUBLISHED: frozenset(
        {ONB_DOKUMENT_STATUS_DRAFT, ONB_DOKUMENT_STATUS_ARCHIVED}
    ),
    ONB_DOKUMENT_STATUS_ARCHIVED: frozenset(),
}

ONB_DOKUMENT_MIME_PDF = "application/pdf"


def is_valid_onboarding_document_transition(trenutni: str, novi: str) -> bool:
    return novi in ONB_DOKUMENT_DOZVOLJENI_PRELAZI.get(trenutni, frozenset())


class OnboardingDokument(Base):
    """PULS_ONBOARDING_DOKUMENTI - PDF cuvan kao BLOB. SADRZAJ je `deferred`: nijedan ORM
    upit ga ne ucitava osim ako se eksplicitno trazi (lista/detalj koriste selekciju
    metadata kolona; sadrzaj se cita samo u content endpointima)."""

    __tablename__ = "PULS_ONBOARDING_DOKUMENTI"

    id: Mapped[int] = mapped_column("ID", Numeric(19, 0), primary_key=True)
    naziv: Mapped[str] = mapped_column("NAZIV", NVARCHAR2(200))
    opis: Mapped[str | None] = mapped_column("OPIS", NCLOB, nullable=True)
    originalni_naziv_fajla: Mapped[str] = mapped_column("ORIGINALNI_NAZIV_FAJLA", NVARCHAR2(255))
    mime_tip: Mapped[str] = mapped_column("MIME_TIP", VARCHAR(100), default=ONB_DOKUMENT_MIME_PDF)
    velicina_bajtova: Mapped[int] = mapped_column("VELICINA_BAJTOVA", Numeric(12, 0))
    sha256: Mapped[str] = mapped_column("SHA256", CHAR(64))
    sadrzaj: Mapped[bytes] = deferred(mapped_column("SADRZAJ", BLOB))
    status: Mapped[str] = mapped_column("STATUS", VARCHAR(20), default=ONB_DOKUMENT_STATUS_DRAFT)
    redosled: Mapped[int] = mapped_column("REDOSLED", Numeric(10, 0), default=1)
    verzija: Mapped[int] = mapped_column("VERZIJA", Numeric(10, 0), default=1)
    kreirao_platni_broj: Mapped[str] = mapped_column("KREIRAO_PLATNI_BROJ", VARCHAR(30))
    izmenio_platni_broj: Mapped[str] = mapped_column("IZMENIO_PLATNI_BROJ", VARCHAR(30))
    datum_kreiranja: Mapped[datetime.datetime] = mapped_column(
        "DATUM_KREIRANJA", TIMESTAMP(timezone=False)
    )
    datum_izmene: Mapped[datetime.datetime] = mapped_column(
        "DATUM_IZMENE", TIMESTAMP(timezone=False)
    )
    datum_objave: Mapped[datetime.datetime | None] = mapped_column(
        "DATUM_OBJAVE", TIMESTAMP(timezone=False), nullable=True
    )
