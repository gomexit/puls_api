import datetime

from sqlalchemy import BLOB, CHAR, TIMESTAMP, VARCHAR, Numeric
from sqlalchemy.dialects.oracle import NVARCHAR2
from sqlalchemy.orm import Mapped, deferred, mapped_column

from app.db.session import Base

# --- Statusi slike (sql/010_osnova_module.sql) ---
SLIKA_STATUS_AKTIVNA = "AKTIVNA"
SLIKA_STATUS_ARHIVIRANA = "ARHIVIRANA"
SLIKA_STATUSI = (SLIKA_STATUS_AKTIVNA, SLIKA_STATUS_ARHIVIRANA)

SLIKA_MIME_JPEG = "image/jpeg"
SLIKA_MIME_PNG = "image/png"
SLIKA_MIME_TIPOVI = (SLIKA_MIME_JPEG, SLIKA_MIME_PNG)

# Najveca dimenzija sacuvane slike (CK_SLIKE_DIMENZIJE u bazi).
SLIKA_MAX_DIMENZIJA = 1200


class Slika(Base):
    """PULS_SLIKE - slika cuvana kao BLOB (logo partnera, slika pitanja u kvizu...).

    Slika je nepromenljiva: posle upload-a menja se samo STATUS. SADRZAJ je `deferred`
    i cita se samo u content endpointima; liste i detalji selektuju metadata kolone."""

    __tablename__ = "PULS_SLIKE"

    id: Mapped[int] = mapped_column("ID", Numeric(19, 0), primary_key=True)
    naziv: Mapped[str] = mapped_column("NAZIV", NVARCHAR2(200))
    originalni_naziv_fajla: Mapped[str] = mapped_column("ORIGINALNI_NAZIV_FAJLA", NVARCHAR2(255))
    mime_tip: Mapped[str] = mapped_column("MIME_TIP", VARCHAR(50))
    velicina_bajtova: Mapped[int] = mapped_column("VELICINA_BAJTOVA", Numeric(12, 0))
    sirina: Mapped[int] = mapped_column("SIRINA", Numeric(5, 0))
    visina: Mapped[int] = mapped_column("VISINA", Numeric(5, 0))
    sha256: Mapped[str] = mapped_column("SHA256", CHAR(64))
    sadrzaj: Mapped[bytes] = deferred(mapped_column("SADRZAJ", BLOB))
    status: Mapped[str] = mapped_column("STATUS", VARCHAR(20), default=SLIKA_STATUS_AKTIVNA)
    kreirao_platni_broj: Mapped[str] = mapped_column("KREIRAO_PLATNI_BROJ", VARCHAR(30))
    izmenio_platni_broj: Mapped[str] = mapped_column("IZMENIO_PLATNI_BROJ", VARCHAR(30))
    datum_kreiranja: Mapped[datetime.datetime] = mapped_column(
        "DATUM_KREIRANJA", TIMESTAMP(timezone=False)
    )
    datum_izmene: Mapped[datetime.datetime] = mapped_column(
        "DATUM_IZMENE", TIMESTAMP(timezone=False)
    )
