import datetime

from sqlalchemy import CHAR, TIMESTAMP, VARCHAR, Numeric
from sqlalchemy.dialects.oracle import NCLOB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.models.anketa import UCESCE_NOT_STARTED


class AnketaUcesce(Base):
    """Cinjenica da je korisnik dobio/zapoceo/predao anketu. NEMA vezu ka predaji."""

    __tablename__ = "PULS_ANKETA_UCESCA"

    id: Mapped[int] = mapped_column("ID", Numeric(19, 0), primary_key=True)
    anketa_id: Mapped[int] = mapped_column("ANKETA_ID", Numeric(19, 0))
    korisnik_id: Mapped[int] = mapped_column("KORISNIK_ID", Numeric(19, 0))
    status: Mapped[str] = mapped_column("STATUS", VARCHAR(20), default=UCESCE_NOT_STARTED)
    datum_pocetka: Mapped[datetime.datetime | None] = mapped_column(
        "DATUM_POCETKA", TIMESTAMP(timezone=False), nullable=True
    )
    datum_predaje: Mapped[datetime.datetime | None] = mapped_column(
        "DATUM_PREDAJE", TIMESTAMP(timezone=False), nullable=True
    )
    datum_kreiranja: Mapped[datetime.datetime | None] = mapped_column(
        "DATUM_KREIRANJA", TIMESTAMP(timezone=False), nullable=True
    )
    datum_izmene: Mapped[datetime.datetime | None] = mapped_column(
        "DATUM_IZMENE", TIMESTAMP(timezone=False), nullable=True
    )


class AnketaNacrtOdgovor(Base):
    __tablename__ = "PULS_ANKETA_NACRT_ODGOVORI"

    id: Mapped[int] = mapped_column("ID", Numeric(19, 0), primary_key=True)
    anketa_id: Mapped[int] = mapped_column("ANKETA_ID", Numeric(19, 0))
    korisnik_id: Mapped[int] = mapped_column("KORISNIK_ID", Numeric(19, 0))
    pitanje_id: Mapped[int] = mapped_column("PITANJE_ID", Numeric(19, 0))
    tekst: Mapped[str | None] = mapped_column("TEKST", NCLOB, nullable=True)
    broj: Mapped[int | None] = mapped_column("BROJ", Numeric(10, 0), nullable=True)
    logicka: Mapped[str | None] = mapped_column("LOGICKA", CHAR(1), nullable=True)
    datum_kreiranja: Mapped[datetime.datetime | None] = mapped_column(
        "DATUM_KREIRANJA", TIMESTAMP(timezone=False), nullable=True
    )
    datum_izmene: Mapped[datetime.datetime | None] = mapped_column(
        "DATUM_IZMENE", TIMESTAMP(timezone=False), nullable=True
    )


class AnketaNacrtOpcija(Base):
    __tablename__ = "PULS_ANKETA_NACRT_OPCIJE"

    id: Mapped[int] = mapped_column("ID", Numeric(19, 0), primary_key=True)
    nacrt_odgovor_id: Mapped[int] = mapped_column("NACRT_ODGOVOR_ID", Numeric(19, 0))
    opcija_id: Mapped[int] = mapped_column("OPCIJA_ID", Numeric(19, 0))