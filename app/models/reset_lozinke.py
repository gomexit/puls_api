import datetime

from sqlalchemy import CHAR, TIMESTAMP, VARCHAR, Integer, Numeric
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class ResetLozinke(Base):
    __tablename__ = "PULS_RESET_LOZINKE"

    id: Mapped[int] = mapped_column("ID", Numeric(19, 0), primary_key=True)
    korisnik_id: Mapped[int] = mapped_column("KORISNIK_ID", Numeric(19, 0))
    kod_hash: Mapped[str] = mapped_column("KOD_HASH", VARCHAR(128))
    aktivan: Mapped[str] = mapped_column("AKTIVAN", CHAR(1), default="D")
    broj_pokusaja: Mapped[int] = mapped_column("BROJ_POKUSAJA", Integer, default=0)
    datum_zahteva: Mapped[datetime.datetime | None] = mapped_column(
        "DATUM_ZAHTEVA", TIMESTAMP(timezone=False), nullable=True
    )
    datum_isteka: Mapped[datetime.datetime | None] = mapped_column(
        "DATUM_ISTEKA", TIMESTAMP(timezone=False), nullable=True
    )
    datum_koriscenja: Mapped[datetime.datetime | None] = mapped_column(
        "DATUM_KORISCENJA", TIMESTAMP(timezone=False), nullable=True
    )
    ip_adresa: Mapped[str | None] = mapped_column("IP_ADRESA", VARCHAR(50), nullable=True)
    datum_kreiranja: Mapped[datetime.datetime | None] = mapped_column(
        "DATUM_KREIRANJA", TIMESTAMP(timezone=False), nullable=True
    )
