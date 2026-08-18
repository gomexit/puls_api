import datetime

from sqlalchemy import CHAR, TIMESTAMP, VARCHAR, Numeric
from sqlalchemy.dialects.oracle import NCLOB, NVARCHAR2
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base

# --- Statusi ankete ---
ANKETA_STATUS_DRAFT = "DRAFT"
ANKETA_STATUS_SCHEDULED = "SCHEDULED"
ANKETA_STATUS_ACTIVE = "ACTIVE"
ANKETA_STATUS_CLOSED = "CLOSED"
ANKETA_STATUS_ARCHIVED = "ARCHIVED"

ANKETA_STATUSI = (
    ANKETA_STATUS_DRAFT,
    ANKETA_STATUS_SCHEDULED,
    ANKETA_STATUS_ACTIVE,
    ANKETA_STATUS_CLOSED,
    ANKETA_STATUS_ARCHIVED,
)

# Statusi u kojima je struktura zakljucana (ne moze se menjati).
ANKETA_ZAKLJUCANI_STATUSI = (
    ANKETA_STATUS_SCHEDULED,
    ANKETA_STATUS_ACTIVE,
    ANKETA_STATUS_CLOSED,
    ANKETA_STATUS_ARCHIVED,
)

# Dozvoljeni statusni prelazi. Nema vracanja unazad ni ponovnog otvaranja.
ANKETA_DOZVOLJENI_PRELAZI: dict[str, frozenset[str]] = {
    ANKETA_STATUS_DRAFT: frozenset({ANKETA_STATUS_SCHEDULED, ANKETA_STATUS_ACTIVE}),
    ANKETA_STATUS_SCHEDULED: frozenset({ANKETA_STATUS_ACTIVE, ANKETA_STATUS_CLOSED}),
    ANKETA_STATUS_ACTIVE: frozenset({ANKETA_STATUS_CLOSED}),
    ANKETA_STATUS_CLOSED: frozenset({ANKETA_STATUS_ARCHIVED}),
    ANKETA_STATUS_ARCHIVED: frozenset(),
}


def is_valid_survey_transition(trenutni: str, novi: str) -> bool:
    return novi in ANKETA_DOZVOLJENI_PRELAZI.get(trenutni, frozenset())


# --- Tipovi pitanja (trenutno podrzani UI tipovi - nije slobodno prosiriva lista) ---
TIP_SINGLE_CHOICE = "SINGLE_CHOICE"
TIP_MULTI_CHOICE = "MULTI_CHOICE"
TIP_TEXT = "TEXT"
TIP_RATING_1_5 = "RATING_1_5"
TIP_RATING_1_10 = "RATING_1_10"
TIP_BOOLEAN = "BOOLEAN"
TIP_DROPDOWN = "DROPDOWN"

TIPOVI_PITANJA = (
    TIP_SINGLE_CHOICE,
    TIP_MULTI_CHOICE,
    TIP_TEXT,
    TIP_RATING_1_5,
    TIP_RATING_1_10,
    TIP_BOOLEAN,
    TIP_DROPDOWN,
)

# Pitanja koja imaju ponudjene opcije.
TIPOVI_SA_OPCIJAMA = (TIP_SINGLE_CHOICE, TIP_MULTI_CHOICE, TIP_DROPDOWN)
# Pitanja koja NE smeju imati opcije.
TIPOVI_BEZ_OPCIJA = (TIP_TEXT, TIP_BOOLEAN, TIP_RATING_1_5, TIP_RATING_1_10)
# Tipovi kod kojih se bira tacno jedna opcija.
TIPOVI_JEDNA_OPCIJA = (TIP_SINGLE_CHOICE, TIP_DROPDOWN)

RATING_RASPON = {TIP_RATING_1_5: (1, 5), TIP_RATING_1_10: (1, 10)}

# --- Tipovi cilja ---
CILJ_SVI = "SVI"
CILJ_CENTRALA = "CENTRALA"
CILJ_MALOPRODAJA = "MALOPRODAJA"
CILJ_ORGJED = "ORGJED"
CILJ_PLATNI_BROJ = "PLATNI_BROJ"

