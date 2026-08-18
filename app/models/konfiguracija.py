from sqlalchemy import CHAR, VARCHAR, Numeric
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class Konfiguracija(Base):
    __tablename__ = "PULS_KONFIGURACIJA"

    kljuc: Mapped[str] = mapped_column("KLJUC", VARCHAR(100), primary_key=True)
    vrednost: Mapped[str | None] = mapped_column("VREDNOST", VARCHAR(4000), nullable=True)
    tip_podatka: Mapped[str] = mapped_column("TIP_PODATKA", VARCHAR(20))
    opis: Mapped[str | None] = mapped_column("OPIS", VARCHAR(500), nullable=True)
    aktivna: Mapped[str] = mapped_column("AKTIVNA", CHAR(1), default="D")
    izmenio_korisnik_id: Mapped[int | None] = mapped_column("IZMENIO_KORISNIK_ID", Numeric(19, 0), nullable=True)
