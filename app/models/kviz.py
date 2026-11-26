"""Modul PULS IZAZOV (kviz) - sql/011_kviz_module.sql.

Bez ORM relationship-a (kao ostatak projekta): repozitorijum eksplicitno cita i
upisuje pitanja, opcije i ciljeve po KVIZ_ID / PITANJE_ID."""

import datetime

from sqlalchemy import CHAR, TIMESTAMP, VARCHAR, Numeric
from sqlalchemy.dialects.oracle import NVARCHAR2
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base

# --- Statusi kviza ---
KVIZ_STATUS_DRAFT = "DRAFT"
KVIZ_STATUS_OBJAVLJEN = "OBJAVLJEN"
KVIZ_STATUS_ARHIVIRAN = "ARHIVIRAN"
KVIZ_STATUSI = (KVIZ_STATUS_DRAFT, KVIZ_STATUS_OBJAVLJEN, KVIZ_STATUS_ARHIVIRAN)

# --- Ciljanje (bez redova = svi zaposleni kojima je modul ukljucen) ---
KVIZ_CILJ_ORGJED = "ORGJED"
KVIZ_CILJ_PLATNI_BROJ = "PLATNI_BROJ"
KVIZ_CILJ_TIPOVI = (KVIZ_CILJ_ORGJED, KVIZ_CILJ_PLATNI_BROJ)

# --- Statusi pokusaja ---
POKUSAJ_U_TOKU = "U_TOKU"
POKUSAJ_ZAVRSEN = "ZAVRSEN"
POKUSAJ_STATUSI = (POKUSAJ_U_TOKU, POKUSAJ_ZAVRSEN)

# --- Ogranicenja (iste vrednosti kao CHECK u bazi gde postoje) ---
TRAJANJE_MIN_SEKUNDI = 30
TRAJANJE_MAX_SEKUNDI = 900
TRAJANJE_PODRAZUMEVANO = 120
MAX_PITANJA = 10
MIN_OPCIJA = 2
MAX_OPCIJA = 4


class KvizKategorija(Base):
    __tablename__ = "PULS_KVIZ_KATEGORIJE"

    sifra: Mapped[str] = mapped_column("SIFRA", VARCHAR(30), primary_key=True)
    naziv: Mapped[str] = mapped_column("NAZIV", NVARCHAR2(100))
    redosled: Mapped[int] = mapped_column("REDOSLED", Numeric(5, 0), default=0)
    aktivna: Mapped[str] = mapped_column("AKTIVNA", CHAR(1), default="D")
    kreirao_platni_broj: Mapped[str] = mapped_column("KREIRAO_PLATNI_BROJ", VARCHAR(30))
    izmenio_platni_broj: Mapped[str] = mapped_column("IZMENIO_PLATNI_BROJ", VARCHAR(30))
    datum_kreiranja: Mapped[datetime.datetime] = mapped_column("DATUM_KREIRANJA", TIMESTAMP(timezone=False))
    datum_izmene: Mapped[datetime.datetime] = mapped_column("DATUM_IZMENE", TIMESTAMP(timezone=False))


class Kviz(Base):
    __tablename__ = "PULS_KVIZOVI"

    id: Mapped[int] = mapped_column("ID", Numeric(19, 0), primary_key=True)
    naziv: Mapped[str] = mapped_column("NAZIV", NVARCHAR2(200))
    opis: Mapped[str | None] = mapped_column("OPIS", NVARCHAR2(1000), nullable=True)
    datum_od: Mapped[datetime.datetime] = mapped_column("DATUM_OD", TIMESTAMP(timezone=False))
    datum_do: Mapped[datetime.datetime] = mapped_column("DATUM_DO", TIMESTAMP(timezone=False))
    trajanje_sekundi: Mapped[int] = mapped_column("TRAJANJE_SEKUNDI", Numeric(5, 0), default=TRAJANJE_PODRAZUMEVANO)
    status: Mapped[str] = mapped_column("STATUS", VARCHAR(20), default=KVIZ_STATUS_DRAFT)
    kreirao_platni_broj: Mapped[str] = mapped_column("KREIRAO_PLATNI_BROJ", VARCHAR(30))
    izmenio_platni_broj: Mapped[str] = mapped_column("IZMENIO_PLATNI_BROJ", VARCHAR(30))
    datum_objave: Mapped[datetime.datetime | None] = mapped_column(
        "DATUM_OBJAVE", TIMESTAMP(timezone=False), nullable=True
    )
    datum_kreiranja: Mapped[datetime.datetime] = mapped_column("DATUM_KREIRANJA", TIMESTAMP(timezone=False))
    datum_izmene: Mapped[datetime.datetime] = mapped_column("DATUM_IZMENE", TIMESTAMP(timezone=False))

    def is_open(self, now: datetime.datetime) -> bool:
        """Objavljen i u periodu: zaposleni moze da zapocne kviz."""
        return self.status == KVIZ_STATUS_OBJAVLJEN and self.datum_od <= now < self.datum_do


