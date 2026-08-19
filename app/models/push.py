import datetime

from sqlalchemy import CHAR, TIMESTAMP, VARCHAR, Numeric
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base

# --- Statusi push isporuke ---
PUSH_STATUS_PENDING = "PENDING"
PUSH_STATUS_SENT = "SENT"        # FCM prihvatio poruku (NIJE potvrda dostave uredjaju)
PUSH_STATUS_FAILED = "FAILED"
PUSH_STATUS_SKIPPED = "SKIPPED"

PUSH_STATUSI = (PUSH_STATUS_PENDING, PUSH_STATUS_SENT, PUSH_STATUS_FAILED, PUSH_STATUS_SKIPPED)


class PushToken(Base):
    __tablename__ = "PULS_PUSH_TOKENI"

    id: Mapped[int] = mapped_column("ID", Numeric(19, 0), primary_key=True)
    korisnik_id: Mapped[int] = mapped_column("KORISNIK_ID", Numeric(19, 0))
    uredjaj_id: Mapped[str] = mapped_column("UREDJAJ_ID", VARCHAR(255))
    # Tajna vrednost - nikada se ne loguje niti vraca u API response.
    fcm_token: Mapped[str] = mapped_column("FCM_TOKEN", VARCHAR(4000))
    token_hash: Mapped[str] = mapped_column("TOKEN_HASH", VARCHAR(64))
    aktivan: Mapped[str] = mapped_column("AKTIVAN", CHAR(1), default="D")
    app_version: Mapped[str | None] = mapped_column("APP_VERSION", VARCHAR(50), nullable=True)
    datum_kreiranja: Mapped[datetime.datetime | None] = mapped_column(
        "DATUM_KREIRANJA", TIMESTAMP(timezone=False), nullable=True
    )
    datum_izmene: Mapped[datetime.datetime | None] = mapped_column(
        "DATUM_IZMENE", TIMESTAMP(timezone=False), nullable=True
    )
    datum_poslednje_registracije: Mapped[datetime.datetime | None] = mapped_column(
        "DATUM_POSLEDNJE_REGISTRACIJE", TIMESTAMP(timezone=False), nullable=True
    )
    datum_deaktivacije: Mapped[datetime.datetime | None] = mapped_column(
        "DATUM_DEAKTIVACIJE", TIMESTAMP(timezone=False), nullable=True
    )


class PushIsporuka(Base):
    __tablename__ = "PULS_PUSH_ISPORUKE"

    id: Mapped[int] = mapped_column("ID", Numeric(19, 0), primary_key=True)
    obavestenje_id: Mapped[int] = mapped_column("OBAVESTENJE_ID", Numeric(19, 0))
    korisnik_id: Mapped[int] = mapped_column("KORISNIK_ID", Numeric(19, 0))
    status: Mapped[str] = mapped_column("STATUS", VARCHAR(20), default=PUSH_STATUS_PENDING)
    broj_pokusaja: Mapped[int] = mapped_column("BROJ_POKUSAJA", Numeric(10, 0), default=0)
    datum_sledeceg_pokusaja: Mapped[datetime.datetime | None] = mapped_column(
        "DATUM_SLEDECEG_POKUSAJA", TIMESTAMP(timezone=False), nullable=True
    )
    # Samo bezbedan FCM kod greske - bez tokena/tajni.
    poslednji_error_code: Mapped[str | None] = mapped_column(
        "POSLEDNJI_ERROR_CODE", VARCHAR(100), nullable=True
    )
    datum_kreiranja: Mapped[datetime.datetime | None] = mapped_column(
        "DATUM_KREIRANJA", TIMESTAMP(timezone=False), nullable=True
    )
    datum_poslednjeg_pokusaja: Mapped[datetime.datetime | None] = mapped_column(
        "DATUM_POSLEDNJEG_POKUSAJA", TIMESTAMP(timezone=False), nullable=True
    )
    datum_slanja: Mapped[datetime.datetime | None] = mapped_column(
        "DATUM_SLANJA", TIMESTAMP(timezone=False), nullable=True
    )
    broj_ponovnih_slanja: Mapped[int] = mapped_column("BROJ_PONOVNIH_SLANJA", Numeric(10, 0), default=0)
