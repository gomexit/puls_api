import datetime

from sqlalchemy import CHAR, DATE, TIMESTAMP, VARCHAR, Integer, Numeric
from sqlalchemy.dialects.oracle import NCLOB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.models.anketa import UCESCE_NOT_STARTED


class AnketaUcesce(Base):
    """Cinjenica da je korisnik dobio/zapoceo/predao anketu. NEMA vezu ka predaji."""

    __tablename__ = "PULS_ANKETA_UCESCA"

    id: Mapped[int] = mapped_column("ID", Numeric(19, 0), primary_key=True)
    anketa_id: Mapped[int] = mapped_column("ANKETA_ID", Numeric(19, 0))
    korisnik_id: Mapped[int] = mapped_column("KORISNIK_ID", Numeric(19, 0))
    status: Mapped[str] = mapped_column("STATUS", VARCHAR(20), default=UCESCE_NOT_STARTED)
    datum_pocetka: Mapped[datetime.datetime | None] = mapped_column(
        "DATUM_POCETKA", TIMESTAMP(timezone=False), nullable=True
    )
    datum_predaje: Mapped[datetime.datetime | None] = mapped_column(
        "DATUM_PREDAJE", TIMESTAMP(timezone=False), nullable=True
    )
    datum_kreiranja: Mapped[datetime.datetime | None] = mapped_column(
        "DATUM_KREIRANJA", TIMESTAMP(timezone=False), nullable=True
    )
    datum_izmene: Mapped[datetime.datetime | None] = mapped_column(
        "DATUM_IZMENE", TIMESTAMP(timezone=False), nullable=True
    )
    # Automatsko (onboarding) ucesce - sve cetiri kolone ispod su NULL kod obicnog
    # (rucno dodeljenog) ucesca i popunjene ZAJEDNO kod automatskog (CK_ANKETA_UCESCA_AUTOMATIKA).
    automatika_id: Mapped[int | None] = mapped_column("AUTOMATIKA_ID", Numeric(19, 0), nullable=True)
    datum_dostupnosti: Mapped[datetime.datetime | None] = mapped_column(
        "DATUM_DOSTUPNOSTI", TIMESTAMP(timezone=False), nullable=True
    )
    datum_isteka: Mapped[datetime.datetime | None] = mapped_column(
        "DATUM_ISTEKA", TIMESTAMP(timezone=False), nullable=True
    )
    datum_zaposlenja_snapshot: Mapped[datetime.date | None] = mapped_column(
        "DATUM_ZAPOSLENJA_SNAPSHOT", DATE, nullable=True
    )

    @property
    def is_automatsko(self) -> bool:
        return self.automatika_id is not None

    def is_dostupno_sada(self, now: datetime.datetime) -> bool:
        """Za automatsko ucesce: [DATUM_DOSTUPNOSTI, DATUM_ISTEKA) - istice na pocetku
        osmog dana, ne diranjem statusa same ankete (proverava se odvojeno)."""
        if not self.is_automatsko:
            return True
        return self.datum_dostupnosti <= now < self.datum_isteka


class AnketaAutomatika(Base):
    """PULS_ANKETA_AUTOMATIKA - pravilo automatske dodele jedne ankete na milestone
    (7/30/60/90 dana od DATUM_ZAPOSLENJA). Jedna anketa = najvise jedno pravilo
    (UNIQUE ANKETA_ID). Najvise jedno AKTIVNA='D' pravilo po milestone-u je zasticeno
    function-based unique indeksom (UX_ANKETA_AUTOMATIKA_AKTIVNA_MILESTONE) - istorijska
    neaktivna pravila ostaju u tabeli."""

    __tablename__ = "PULS_ANKETA_AUTOMATIKA"

    id: Mapped[int] = mapped_column("ID", Numeric(19, 0), primary_key=True)
    anketa_id: Mapped[int] = mapped_column("ANKETA_ID", Numeric(19, 0))
    dani_od_zaposlenja: Mapped[int] = mapped_column("DANI_OD_ZAPOSLENJA", Integer)
    rok_dana: Mapped[int] = mapped_column("ROK_DANA", Integer, default=7)
    datum_primene_od: Mapped[datetime.date] = mapped_column("DATUM_PRIMENE_OD", DATE)
    aktivna: Mapped[str] = mapped_column("AKTIVNA", CHAR(1), default="N")
    datum_kreiranja: Mapped[datetime.datetime | None] = mapped_column(
        "DATUM_KREIRANJA", TIMESTAMP(timezone=False), nullable=True
    )
    datum_izmene: Mapped[datetime.datetime | None] = mapped_column(
        "DATUM_IZMENE", TIMESTAMP(timezone=False), nullable=True
    )

    @property
    def is_aktivna(self) -> bool:
        return self.aktivna == "D"


class AnketaNacrtOdgovor(Base):
    __tablename__ = "PULS_ANKETA_NACRT_ODGOVORI"

    id: Mapped[int] = mapped_column("ID", Numeric(19, 0), primary_key=True)
    anketa_id: Mapped[int] = mapped_column("ANKETA_ID", Numeric(19, 0))
    korisnik_id: Mapped[int] = mapped_column("KORISNIK_ID", Numeric(19, 0))
    pitanje_id: Mapped[int] = mapped_column("PITANJE_ID", Numeric(19, 0))
    tekst: Mapped[str | None] = mapped_column("TEKST", NCLOB, nullable=True)
    broj: Mapped[int | None] = mapped_column("BROJ", Numeric(10, 0), nullable=True)
    logicka: Mapped[str | None] = mapped_column("LOGICKA", CHAR(1), nullable=True)
    datum_kreiranja: Mapped[datetime.datetime | None] = mapped_column(
        "DATUM_KREIRANJA", TIMESTAMP(timezone=False), nullable=True
    )
    datum_izmene: Mapped[datetime.datetime | None] = mapped_column(
        "DATUM_IZMENE", TIMESTAMP(timezone=False), nullable=True
    )


class AnketaNacrtOpcija(Base):
    __tablename__ = "PULS_ANKETA_NACRT_OPCIJE"

    id: Mapped[int] = mapped_column("ID", Numeric(19, 0), primary_key=True)
    nacrt_odgovor_id: Mapped[int] = mapped_column("NACRT_ODGOVOR_ID", Numeric(19, 0))
    opcija_id: Mapped[int] = mapped_column("OPCIJA_ID", Numeric(19, 0))