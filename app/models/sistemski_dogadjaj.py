import datetime

from sqlalchemy import TIMESTAMP, VARCHAR, Numeric
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base

# --- Statusi obrade dogadjaja ---
DOGADJAJ_STATUS_PENDING = "PENDING"
DOGADJAJ_STATUS_PROCESSED = "PROCESSED"
DOGADJAJ_STATUS_SKIPPED = "SKIPPED"
DOGADJAJ_STATUS_FAILED = "FAILED"

DOGADJAJ_STATUSI = (
    DOGADJAJ_STATUS_PENDING,
    DOGADJAJ_STATUS_PROCESSED,
    DOGADJAJ_STATUS_SKIPPED,
    DOGADJAJ_STATUS_FAILED,
)

# --- Tipovi sistemskih dogadjaja (izvor za automatska SISTEM obavestenja) ---
DOGADJAJ_TIP_SURVEY_ACTIVATED = "SURVEY_ACTIVATED"
DOGADJAJ_TIP_SURVEY_EXPIRING = "SURVEY_EXPIRING"
DOGADJAJ_TIP_IDEA_CYCLE_ACTIVATED = "IDEA_CYCLE_ACTIVATED"
DOGADJAJ_TIP_IDEA_CYCLE_EXPIRING = "IDEA_CYCLE_EXPIRING"
DOGADJAJ_TIP_IDEA_TOP_10 = "IDEA_TOP_10"
DOGADJAJ_TIP_IDEA_NAGRADJENA = "IDEA_NAGRADJENA"
DOGADJAJ_TIP_APP_VERSION_CHANGED = "APP_VERSION_CHANGED"
# RESURS_ID = PULS_ANKETA_UCESCA.ID (ne ANKETA_ID) - dodela je per-korisnik.
DOGADJAJ_TIP_ONBOARDING_SURVEY_AVAILABLE = "ONBOARDING_SURVEY_AVAILABLE"

DOGADJAJ_TIPOVI = (
    DOGADJAJ_TIP_SURVEY_ACTIVATED,
    DOGADJAJ_TIP_SURVEY_EXPIRING,
    DOGADJAJ_TIP_IDEA_CYCLE_ACTIVATED,
    DOGADJAJ_TIP_IDEA_CYCLE_EXPIRING,
    DOGADJAJ_TIP_IDEA_TOP_10,
    DOGADJAJ_TIP_IDEA_NAGRADJENA,
    DOGADJAJ_TIP_APP_VERSION_CHANGED,
    DOGADJAJ_TIP_ONBOARDING_SURVEY_AVAILABLE,
)


class SistemskiDogadjaj(Base):
    """PULS_SISTEMSKI_DOGADJAJI - idempotentni event queue za sistemska obavestenja.

    DOGADJAJ_KLJUC je jedinstven i nosi svu informaciju potrebnu za idempotentnost
    (npr. "SURVEY_ACTIVATED:123" ili "SURVEY_EXPIRING:123:2026-03-01T10:00:00" za
    podsetnik vezan za konkretan rok - produzenje roka menja kljuc i time namerno
    dozvoljava nov podsetnik). Enqueue NIKADA ne commituje - ucestvuje u transakciji
    poslovne operacije koja ga izaziva (ili u worker discovery transakciji)."""

    __tablename__ = "PULS_SISTEMSKI_DOGADJAJI"

    id: Mapped[int] = mapped_column("ID", Numeric(19, 0), primary_key=True)
    dogadjaj_kljuc: Mapped[str] = mapped_column("DOGADJAJ_KLJUC", VARCHAR(300))
    tip_dogadjaja: Mapped[str] = mapped_column("TIP_DOGADJAJA", VARCHAR(30))
    resurs_id: Mapped[int | None] = mapped_column("RESURS_ID", Numeric(19, 0), nullable=True)
    # Verzija (APP_VERSION_CHANGED) ili drugi bezbedan marker - NIKADA tajna/token.
    vrednost: Mapped[str | None] = mapped_column("VREDNOST", VARCHAR(100), nullable=True)
    status: Mapped[str] = mapped_column("STATUS", VARCHAR(20), default=DOGADJAJ_STATUS_PENDING)
    broj_pokusaja: Mapped[int] = mapped_column("BROJ_POKUSAJA", Numeric(10, 0), default=0)
    datum_sledeceg_pokusaja: Mapped[datetime.datetime | None] = mapped_column(
        "DATUM_SLEDECEG_POKUSAJA", TIMESTAMP(timezone=False), nullable=True
    )
    # Samo bezbedan kod greske (npr. naziv exception klase) - bez pune poruke/tajni.
    poslednji_error_code: Mapped[str | None] = mapped_column(
        "POSLEDNJI_ERROR_CODE", VARCHAR(100), nullable=True
    )
    obavestenje_id: Mapped[int | None] = mapped_column("OBAVESTENJE_ID", Numeric(19, 0), nullable=True)
    datum_kreiranja: Mapped[datetime.datetime | None] = mapped_column(
        "DATUM_KREIRANJA", TIMESTAMP(timezone=False), nullable=True
    )
    datum_obrade: Mapped[datetime.datetime | None] = mapped_column(
        "DATUM_OBRADE", TIMESTAMP(timezone=False), nullable=True
    )
