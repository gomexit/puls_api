"""Modul GOMEX PUTANJA (dnevna igra) - sql/012_igra_module.sql."""

import datetime

from sqlalchemy import CLOB, DATE, TIMESTAMP, VARCHAR, Numeric
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base

REZULTAT_U_TOKU = "U_TOKU"
REZULTAT_RESEN = "RESEN"
REZULTAT_STATUSI = (REZULTAT_U_TOKU, REZULTAT_RESEN)


class IgraNivo(Base):
    __tablename__ = "PULS_IGRA_NIVOI"

    id: Mapped[int] = mapped_column("ID", Numeric(19, 0), primary_key=True)
    datum: Mapped[datetime.date] = mapped_column("DATUM", DATE)
    velicina: Mapped[int] = mapped_column("VELICINA", Numeric(2, 0))
    podaci: Mapped[str] = mapped_column("PODACI", CLOB)
    resenje: Mapped[str] = mapped_column("RESENJE", CLOB)
    datum_kreiranja: Mapped[datetime.datetime] = mapped_column("DATUM_KREIRANJA", TIMESTAMP(timezone=False))


class IgraRezultat(Base):
    __tablename__ = "PULS_IGRA_REZULTATI"

    id: Mapped[int] = mapped_column("ID", Numeric(19, 0), primary_key=True)
    nivo_id: Mapped[int] = mapped_column("NIVO_ID", Numeric(19, 0))
    korisnik_id: Mapped[int] = mapped_column("KORISNIK_ID", Numeric(19, 0))
    orgjed_sifra: Mapped[str | None] = mapped_column("ORGJED_SIFRA", VARCHAR(50), nullable=True)
    status: Mapped[str] = mapped_column("STATUS", VARCHAR(20), default=REZULTAT_U_TOKU)
    datum_pocetka: Mapped[datetime.datetime] = mapped_column("DATUM_POCETKA", TIMESTAMP(timezone=False))
    datum_resenja: Mapped[datetime.datetime | None] = mapped_column(
        "DATUM_RESENJA", TIMESTAMP(timezone=False), nullable=True
    )
    trajanje_ms: Mapped[int | None] = mapped_column("TRAJANJE_MS", Numeric(10, 0), nullable=True)
    broj_pokretanja: Mapped[int] = mapped_column("BROJ_POKRETANJA", Numeric(5, 0), default=1)