TIPOVI_CILJA = (CILJ_SVI, CILJ_CENTRALA, CILJ_MALOPRODAJA, CILJ_ORGJED, CILJ_PLATNI_BROJ)
CILJEVI_BEZ_VREDNOSTI = (CILJ_SVI, CILJ_CENTRALA, CILJ_MALOPRODAJA)
CILJEVI_SA_VREDNOSCU = (CILJ_ORGJED, CILJ_PLATNI_BROJ)
# BLOKER: nema pouzdanog HR podatka za razlikovanje ovih ciljeva (vidi survey_service).
CILJEVI_NEPODRZANI = (CILJ_CENTRALA, CILJ_MALOPRODAJA)

# --- Operatori uslova ---
OPERATOR_EQUALS = "EQUALS"
OPERATOR_NOT_EQUALS = "NOT_EQUALS"
OPERATOR_IN = "IN"
OPERATORI = (OPERATOR_EQUALS, OPERATOR_NOT_EQUALS, OPERATOR_IN)

# --- Statusi ucesca ---
UCESCE_NOT_STARTED = "NOT_STARTED"
UCESCE_IN_PROGRESS = "IN_PROGRESS"
UCESCE_SUBMITTED = "SUBMITTED"
UCESCE_STATUSI = (UCESCE_NOT_STARTED, UCESCE_IN_PROGRESS, UCESCE_SUBMITTED)


class AnketaTip(Base):
    __tablename__ = "PULS_ANKETA_TIPOVI"

    sifra: Mapped[str] = mapped_column("SIFRA", VARCHAR(50), primary_key=True)
    naziv: Mapped[str] = mapped_column("NAZIV", NVARCHAR2(200))
    aktivan: Mapped[str] = mapped_column("AKTIVAN", CHAR(1), default="D")
    datum_kreiranja: Mapped[datetime.datetime | None] = mapped_column(
        "DATUM_KREIRANJA", TIMESTAMP(timezone=False), nullable=True
    )
    datum_izmene: Mapped[datetime.datetime | None] = mapped_column(
        "DATUM_IZMENE", TIMESTAMP(timezone=False), nullable=True
    )


class Anketa(Base):
    __tablename__ = "PULS_ANKETE"

    id: Mapped[int] = mapped_column("ID", Numeric(19, 0), primary_key=True)
    tip_sifra: Mapped[str] = mapped_column("TIP_SIFRA", VARCHAR(50))
    naziv: Mapped[str] = mapped_column("NAZIV", NVARCHAR2(200))
    opis: Mapped[str | None] = mapped_column("OPIS", NCLOB, nullable=True)
    anonimna: Mapped[str] = mapped_column("ANONIMNA", CHAR(1), default="N")
    status: Mapped[str] = mapped_column("STATUS", VARCHAR(20), default=ANKETA_STATUS_DRAFT)
    datum_pocetka: Mapped[datetime.datetime] = mapped_column("DATUM_POCETKA", TIMESTAMP(timezone=False))
    datum_zavrsetka: Mapped[datetime.datetime] = mapped_column(
        "DATUM_ZAVRSETKA", TIMESTAMP(timezone=False)
    )
    datum_kreiranja: Mapped[datetime.datetime | None] = mapped_column(
        "DATUM_KREIRANJA", TIMESTAMP(timezone=False), nullable=True
    )
    datum_izmene: Mapped[datetime.datetime | None] = mapped_column(
        "DATUM_IZMENE", TIMESTAMP(timezone=False), nullable=True
    )

    @property
    def is_anonimna(self) -> bool:
        return self.anonimna == "D"

    def is_within_period(self, now: datetime.datetime) -> bool:
        return self.datum_pocetka <= now <= self.datum_zavrsetka

    def is_available_to_employees(self, now: datetime.datetime) -> bool:
        """Efektivno dostupna zaposlenima: status SCHEDULED/ACTIVE i unutar perioda.
        Istek perioda funkcionalno zatvara draft/submit i pre rucnog CLOSED."""
        return self.status in (ANKETA_STATUS_SCHEDULED, ANKETA_STATUS_ACTIVE) and self.is_within_period(
            now
        )