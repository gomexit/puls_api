from sqlalchemy import VARCHAR
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class IisOrgjed(Base):
    """Read-only spoljni Oracle sifrarnik organizacionih jedinica (IIS shema).
    Nema ORM write operacija - samo SELECT za obogacivanje /auth/me odgovora."""

    __tablename__ = "ORGJED"
    __table_args__ = {"schema": "IIS"}

    sifra: Mapped[str] = mapped_column("SIFRA", VARCHAR(8), primary_key=True)
    naziv: Mapped[str] = mapped_column("NAZIV", VARCHAR(60))
