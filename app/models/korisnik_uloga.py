import datetime

from sqlalchemy import TIMESTAMP, Numeric
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class KorisnikUloga(Base):
    __tablename__ = "PULS_KORISNIK_ULOGE"

    korisnik_id: Mapped[int] = mapped_column("KORISNIK_ID", Numeric(19, 0), primary_key=True)
    uloga_id: Mapped[int] = mapped_column("ULOGA_ID", Numeric(19, 0), primary_key=True)
    dodelio_korisnik_id: Mapped[int | None] = mapped_column("DODELIO_KORISNIK_ID", Numeric(19, 0), nullable=True)
    datum_dodele: Mapped[datetime.datetime | None] = mapped_column(
        "DATUM_DODELE", TIMESTAMP(timezone=False), nullable=True
    )
