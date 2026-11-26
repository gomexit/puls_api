"""HVALA, KOLEGA! - upiti nad PULS_ZAHVALNICE i PULS_ZAHVALNICA_PRIJAVE (bez ORM relationship-a)."""

import datetime

from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from app.models.iis_orgjed import IisOrgjed
from app.models.korisnik import (
    STATUS_NALOGA_OMOGUCEN,
    STATUS_ZAPOSLENJA_AKTIVAN,
    Korisnik,
)
from app.models.korisnik_raspored import KorisnikRaspored
from app.models.zahvalnica import STATUS_OBJAVLJENA, Zahvalnica, ZahvalnicaPrijava


class KudosRepository:
    def __init__(self, db: Session):
        self.db = db

    # ============================================================== korisnici
    def get_user(self, korisnik_id: int) -> Korisnik | None:
        return self.db.get(Korisnik, korisnik_id)

    def users_by_ids(self, ids: set[int]) -> dict[int, Korisnik]:
        if not ids:
            return {}
        stmt = select(Korisnik).where(Korisnik.id.in_(sorted(ids)))
        return {int(k.id): k for k in self.db.execute(stmt).scalars().all()}

    def primary_orgjed(self, korisnik_id: int) -> str | None:
        stmt = (
            select(KorisnikRaspored.orgjed_sifra)
            .where(KorisnikRaspored.korisnik_id == korisnik_id, KorisnikRaspored.aktivan == "D")
            .order_by(KorisnikRaspored.primarni, KorisnikRaspored.id)  # 'D' pre 'N'
            .limit(1)
        )
        return self.db.execute(stmt).scalars().first()

    def orgjed_names(self, sifre: set[str]) -> dict[str, str]:
        if not sifre:
            return {}
        stmt = select(IisOrgjed.sifra, IisOrgjed.naziv).where(IisOrgjed.sifra.in_(sorted(sifre)))
        return {str(s): str(n) for s, n in self.db.execute(stmt).all() if s and n}

    def search_colleagues(self, tokens: list[str], exclude_id: int, limit: int) -> list[Korisnik]:
        """Aktivni zaposleni ciji ime ili prezime sadrzi svaki od reci upita."""
        stmt = select(Korisnik).where(
            Korisnik.status_zaposlenja == STATUS_ZAPOSLENJA_AKTIVAN,
            Korisnik.status_naloga == STATUS_NALOGA_OMOGUCEN,
            Korisnik.id != exclude_id,
        )
        for token in tokens:
            pattern = f"%{token.upper()}%"
            stmt = stmt.where(or_(func.upper(Korisnik.ime).like(pattern), func.upper(Korisnik.prezime).like(pattern)))
        stmt = stmt.order_by(Korisnik.prezime, Korisnik.ime, Korisnik.id).limit(limit)
        return list(self.db.execute(stmt).scalars().all())

    # ============================================================ zahvalnice
    def add(self, zahvalnica: Zahvalnica) -> Zahvalnica:
        self.db.add(zahvalnica)
        self.db.flush()
        return zahvalnica

    def get(self, zahvalnica_id: int) -> Zahvalnica | None:
        return self.db.get(Zahvalnica, zahvalnica_id)

    def get_for_update(self, zahvalnica_id: int) -> Zahvalnica | None:
        stmt = select(Zahvalnica).where(Zahvalnica.id == zahvalnica_id).with_for_update()
        return self.db.execute(stmt).scalars().first()

    def count_sent_since(self, posiljalac_id: int, since: datetime.datetime) -> int:
        stmt = select(func.count()).where(
            Zahvalnica.posiljalac_id == posiljalac_id, Zahvalnica.datum_kreiranja >= since
        )
        return int(self.db.execute(stmt).scalar() or 0)

    def feed(self, orgjed: str | None, offset: int, limit: int) -> list[Zahvalnica]:
        """Objavljene, najnovije prvo. orgjed = samo gde je posiljalac ili primalac iz te jedinice."""
        stmt = select(Zahvalnica).where(Zahvalnica.status == STATUS_OBJAVLJENA)
        if orgjed is not None:
            stmt = stmt.where(or_(Zahvalnica.primalac_orgjed == orgjed, Zahvalnica.posiljalac_orgjed == orgjed))
        stmt = stmt.order_by(Zahvalnica.datum_kreiranja.desc(), Zahvalnica.id.desc()).offset(offset).limit(limit)
        return list(self.db.execute(stmt).scalars().all())

    def received(self, korisnik_id: int, offset: int, limit: int) -> list[Zahvalnica]:
        stmt = (
            select(Zahvalnica)
            .where(Zahvalnica.primalac_id == korisnik_id, Zahvalnica.status == STATUS_OBJAVLJENA)
            .order_by(Zahvalnica.datum_kreiranja.desc(), Zahvalnica.id.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(self.db.execute(stmt).scalars().all())

    def sent(self, korisnik_id: int, offset: int, limit: int) -> list[Zahvalnica]:
        stmt = (
            select(Zahvalnica)
            .where(Zahvalnica.posiljalac_id == korisnik_id)
            .order_by(Zahvalnica.datum_kreiranja.desc(), Zahvalnica.id.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(self.db.execute(stmt).scalars().all())

    def unread_count(self, korisnik_id: int) -> int:
        stmt = select(func.count()).where(
            Zahvalnica.primalac_id == korisnik_id,
            Zahvalnica.status == STATUS_OBJAVLJENA,
            Zahvalnica.procitana == "N",
        )
        return int(self.db.execute(stmt).scalar() or 0)

    def mark_received_read(self, korisnik_id: int) -> int:
        stmt = (
            update(Zahvalnica)
            .where(Zahvalnica.primalac_id == korisnik_id, Zahvalnica.procitana == "N")
            .values(procitana="D")
        )
        return int(self.db.execute(stmt).rowcount or 0)

    # =============================================================== prijave
    def has_report(self, zahvalnica_id: int, korisnik_id: int) -> bool:
        stmt = select(func.count()).where(
            ZahvalnicaPrijava.zahvalnica_id == zahvalnica_id, ZahvalnicaPrijava.korisnik_id == korisnik_id
        )
        return int(self.db.execute(stmt).scalar() or 0) > 0

    def add_report(self, prijava: ZahvalnicaPrijava) -> ZahvalnicaPrijava:
        self.db.add(prijava)
        self.db.flush()
        return prijava

    def report_count(self, zahvalnica_id: int) -> int:
        stmt = select(func.count()).where(ZahvalnicaPrijava.zahvalnica_id == zahvalnica_id)
        return int(self.db.execute(stmt).scalar() or 0)

    def report_counts(self, ids: list[int]) -> dict[int, int]:
        if not ids:
            return {}
        stmt = (
            select(ZahvalnicaPrijava.zahvalnica_id, func.count())
            .where(ZahvalnicaPrijava.zahvalnica_id.in_(ids))
            .group_by(ZahvalnicaPrijava.zahvalnica_id)
        )
        return {int(z): int(c) for z, c in self.db.execute(stmt).all()}

    def reports(self, zahvalnica_id: int) -> list[ZahvalnicaPrijava]:
        stmt = (
            select(ZahvalnicaPrijava)
            .where(ZahvalnicaPrijava.zahvalnica_id == zahvalnica_id)
            .order_by(ZahvalnicaPrijava.datum_kreiranja, ZahvalnicaPrijava.id)
        )
        return list(self.db.execute(stmt).scalars().all())

    # ================================================================= admin
    def admin_list(self, status: str | None, offset: int, limit: int) -> tuple[int, list[Zahvalnica]]:
        base = select(Zahvalnica)
        count = select(func.count()).select_from(Zahvalnica)
        if status is not None:
            base = base.where(Zahvalnica.status == status)
            count = count.where(Zahvalnica.status == status)
        total = int(self.db.execute(count).scalar() or 0)
        stmt = base.order_by(Zahvalnica.datum_kreiranja.desc(), Zahvalnica.id.desc()).offset(offset).limit(limit)
        return total, list(self.db.execute(stmt).scalars().all())
