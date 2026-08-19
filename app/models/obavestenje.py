import datetime

from sqlalchemy import CHAR, TIMESTAMP, VARCHAR, Numeric
from sqlalchemy.dialects.oracle import NCLOB, NVARCHAR2
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base

# --- Statusi obavestenja ---
OBAVESTENJE_STATUS_DRAFT = "DRAFT"
OBAVESTENJE_STATUS_PUBLISHED = "PUBLISHED"
OBAVESTENJE_STATUS_ARCHIVED = "ARCHIVED"

OBAVESTENJE_STATUSI = (
    OBAVESTENJE_STATUS_DRAFT,
    OBAVESTENJE_STATUS_PUBLISHED,
    OBAVESTENJE_STATUS_ARCHIVED,
)

# Dozvoljeni statusni prelazi. Nema vracanja unazad ni ponovnog objavljivanja.
OBAVESTENJE_DOZVOLJENI_PRELAZI: dict[str, frozenset[str]] = {
    OBAVESTENJE_STATUS_DRAFT: frozenset({OBAVESTENJE_STATUS_PUBLISHED}),
    OBAVESTENJE_STATUS_PUBLISHED: frozenset({OBAVESTENJE_STATUS_ARCHIVED}),
    OBAVESTENJE_STATUS_ARCHIVED: frozenset(),
}


def is_valid_notification_transition(trenutni: str, novi: str) -> bool:
    return novi in OBAVESTENJE_DOZVOLJENI_PRELAZI.get(trenutni, frozenset())


# --- Tipovi akcije ---
AKCIJA_NONE = "NONE"
AKCIJA_SURVEY = "SURVEY"
AKCIJA_IDEA = "IDEA"
AKCIJA_URL = "URL"

AKCIJA_TIPOVI = (AKCIJA_NONE, AKCIJA_SURVEY, AKCIJA_IDEA, AKCIJA_URL)
# Tipovi koji koriste RESURS_ID (interni entitet) odnosno spoljni URL.
AKCIJE_SA_RESURSOM = (AKCIJA_SURVEY, AKCIJA_IDEA)
AKCIJE_SA_URL = (AKCIJA_URL,)

# --- Tipovi cilja ---
CILJ_SVI = "SVI"
CILJ_CENTRALA = "CENTRALA"
CILJ_MALOPRODAJA = "MALOPRODAJA"
CILJ_ORGJED = "ORGJED"
CILJ_PLATNI_BROJ = "PLATNI_BROJ"

TIPOVI_CILJA = (CILJ_SVI, CILJ_CENTRALA, CILJ_MALOPRODAJA, CILJ_ORGJED, CILJ_PLATNI_BROJ)
CILJEVI_BEZ_VREDNOSTI = (CILJ_SVI, CILJ_CENTRALA, CILJ_MALOPRODAJA)
CILJEVI_SA_VREDNOSCU = (CILJ_ORGJED, CILJ_PLATNI_BROJ)
# BLOKER: nema pouzdanog HR podatka za razlikovanje ovih ciljeva (kao i modul ANKETE).
CILJEVI_NEPODRZANI = (CILJ_CENTRALA, CILJ_MALOPRODAJA)


class ObavestenjeKategorija(Base):
    __tablename__ = "PULS_OBAVESTENJE_KATEGORIJE"

    sifra: Mapped[str] = mapped_column("SIFRA", VARCHAR(50), primary_key=True)
    naziv: Mapped[str] = mapped_column("NAZIV", NVARCHAR2(100))
    aktivna: Mapped[str] = mapped_column("AKTIVNA", CHAR(1), default="D")
    redosled: Mapped[int | None] = mapped_column("REDOSLED", Numeric(10, 0), nullable=True)
    datum_kreiranja: Mapped[datetime.datetime | None] = mapped_column(
        "DATUM_KREIRANJA", TIMESTAMP(timezone=False), nullable=True
    )
    datum_izmene: Mapped[datetime.datetime | None] = mapped_column(
        "DATUM_IZMENE", TIMESTAMP(timezone=False), nullable=True
    )

    @property
    def is_aktivna(self) -> bool:
        return self.aktivna == "D"


