import datetime

from sqlalchemy import CHAR, TIMESTAMP, Numeric
from sqlalchemy.dialects.oracle import NCLOB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class AnketaPredaja(Base):
    """Finalna predaja. Kod anonimne ankete KORISNIK_ID je NULL (snapshot ANONIMNA)."""

    __tablename__ = "PULS_ANKETA_PREDAJE"

    id: Mapped[int] = mapped_column("ID", Numeric(19, 0), primary_key=True)
    anketa_id: Mapped[int] = mapped_column("ANKETA_ID", Numeric(19, 0))
    anonimna: Mapped[str] = mapped_column("ANONIMNA", CHAR(1))
    korisnik_id: Mapped[int | None] = mapped_column("KORISNIK_ID", Numeric(19, 0), nullable=True)
    datum_predaje: Mapped[datetime.datetime | None] = mapped_column(
        "DATUM_PREDAJE", TIMESTAMP(timezone=False), nullable=True
    )


class AnketaOdgovor(Base):
    __tablename__ = "PULS_ANKETA_ODGOVORI"

    id: Mapped[int] = mapped_column("ID", Numeric(19, 0), primary_key=True)
    predaja_id: Mapped[int] = mapped_column("PREDAJA_ID", Numeric(19, 0))
    pitanje_id: Mapped[int] = mapped_column("PITANJE_ID", Numeric(19, 0))
    tekst: Mapped[str | None] = mapped_column("TEKST", NCLOB, nullable=True)
    broj: Mapped[int | None] = mapped_column("BROJ", Numeric(10, 0), nullable=True)
    logicka: Mapped[str | None] = mapped_column("LOGICKA", CHAR(1), nullable=True)


class AnketaOdgovorOpcija(Base):
    __tablename__ = "PULS_ANKETA_ODGOVOR_OPCIJE"

    id: Mapped[int] = mapped_column("ID", Numeric(19, 0), primary_key=True)
    odgovor_id: Mapped[int] = mapped_column("ODGOVOR_ID", Numeric(19, 0))
    opcija_id: Mapped[int] = mapped_column("OPCIJA_ID", Numeric(19, 0))