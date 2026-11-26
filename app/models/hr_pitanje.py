"""Modul PITAJ HR - sql/014_pitaj_hr_module.sql."""

import datetime

from sqlalchemy import CHAR, TIMESTAMP, VARCHAR, Numeric
from sqlalchemy.dialects.oracle import NVARCHAR2
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base

STATUS_POSLATO = "POSLATO"
STATUS_ODGOVORENO = "ODGOVORENO"
STATUS_ZATVORENO = "ZATVORENO"
STATUSI = (STATUS_POSLATO, STATUS_ODGOVORENO, STATUS_ZATVORENO)

AUTOR_ZAPOSLENI = "ZAPOSLENI"
AUTOR_HR = "HR"


class HrKategorija(Base):
    __tablename__ = "PULS_HR_KATEGORIJE"

    sifra: Mapped[str] = mapped_column("SIFRA", VARCHAR(30), primary_key=True)
    naziv: Mapped[str] = mapped_column("NAZIV", NVARCHAR2(100))
    redosled: Mapped[int] = mapped_column("REDOSLED", Numeric(5, 0), default=0)
    aktivna: Mapped[str] = mapped_column("AKTIVNA", CHAR(1), default="D")
    kreirao_platni_broj: Mapped[str] = mapped_column("KREIRAO_PLATNI_BROJ", VARCHAR(30))
    izmenio_platni_broj: Mapped[str] = mapped_column("IZMENIO_PLATNI_BROJ", VARCHAR(30))
    datum_kreiranja: Mapped[datetime.datetime] = mapped_column("DATUM_KREIRANJA", TIMESTAMP(timezone=False))
    datum_izmene: Mapped[datetime.datetime] = mapped_column("DATUM_IZMENE", TIMESTAMP(timezone=False))


class HrPitanje(Base):
    __tablename__ = "PULS_HR_PITANJA"

    id: Mapped[int] = mapped_column("ID", Numeric(19, 0), primary_key=True)
    korisnik_id: Mapped[int] = mapped_column("KORISNIK_ID", Numeric(19, 0))
    kategorija_sifra: Mapped[str] = mapped_column("KATEGORIJA_SIFRA", VARCHAR(30))
    orgjed: Mapped[str | None] = mapped_column("ORGJED", VARCHAR(50), nullable=True)
    status: Mapped[str] = mapped_column("STATUS", VARCHAR(20), default=STATUS_POSLATO)
    dopuna_poslata: Mapped[str] = mapped_column("DOPUNA_POSLATA", CHAR(1), default="N")
    procitano: Mapped[str] = mapped_column("PROCITANO", CHAR(1), default="D")
    datum_kreiranja: Mapped[datetime.datetime] = mapped_column("DATUM_KREIRANJA", TIMESTAMP(timezone=False))
    datum_izmene: Mapped[datetime.datetime] = mapped_column("DATUM_IZMENE", TIMESTAMP(timezone=False))
    datum_odgovora: Mapped[datetime.datetime | None] = mapped_column(
        "DATUM_ODGOVORA", TIMESTAMP(timezone=False), nullable=True
    )


class HrPoruka(Base):
    __tablename__ = "PULS_HR_PORUKE"

    id: Mapped[int] = mapped_column("ID", Numeric(19, 0), primary_key=True)
    pitanje_id: Mapped[int] = mapped_column("PITANJE_ID", Numeric(19, 0))
    autor: Mapped[str] = mapped_column("AUTOR", VARCHAR(20))
    korisnik_id: Mapped[int] = mapped_column("KORISNIK_ID", Numeric(19, 0))
    tekst: Mapped[str] = mapped_column("TEKST", NVARCHAR2(2000))
    datum_kreiranja: Mapped[datetime.datetime] = mapped_column("DATUM_KREIRANJA", TIMESTAMP(timezone=False))


class HrCestoPitanje(Base):
    __tablename__ = "PULS_HR_CESTA_PITANJA"

    id: Mapped[int] = mapped_column("ID", Numeric(19, 0), primary_key=True)
    kategorija_sifra: Mapped[str] = mapped_column("KATEGORIJA_SIFRA", VARCHAR(30))
    pitanje: Mapped[str] = mapped_column("PITANJE", NVARCHAR2(1000))
    odgovor: Mapped[str] = mapped_column("ODGOVOR", NVARCHAR2(2000))
    redosled: Mapped[int] = mapped_column("REDOSLED", Numeric(5, 0), default=0)
    aktivno: Mapped[str] = mapped_column("AKTIVNO", CHAR(1), default="D")
    izvor_pitanje_id: Mapped[int | None] = mapped_column("IZVOR_PITANJE_ID", Numeric(19, 0), nullable=True)
    kreirao_platni_broj: Mapped[str] = mapped_column("KREIRAO_PLATNI_BROJ", VARCHAR(30))
    izmenio_platni_broj: Mapped[str] = mapped_column("IZMENIO_PLATNI_BROJ", VARCHAR(30))
    datum_kreiranja: Mapped[datetime.datetime] = mapped_column("DATUM_KREIRANJA", TIMESTAMP(timezone=False))
    datum_izmene: Mapped[datetime.datetime] = mapped_column("DATUM_IZMENE", TIMESTAMP(timezone=False))
