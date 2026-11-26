"""GOMEX PUTANJA - upiti nad PULS_IGRA_* (bez ORM relationship-a)."""

import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.igra import REZULTAT_RESEN, IgraNivo, IgraRezultat
from app.models.korisnik_raspored import KorisnikRaspored


class GameRepository:
    def __init__(self, db: Session):
        self.db = db

    # ================================================================== nivoi
    def get_level(self, datum: datetime.date) -> IgraNivo | None:
        stmt = select(IgraNivo).where(IgraNivo.datum == datum)
        return self.db.execute(stmt).scalars().first()

    def add_level(self, nivo: IgraNivo) -> IgraNivo:
        self.db.add(nivo)
        self.db.flush()
        return nivo

    # ============================================================== rezultati
    def get_result(self, nivo_id: int, korisnik_id: int) -> IgraRezultat | None:
        stmt = select(IgraRezultat).where(IgraRezultat.nivo_id == nivo_id, IgraRezultat.korisnik_id == korisnik_id)
        return self.db.execute(stmt).scalars().first()

    def get_result_for_update(self, nivo_id: int, korisnik_id: int) -> IgraRezultat | None:
        stmt = (
            select(IgraRezultat)
            .where(IgraRezultat.nivo_id == nivo_id, IgraRezultat.korisnik_id == korisnik_id)
            .with_for_update()
        )
        return self.db.execute(stmt).scalars().first()

    def add_result(self, rezultat: IgraRezultat) -> IgraRezultat:
        self.db.add(rezultat)
        self.db.flush()
        return rezultat

    def primary_orgjed(self, korisnik_id: int) -> str | None:
        stmt = (
            select(KorisnikRaspored.orgjed_sifra)
            .where(KorisnikRaspored.korisnik_id == korisnik_id, KorisnikRaspored.aktivan == "D")
            .order_by(KorisnikRaspored.primarni, KorisnikRaspored.id)  # 'D' pre 'N'
            .limit(1)
        )
        return self.db.execute(stmt).scalars().first()

    def orgjed_average(self, nivo_id: int, orgjed_sifra: str) -> tuple[int, float | None]:
        stmt = select(func.count(), func.avg(IgraRezultat.trajanje_ms)).where(
            IgraRezultat.nivo_id == nivo_id,
            IgraRezultat.orgjed_sifra == orgjed_sifra,
            IgraRezultat.status == REZULTAT_RESEN,
        )
        count, avg = self.db.execute(stmt).one()
        return int(count or 0), (float(avg) if avg is not None else None)

    def solved_dates(self, korisnik_id: int, since: datetime.date) -> set[datetime.date]:
        """Dani u kojima je zaposleni resio nivo (za niz dana zaredom)."""
        stmt = (
            select(IgraNivo.datum)
            .join(IgraRezultat, IgraRezultat.nivo_id == IgraNivo.id)
            .where(
                IgraRezultat.korisnik_id == korisnik_id,
                IgraRezultat.status == REZULTAT_RESEN,
                IgraNivo.datum >= since,
            )
        )
        out = set()
        for d in self.db.execute(stmt).scalars().all():
            out.add(d.date() if isinstance(d, datetime.datetime) else d)
        return out
