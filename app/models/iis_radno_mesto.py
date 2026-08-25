from sqlalchemy import VARCHAR, Numeric
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class IisRadnoMesto(Base):
    """Read-only spoljni Oracle sifrarnik radnih mesta (IIS shema).
    Nema ORM write operacija - samo SELECT za obogacivanje /auth/me odgovora."""

    __tablename__ = "RADNAMESTA"
    __table_args__ = {"schema": "IIS"}

    sifra: Mapped[int] = mapped_column("SIFRA", Numeric(19, 0), primary_key=True)
    naziv: Mapped[str] = mapped_column("NAZIV", VARCHAR(80))
