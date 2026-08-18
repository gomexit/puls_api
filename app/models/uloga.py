from sqlalchemy import CHAR, VARCHAR, Numeric
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class Uloga(Base):
    __tablename__ = "PULS_ULOGE"

    id: Mapped[int] = mapped_column("ID", Numeric(19, 0), primary_key=True)
    sifra: Mapped[str] = mapped_column("SIFRA", VARCHAR(50))
    naziv: Mapped[str] = mapped_column("NAZIV", VARCHAR(200))
    opis: Mapped[str | None] = mapped_column("OPIS", VARCHAR(500), nullable=True)
    aktivna: Mapped[str] = mapped_column("AKTIVNA", CHAR(1), default="D")