class Obavestenje(Base):
    __tablename__ = "PULS_OBAVESTENJA"

    id: Mapped[int] = mapped_column("ID", Numeric(19, 0), primary_key=True)
    kategorija_sifra: Mapped[str] = mapped_column("KATEGORIJA_SIFRA", VARCHAR(50))
    naslov: Mapped[str] = mapped_column("NASLOV", NVARCHAR2(200))
    kratak_tekst: Mapped[str] = mapped_column("KRATAK_TEKST", NVARCHAR2(500))
    sadrzaj: Mapped[str] = mapped_column("SADRZAJ", NCLOB)
    status: Mapped[str] = mapped_column("STATUS", VARCHAR(20), default=OBAVESTENJE_STATUS_DRAFT)
    akcija_tip: Mapped[str] = mapped_column("AKCIJA_TIP", VARCHAR(30), default=AKCIJA_NONE)
    resurs_id: Mapped[int | None] = mapped_column("RESURS_ID", Numeric(19, 0), nullable=True)
    akcija_url: Mapped[str | None] = mapped_column("AKCIJA_URL", VARCHAR(1000), nullable=True)
    kreirao_platni_broj: Mapped[str | None] = mapped_column(
        "KREIRAO_PLATNI_BROJ", VARCHAR(30), nullable=True
    )
    datum_objave: Mapped[datetime.datetime | None] = mapped_column(
        "DATUM_OBJAVE", TIMESTAMP(timezone=False), nullable=True
    )
    datum_isteka: Mapped[datetime.datetime | None] = mapped_column(
        "DATUM_ISTEKA", TIMESTAMP(timezone=False), nullable=True
    )
    datum_kreiranja: Mapped[datetime.datetime | None] = mapped_column(
        "DATUM_KREIRANJA", TIMESTAMP(timezone=False), nullable=True
    )
    datum_izmene: Mapped[datetime.datetime | None] = mapped_column(
        "DATUM_IZMENE", TIMESTAMP(timezone=False), nullable=True
    )

    def is_available_to_employees(self, now: datetime.datetime) -> bool:
        """DDL ugovor: PUBLISHED je dostupno samo ako DATUM_OBJAVE nije NULL i nije u
        buducnosti, I DATUM_ISTEKA nije NULL i veci je od sada. (PUBLISHED po DDL-u
        uvek ima oba datuma - ovde ih striktno zahtevamo, bez divergencije od SQL-a.)"""
        if self.status != OBAVESTENJE_STATUS_PUBLISHED:
            return False
        if self.datum_objave is None or self.datum_objave > now:
            return False
        if self.datum_isteka is None or self.datum_isteka <= now:
            return False
        return True


class ObavestenjeCilj(Base):
    __tablename__ = "PULS_OBAVESTENJE_CILJEVI"

    id: Mapped[int] = mapped_column("ID", Numeric(19, 0), primary_key=True)
    obavestenje_id: Mapped[int] = mapped_column("OBAVESTENJE_ID", Numeric(19, 0))
    tip_cilja: Mapped[str] = mapped_column("TIP_CILJA", VARCHAR(20))
    vrednost: Mapped[str | None] = mapped_column("VREDNOST", VARCHAR(100), nullable=True)
    datum_kreiranja: Mapped[datetime.datetime | None] = mapped_column(
        "DATUM_KREIRANJA", TIMESTAMP(timezone=False), nullable=True
    )


class ObavestenjePrimalac(Base):
    __tablename__ = "PULS_OBAVESTENJE_PRIMAOCI"

    id: Mapped[int] = mapped_column("ID", Numeric(19, 0), primary_key=True)
    obavestenje_id: Mapped[int] = mapped_column("OBAVESTENJE_ID", Numeric(19, 0))
    korisnik_id: Mapped[int] = mapped_column("KORISNIK_ID", Numeric(19, 0))
    procitano: Mapped[str] = mapped_column("PROCITANO", CHAR(1), default="N")
    datum_citanja: Mapped[datetime.datetime | None] = mapped_column(
        "DATUM_CITANJA", TIMESTAMP(timezone=False), nullable=True
    )
    datum_kreiranja: Mapped[datetime.datetime | None] = mapped_column(
        "DATUM_KREIRANJA", TIMESTAMP(timezone=False), nullable=True
    )
    datum_izmene: Mapped[datetime.datetime | None] = mapped_column(
        "DATUM_IZMENE", TIMESTAMP(timezone=False), nullable=True
    )

    @property
    def is_procitano(self) -> bool:
        return self.procitano == "D"
