import datetime

from sqlalchemy import TIMESTAMP, VARCHAR, Numeric
from sqlalchemy.dialects.oracle import NVARCHAR2
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base

# --- Statusi ciklusa (centralizovano, ne razbacivati stringove kroz kod) ---
CIKLUS_STATUS_PLANIRAN = "PLANIRAN"
CIKLUS_STATUS_AKTIVAN = "AKTIVAN"
CIKLUS_STATUS_ZATVOREN = "ZATVOREN"

CIKLUS_STATUSI = (
    CIKLUS_STATUS_PLANIRAN,
    CIKLUS_STATUS_AKTIVAN,
    CIKLUS_STATUS_ZATVOREN,
)

# Dozvoljeni prelazi statusa ciklusa. ZATVOREN je zavrsni status.
CIKLUS_DOZVOLJENI_PRELAZI: dict[str, frozenset[str]] = {
    CIKLUS_STATUS_PLANIRAN: frozenset({CIKLUS_STATUS_AKTIVAN}),
    CIKLUS_STATUS_AKTIVAN: frozenset({CIKLUS_STATUS_ZATVOREN}),
    CIKLUS_STATUS_ZATVOREN: frozenset(),
}


def is_valid_cycle_transition(trenutni: str, novi: str) -> bool:
    return novi in CIKLUS_DOZVOLJENI_PRELAZI.get(trenutni, frozenset())


class IdeaCiklus(Base):
    __tablename__ = "PULS_IDEA_CIKLUSI"

    id: Mapped[int] = mapped_column("ID", Numeric(19, 0), primary_key=True)
    # NVARCHAR2 (AL16UTF16) da bi cirilica/emoji bili sacuvani - baza je EE8ISO8859P2.
    naziv: Mapped[str] = mapped_column("NAZIV", NVARCHAR2(200))
    datum_pocetka: Mapped[datetime.datetime] = mapped_column("DATUM_POCETKA", TIMESTAMP(timezone=False))
    datum_zavrsetka: Mapped[datetime.datetime] = mapped_column(
        "DATUM_ZAVRSETKA", TIMESTAMP(timezone=False)
    )
    status: Mapped[str] = mapped_column("STATUS", VARCHAR(20), default=CIKLUS_STATUS_PLANIRAN)
    datum_kreiranja: Mapped[datetime.datetime | None] = mapped_column(
        "DATUM_KREIRANJA", TIMESTAMP(timezone=False), nullable=True
    )
    datum_izmene: Mapped[datetime.datetime | None] = mapped_column(
        "DATUM_IZMENE", TIMESTAMP(timezone=False), nullable=True
    )

    def is_submission_open(self, now: datetime.datetime) -> bool:
        return (
            self.status == CIKLUS_STATUS_AKTIVAN
            and self.datum_pocetka <= now <= self.datum_zavrsetka
        )