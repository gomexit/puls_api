import datetime

from sqlalchemy import CLOB, TIMESTAMP, VARCHAR, Numeric
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class AuditLog(Base):
    __tablename__ = "PULS_AUDIT_LOG"

    id: Mapped[int] = mapped_column("ID", Numeric(19, 0), primary_key=True)
    korisnik_id: Mapped[int | None] = mapped_column("KORISNIK_ID", Numeric(19, 0), nullable=True)
    platni_broj: Mapped[str | None] = mapped_column("PLATNI_BROJ", VARCHAR(30), nullable=True)
    sifra_akcije: Mapped[str] = mapped_column("SIFRA_AKCIJE", VARCHAR(100))
    tip_entiteta: Mapped[str | None] = mapped_column("TIP_ENTITETA", VARCHAR(100), nullable=True)
    entitet_id: Mapped[str | None] = mapped_column("ENTITET_ID", VARCHAR(50), nullable=True)
    izvor: Mapped[str] = mapped_column("IZVOR", VARCHAR(20))
    detalji: Mapped[str | None] = mapped_column("DETALJI", CLOB, nullable=True)
    ip_adresa: Mapped[str | None] = mapped_column("IP_ADRESA", VARCHAR(50), nullable=True)
    korisnicki_agent: Mapped[str | None] = mapped_column("KORISNICKI_AGENT", VARCHAR(500), nullable=True)
    datum_kreiranja: Mapped[datetime.datetime | None] = mapped_column(
        "DATUM_KREIRANJA", TIMESTAMP(timezone=False), nullable=True
    )
