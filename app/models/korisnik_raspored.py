import datetime

from sqlalchemy import CHAR, DATE, TIMESTAMP, VARCHAR, Numeric
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class KorisnikRaspored(Base):
    __tablename__ = "PULS_KORISNIK_RASPOREDI"

    id: Mapped[int] = mapped_column("ID", Numeric(19, 0), primary_key=True)
    korisnik_id: Mapped[int] = mapped_column("KORISNIK_ID", Numeric(19, 0))
    orgjed_sifra: Mapped[str] = mapped_column("ORGJED_SIFRA", VARCHAR(50))
    radno_mesto_sifra: Mapped[str | None] = mapped_column("RADNO_MESTO_SIFRA", VARCHAR(50), nullable=True)
    primarni: Mapped[str] = mapped_column("PRIMARNI", CHAR(1), default="N")
    aktivan: Mapped[str] = mapped_column("AKTIVAN", CHAR(1), default="D")
    datum_od: Mapped[datetime.date | None] = mapped_column("DATUM_OD", DATE, nullable=True)
    datum_do: Mapped[datetime.date | None] = mapped_column("DATUM_DO", DATE, nullable=True)
    datum_sinhronizacije: Mapped[datetime.datetime | None] = mapped_column(
        "DATUM_SINHRONIZACIJE", TIMESTAMP(timezone=False), nullable=True
    )
