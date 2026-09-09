import datetime

from sqlalchemy import CHAR, DATE, TIMESTAMP, VARCHAR, Integer, Numeric
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base

STATUS_ZAPOSLENJA_AKTIVAN = "AKTIVAN"
STATUS_ZAPOSLENJA_NEAKTIVAN = "NEAKTIVAN"

STATUS_NALOGA_OMOGUCEN = "OMOGUCEN"
STATUS_NALOGA_ONEMOGUCEN = "ONEMOGUCEN"


class Korisnik(Base):
    __tablename__ = "PULS_KORISNICI"

    id: Mapped[int] = mapped_column("ID", Numeric(19, 0), primary_key=True)
    platni_broj: Mapped[str] = mapped_column("PLATNI_BROJ", VARCHAR(30))
    ime: Mapped[str] = mapped_column("IME", VARCHAR(100))
    prezime: Mapped[str] = mapped_column("PREZIME", VARCHAR(100))
    broj_telefona: Mapped[str | None] = mapped_column("BROJ_TELEFONA", VARCHAR(30), nullable=True)
    lozinka_hash: Mapped[str | None] = mapped_column("LOZINKA_HASH", VARCHAR(255), nullable=True)

    status_zaposlenja: Mapped[str] = mapped_column("STATUS_ZAPOSLENJA", VARCHAR(20))
    status_naloga: Mapped[str] = mapped_column("STATUS_NALOGA", VARCHAR(20))

    obavezna_promena_lozinke: Mapped[str] = mapped_column("OBAVEZNA_PROMENA_LOZINKE", CHAR(1), default="D")
    telefon_potvrdjen: Mapped[str] = mapped_column("TELEFON_POTVRDJEN", CHAR(1), default="N")

    broj_neuspesnih_prijava: Mapped[int] = mapped_column("BROJ_NEUSPESNIH_PRIJAVA", Integer, default=0)

    zakljucan: Mapped[str] = mapped_column("ZAKLJUCAN", CHAR(1), default="N")
    datum_zakljucavanja: Mapped[datetime.datetime | None] = mapped_column(
        "DATUM_ZAKLJUCAVANJA", TIMESTAMP(timezone=False), nullable=True
    )

    datum_promene_lozinke: Mapped[datetime.datetime | None] = mapped_column(
        "DATUM_PROMENE_LOZINKE", TIMESTAMP(timezone=False), nullable=True
    )
    datum_potvrde_telefona: Mapped[datetime.datetime | None] = mapped_column(
        "DATUM_POTVRDE_TELEFONA", TIMESTAMP(timezone=False), nullable=True
    )
    datum_aktivacije: Mapped[datetime.datetime | None] = mapped_column(
        "DATUM_AKTIVACIJE", TIMESTAMP(timezone=False), nullable=True
    )
    datum_slanja_prve_lozinke: Mapped[datetime.datetime | None] = mapped_column(
        "DATUM_SLANJA_PRVE_LOZINKE", TIMESTAMP(timezone=False), nullable=True
    )
    datum_poslednje_prijave: Mapped[datetime.datetime | None] = mapped_column(
        "DATUM_POSLEDNJE_PRIJAVE", TIMESTAMP(timezone=False), nullable=True
    )
    datum_sinhronizacije: Mapped[datetime.datetime | None] = mapped_column(
        "DATUM_SINHRONIZACIJE", TIMESTAMP(timezone=False), nullable=True
    )
    datum_kreiranja: Mapped[datetime.datetime | None] = mapped_column(
        "DATUM_KREIRANJA", TIMESTAMP(timezone=False), nullable=True
    )
    datum_izmene: Mapped[datetime.datetime | None] = mapped_column(
        "DATUM_IZMENE", TIMESTAMP(timezone=False), nullable=True
    )
    # Prvo zaposlenje ikada - MIN(TRUNC(DATUMOD)) iz HR.UGOVOR_RADNO_MESTO, sinhronizovano
    # od strane PULS_SINHRONIZUJ_KORISNIKE. Nullable dok se ne izracuna/sinhronizuje.
    datum_zaposlenja: Mapped[datetime.date | None] = mapped_column(
        "DATUM_ZAPOSLENJA", DATE, nullable=True
    )

    def is_eligible_to_login(self) -> bool:
        return (
            self.status_zaposlenja == STATUS_ZAPOSLENJA_AKTIVAN
            and self.status_naloga == STATUS_NALOGA_OMOGUCEN
            and self.zakljucan == "N"
            and self.lozinka_hash is not None
        )
