import datetime

from sqlalchemy import TIMESTAMP, VARCHAR, Numeric
from sqlalchemy.dialects.oracle import NCLOB, NVARCHAR2
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class AnketaSekcija(Base):
    __tablename__ = "PULS_ANKETA_SEKCIJE"

    id: Mapped[int] = mapped_column("ID", Numeric(19, 0), primary_key=True)
    anketa_id: Mapped[int] = mapped_column("ANKETA_ID", Numeric(19, 0))
    naziv: Mapped[str] = mapped_column("NAZIV", NVARCHAR2(200))
    redosled: Mapped[int] = mapped_column("REDOSLED", Numeric(10, 0))
    datum_kreiranja: Mapped[datetime.datetime | None] = mapped_column(
        "DATUM_KREIRANJA", TIMESTAMP(timezone=False), nullable=True
    )
    datum_izmene: Mapped[datetime.datetime | None] = mapped_column(
        "DATUM_IZMENE", TIMESTAMP(timezone=False), nullable=True
    )


class AnketaPitanje(Base):
    __tablename__ = "PULS_ANKETA_PITANJA"

    id: Mapped[int] = mapped_column("ID", Numeric(19, 0), primary_key=True)
    sekcija_id: Mapped[int] = mapped_column("SEKCIJA_ID", Numeric(19, 0))
    tekst: Mapped[str] = mapped_column("TEKST", NCLOB)
    tip_pitanja: Mapped[str] = mapped_column("TIP_PITANJA", VARCHAR(20))
    obavezno: Mapped[str] = mapped_column("OBAVEZNO", VARCHAR(1), default="N")
    redosled: Mapped[int] = mapped_column("REDOSLED", Numeric(10, 0))
    uslov_pitanje_id: Mapped[int | None] = mapped_column(
        "USLOV_PITANJE_ID", Numeric(19, 0), nullable=True
    )
    uslov_operator: Mapped[str | None] = mapped_column("USLOV_OPERATOR", VARCHAR(20), nullable=True)
    datum_kreiranja: Mapped[datetime.datetime | None] = mapped_column(
        "DATUM_KREIRANJA", TIMESTAMP(timezone=False), nullable=True
    )
    datum_izmene: Mapped[datetime.datetime | None] = mapped_column(
        "DATUM_IZMENE", TIMESTAMP(timezone=False), nullable=True
    )

    @property
    def obavezno_bool(self) -> bool:
        return self.obavezno == "D"


class AnketaOpcija(Base):
    __tablename__ = "PULS_ANKETA_OPCIJE"

    id: Mapped[int] = mapped_column("ID", Numeric(19, 0), primary_key=True)
    pitanje_id: Mapped[int] = mapped_column("PITANJE_ID", Numeric(19, 0))
    tekst: Mapped[str] = mapped_column("TEKST", NVARCHAR2(500))
    redosled: Mapped[int] = mapped_column("REDOSLED", Numeric(10, 0))
    datum_kreiranja: Mapped[datetime.datetime | None] = mapped_column(
        "DATUM_KREIRANJA", TIMESTAMP(timezone=False), nullable=True
    )
    datum_izmene: Mapped[datetime.datetime | None] = mapped_column(
        "DATUM_IZMENE", TIMESTAMP(timezone=False), nullable=True
    )


class AnketaUslovVrednost(Base):
    __tablename__ = "PULS_ANKETA_USLOV_VREDNOSTI"

    id: Mapped[int] = mapped_column("ID", Numeric(19, 0), primary_key=True)
    pitanje_id: Mapped[int] = mapped_column("PITANJE_ID", Numeric(19, 0))
    vrednost: Mapped[str] = mapped_column("VREDNOST", VARCHAR(100))
    redosled: Mapped[int] = mapped_column("REDOSLED", Numeric(10, 0))


class AnketaCilj(Base):
    __tablename__ = "PULS_ANKETA_CILJEVI"

    id: Mapped[int] = mapped_column("ID", Numeric(19, 0), primary_key=True)
    anketa_id: Mapped[int] = mapped_column("ANKETA_ID", Numeric(19, 0))
    tip_cilja: Mapped[str] = mapped_column("TIP_CILJA", VARCHAR(20))
    vrednost: Mapped[str | None] = mapped_column("VREDNOST", VARCHAR(100), nullable=True)
    datum_kreiranja: Mapped[datetime.datetime | None] = mapped_column(
        "DATUM_KREIRANJA", TIMESTAMP(timezone=False), nullable=True
    )
    datum_izmene: Mapped[datetime.datetime | None] = mapped_column(
        "DATUM_IZMENE", TIMESTAMP(timezone=False), nullable=True
    )