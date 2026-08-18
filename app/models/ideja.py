import datetime
from decimal import Decimal

from sqlalchemy import TIMESTAMP, VARCHAR, Numeric
from sqlalchemy.dialects.oracle import NCLOB, NVARCHAR2
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base

# --- Statusi ideje (centralizovano) ---
IDEJA_STATUS_POSLATA = "POSLATA"
IDEJA_STATUS_U_OBRADI = "U_OBRADI"
IDEJA_STATUS_ODOBRENA = "ODOBRENA"
IDEJA_STATUS_ODBIJENA = "ODBIJENA"
IDEJA_STATUS_TOP_10 = "TOP_10"
IDEJA_STATUS_NAGRADJENA = "NAGRAĐENA"

IDEJA_STATUSI = (
    IDEJA_STATUS_POSLATA,
    IDEJA_STATUS_U_OBRADI,
    IDEJA_STATUS_ODOBRENA,
    IDEJA_STATUS_ODBIJENA,
    IDEJA_STATUS_TOP_10,
    IDEJA_STATUS_NAGRADJENA,
)

# Statusi koji se prikazuju na javnoj listi najboljih ideja.
IDEJA_TOP_STATUSI = (IDEJA_STATUS_TOP_10, IDEJA_STATUS_NAGRADJENA)

# Dozvoljeni prelazi statusa ideje. NAGRAĐENA i ODBIJENA su zavrsni statusi.
IDEJA_DOZVOLJENI_PRELAZI: dict[str, frozenset[str]] = {
    IDEJA_STATUS_POSLATA: frozenset({IDEJA_STATUS_U_OBRADI, IDEJA_STATUS_ODBIJENA}),
    IDEJA_STATUS_U_OBRADI: frozenset({IDEJA_STATUS_ODOBRENA, IDEJA_STATUS_ODBIJENA}),
    IDEJA_STATUS_ODOBRENA: frozenset({IDEJA_STATUS_TOP_10, IDEJA_STATUS_ODBIJENA}),
    IDEJA_STATUS_TOP_10: frozenset({IDEJA_STATUS_NAGRADJENA}),
    IDEJA_STATUS_ODBIJENA: frozenset(),
    IDEJA_STATUS_NAGRADJENA: frozenset(),
}

# Tezine za konacnu ocenu: HR 70%, AI 30%.
HR_WEIGHT = Decimal("0.70")
AI_WEIGHT = Decimal("0.30")


def is_valid_idea_transition(trenutni: str, novi: str) -> bool:
    return novi in IDEJA_DOZVOLJENI_PRELAZI.get(trenutni, frozenset())


def compute_konacna_ocena(hr_ocena: int | None, ai_ocena: Decimal | None) -> Decimal | None:
    """Konacna ocena = HR * 0.70 + AI * 0.30. NULL ako bilo koja ocena nedostaje."""
    if hr_ocena is None or ai_ocena is None:
        return None
    return (Decimal(hr_ocena) * HR_WEIGHT + Decimal(ai_ocena) * AI_WEIGHT).quantize(Decimal("0.01"))


class Ideja(Base):
    __tablename__ = "PULS_IDEJE"

    id: Mapped[int] = mapped_column("ID", Numeric(19, 0), primary_key=True)
    korisnik_id: Mapped[int] = mapped_column("KORISNIK_ID", Numeric(19, 0))
    ciklus_id: Mapped[int] = mapped_column("CIKLUS_ID", Numeric(19, 0))

    # Snapshot autora u trenutku slanja (istorija ostaje sacuvana).
    platni_broj: Mapped[str] = mapped_column("PLATNI_BROJ", VARCHAR(30))
    ime_autora: Mapped[str] = mapped_column("IME_AUTORA", VARCHAR(100))
    prezime_autora: Mapped[str] = mapped_column("PREZIME_AUTORA", VARCHAR(100))
    orgjed_sifra: Mapped[str | None] = mapped_column("ORGJED_SIFRA", VARCHAR(50), nullable=True)

    # NVARCHAR2/NCLOB (AL16UTF16) - baza je EE8ISO8859P2 i ne cuva cirilicu/emoji u
    # VARCHAR2. Maks. duzina opisa (4000) se namece na aplikacionom (Pydantic) nivou.
    naslov: Mapped[str] = mapped_column("NASLOV", NVARCHAR2(200))
    opis: Mapped[str] = mapped_column("OPIS", NCLOB)
    status: Mapped[str] = mapped_column("STATUS", VARCHAR(20), default=IDEJA_STATUS_POSLATA)

    hr_ocena: Mapped[int | None] = mapped_column("HR_OCENA", Numeric(2, 0), nullable=True)
    ai_ocena: Mapped[Decimal | None] = mapped_column("AI_OCENA", Numeric(4, 2), nullable=True)
    konacna_ocena: Mapped[Decimal | None] = mapped_column("KONACNA_OCENA", Numeric(5, 2), nullable=True)

    datum_kreiranja: Mapped[datetime.datetime | None] = mapped_column(
        "DATUM_KREIRANJA", TIMESTAMP(timezone=False), nullable=True
    )
    datum_izmene: Mapped[datetime.datetime | None] = mapped_column(
        "DATUM_IZMENE", TIMESTAMP(timezone=False), nullable=True
    )