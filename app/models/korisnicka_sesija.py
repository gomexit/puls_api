import datetime

from sqlalchemy import CHAR, TIMESTAMP, VARCHAR, Numeric
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class KorisnickaSesija(Base):
    __tablename__ = "PULS_KORISNICKE_SESIJE"

    id: Mapped[int] = mapped_column("ID", Numeric(19, 0), primary_key=True)
    korisnik_id: Mapped[int] = mapped_column("KORISNIK_ID", Numeric(19, 0))
    token_hash: Mapped[str] = mapped_column("TOKEN_HASH", VARCHAR(128))
    uredjaj_id: Mapped[str] = mapped_column("UREDJAJ_ID", VARCHAR(255))
    naziv_uredjaja: Mapped[str | None] = mapped_column("NAZIV_UREDJAJA", VARCHAR(255), nullable=True)
    aktivna: Mapped[str] = mapped_column("AKTIVNA", CHAR(1), default="D")
    datum_izdavanja: Mapped[datetime.datetime | None] = mapped_column(
        "DATUM_IZDAVANJA", TIMESTAMP(timezone=False), nullable=True
    )
    datum_isteka: Mapped[datetime.datetime | None] = mapped_column(
        "DATUM_ISTEKA", TIMESTAMP(timezone=False), nullable=True
    )
    datum_ponistavanja: Mapped[datetime.datetime | None] = mapped_column(
        "DATUM_PONISTAVANJA", TIMESTAMP(timezone=False), nullable=True
    )
    razlog_ponistavanja: Mapped[str | None] = mapped_column("RAZLOG_PONISTAVANJA", VARCHAR(100), nullable=True)
    poslednja_aktivnost: Mapped[datetime.datetime | None] = mapped_column(
        "POSLEDNJA_AKTIVNOST", TIMESTAMP(timezone=False), nullable=True
    )
    ip_adresa: Mapped[str | None] = mapped_column("IP_ADRESA", VARCHAR(50), nullable=True)
    korisnicki_agent: Mapped[str | None] = mapped_column("KORISNICKI_AGENT", VARCHAR(500), nullable=True)
    datum_kreiranja: Mapped[datetime.datetime | None] = mapped_column(
        "DATUM_KREIRANJA", TIMESTAMP(timezone=False), nullable=True
    )