class KvizCilj(Base):
    __tablename__ = "PULS_KVIZ_CILJEVI"

    id: Mapped[int] = mapped_column("ID", Numeric(19, 0), primary_key=True)
    kviz_id: Mapped[int] = mapped_column("KVIZ_ID", Numeric(19, 0))
    tip_cilja: Mapped[str] = mapped_column("TIP_CILJA", VARCHAR(20))
    vrednost: Mapped[str] = mapped_column("VREDNOST", VARCHAR(50))


class KvizPitanje(Base):
    __tablename__ = "PULS_KVIZ_PITANJA"

    id: Mapped[int] = mapped_column("ID", Numeric(19, 0), primary_key=True)
    kviz_id: Mapped[int] = mapped_column("KVIZ_ID", Numeric(19, 0))
    redosled: Mapped[int] = mapped_column("REDOSLED", Numeric(3, 0))
    tekst: Mapped[str] = mapped_column("TEKST", NVARCHAR2(500))
    kategorija_sifra: Mapped[str] = mapped_column("KATEGORIJA_SIFRA", VARCHAR(30))
    slika_id: Mapped[int | None] = mapped_column("SLIKA_ID", Numeric(19, 0), nullable=True)
    objasnjenje: Mapped[str] = mapped_column("OBJASNJENJE", NVARCHAR2(500))


class KvizOpcija(Base):
    __tablename__ = "PULS_KVIZ_OPCIJE"

    id: Mapped[int] = mapped_column("ID", Numeric(19, 0), primary_key=True)
    pitanje_id: Mapped[int] = mapped_column("PITANJE_ID", Numeric(19, 0))
    redosled: Mapped[int] = mapped_column("REDOSLED", Numeric(3, 0))
    tekst: Mapped[str] = mapped_column("TEKST", NVARCHAR2(200))
    tacna: Mapped[str] = mapped_column("TACNA", CHAR(1), default="N")


class KvizPokusaj(Base):
    __tablename__ = "PULS_KVIZ_POKUSAJI"

    id: Mapped[int] = mapped_column("ID", Numeric(19, 0), primary_key=True)
    kviz_id: Mapped[int] = mapped_column("KVIZ_ID", Numeric(19, 0))
    korisnik_id: Mapped[int] = mapped_column("KORISNIK_ID", Numeric(19, 0))
    orgjed_sifra: Mapped[str | None] = mapped_column("ORGJED_SIFRA", VARCHAR(50), nullable=True)
    status: Mapped[str] = mapped_column("STATUS", VARCHAR(20), default=POKUSAJ_U_TOKU)
    datum_pocetka: Mapped[datetime.datetime] = mapped_column("DATUM_POCETKA", TIMESTAMP(timezone=False))
    datum_zavrsetka: Mapped[datetime.datetime | None] = mapped_column(
        "DATUM_ZAVRSETKA", TIMESTAMP(timezone=False), nullable=True
    )
    broj_tacnih: Mapped[int] = mapped_column("BROJ_TACNIH", Numeric(3, 0), default=0)
    trajanje_ms: Mapped[int | None] = mapped_column("TRAJANJE_MS", Numeric(10, 0), nullable=True)


class KvizOdgovor(Base):
    __tablename__ = "PULS_KVIZ_ODGOVORI"

    id: Mapped[int] = mapped_column("ID", Numeric(19, 0), primary_key=True)
    pokusaj_id: Mapped[int] = mapped_column("POKUSAJ_ID", Numeric(19, 0))
    pitanje_id: Mapped[int] = mapped_column("PITANJE_ID", Numeric(19, 0))
    opcija_id: Mapped[int] = mapped_column("OPCIJA_ID", Numeric(19, 0))
    tacan: Mapped[str] = mapped_column("TACAN", CHAR(1))
    datum_odgovora: Mapped[datetime.datetime] = mapped_column("DATUM_ODGOVORA", TIMESTAMP(timezone=False))
