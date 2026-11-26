"""Modul HVALA, KOLEGA! (zahvalnice) - sql/013_zahvalnice_module.sql."""

import datetime

from sqlalchemy import CHAR, TIMESTAMP, VARCHAR, Numeric
from sqlalchemy.dialects.oracle import NVARCHAR2
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base

STATUS_OBJAVLJENA = "OBJAVLJENA"
STATUS_NA_PROVERI = "NA_PROVERI"
STATUS_SAKRIVENA = "SAKRIVENA"
STATUSI = (STATUS_OBJAVLJENA, STATUS_NA_PROVERI, STATUS_SAKRIVENA)

POVODI = {"POMOC": "Pomoć", "TIMSKI_RAD": "Timski rad", "LJUBAZNOST": "Ljubaznost prema kupcu"}


class Zahvalnica(Base):
    __tablename__ = "PULS_ZAHVALNICE"

    id: Mapped[int] = mapped_column("ID", Numeric(19, 0), primary_key=True)
    posiljalac_id: Mapped[int] = mapped_column("POSILJALAC_ID", Numeric(19, 0))
    primalac_id: Mapped[int] = mapped_column("PRIMALAC_ID", Numeric(19, 0))
    posiljalac_orgjed: Mapped[str | None] = mapped_column("POSILJALAC_ORGJED", VARCHAR(50), nullable=True)
    primalac_orgjed: Mapped[str | None] = mapped_column("PRIMALAC_ORGJED", VARCHAR(50), nullable=True)
    povod: Mapped[str] = mapped_column("POVOD", VARCHAR(20))
    tekst: Mapped[str] = mapped_column("TEKST", NVARCHAR2(280))
    status: Mapped[str] = mapped_column("STATUS", VARCHAR(20), default=STATUS_OBJAVLJENA)
    proverena: Mapped[str] = mapped_column("PROVERENA", CHAR(1), default="N")
    procitana: Mapped[str] = mapped_column("PROCITANA", CHAR(1), default="N")
    datum_kreiranja: Mapped[datetime.datetime] = mapped_column("DATUM_KREIRANJA", TIMESTAMP(timezone=False))
    datum_izmene: Mapped[datetime.datetime | None] = mapped_column(
        "DATUM_IZMENE", TIMESTAMP(timezone=False), nullable=True
    )
    izmenio_korisnik_id: Mapped[int | None] = mapped_column("IZMENIO_KORISNIK_ID", Numeric(19, 0), nullable=True)


class ZahvalnicaPrijava(Base):
    __tablename__ = "PULS_ZAHVALNICA_PRIJAVE"

    id: Mapped[int] = mapped_column("ID", Numeric(19, 0), primary_key=True)
    zahvalnica_id: Mapped[int] = mapped_column("ZAHVALNICA_ID", Numeric(19, 0))
    korisnik_id: Mapped[int] = mapped_column("KORISNIK_ID", Numeric(19, 0))
    razlog: Mapped[str | None] = mapped_column("RAZLOG", NVARCHAR2(200), nullable=True)
    datum_kreiranja: Mapped[datetime.datetime] = mapped_column("DATUM_KREIRANJA", TIMESTAMP(timezone=False))
