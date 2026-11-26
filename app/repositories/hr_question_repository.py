"""PITAJ HR - upiti nad PULS_HR_* tabelama (bez ORM relationship-a)."""

import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.hr_pitanje import (
    STATUS_POSLATO,
    HrCestoPitanje,
    HrKategorija,
    HrPitanje,
    HrPoruka,
)
from app.models.iis_orgjed import IisOrgjed
from app.models.korisnik import Korisnik
from app.models.korisnik_raspored import KorisnikRaspored


class HrQuestionRepository:
    def __init__(self, db: Session):
        self.db = db

    # ============================================================== korisnici
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

    # ============================================================= kategorije
    def list_categories(self, aktivna: str | None = None) -> list[HrKategorija]:
        stmt = select(HrKategorija)
        if aktivna is not None:
            stmt = stmt.where(HrKategorija.aktivna == aktivna)
        stmt = stmt.order_by(HrKategorija.redosled, HrKategorija.sifra)
        return list(self.db.execute(stmt).scalars().all())

    def get_category(self, sifra: str) -> HrKategorija | None:
        return self.db.get(HrKategorija, sifra)

    def get_category_for_update(self, sifra: str) -> HrKategorija | None:
        stmt = select(HrKategorija).where(HrKategorija.sifra == sifra).with_for_update()
        return self.db.execute(stmt).scalars().first()

    def add_category(self, kat: HrKategorija) -> HrKategorija:
        self.db.add(kat)
        self.db.flush()
        return kat

    def category_names(self) -> dict[str, str]:
        stmt = select(HrKategorija.sifra, HrKategorija.naziv)
        return {str(s): str(n) for s, n in self.db.execute(stmt).all()}

    # =============================================================== pitanja
    def add_question(self, p: HrPitanje) -> HrPitanje:
        self.db.add(p)
        self.db.flush()
        return p

    def add_message(self, m: HrPoruka) -> HrPoruka:
        self.db.add(m)
        self.db.flush()
        return m

    def get_question(self, pitanje_id: int) -> HrPitanje | None:
        return self.db.get(HrPitanje, pitanje_id)

    def get_question_for_update(self, pitanje_id: int) -> HrPitanje | None:
        stmt = select(HrPitanje).where(HrPitanje.id == pitanje_id).with_for_update()
        return self.db.execute(stmt).scalars().first()

    def count_asked_since(self, korisnik_id: int, since: datetime.datetime) -> int:
        stmt = select(func.count()).where(HrPitanje.korisnik_id == korisnik_id, HrPitanje.datum_kreiranja >= since)
        return int(self.db.execute(stmt).scalar() or 0)

    def mine(self, korisnik_id: int, offset: int, limit: int) -> list[HrPitanje]:
        stmt = (
            select(HrPitanje)
            .where(HrPitanje.korisnik_id == korisnik_id)
            .order_by(HrPitanje.datum_izmene.desc(), HrPitanje.id.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(self.db.execute(stmt).scalars().all())

    def unread_count(self, korisnik_id: int) -> int:
        stmt = select(func.count()).where(HrPitanje.korisnik_id == korisnik_id, HrPitanje.procitano == "N")
        return int(self.db.execute(stmt).scalar() or 0)

    def messages(self, pitanje_id: int) -> list[HrPoruka]:
        stmt = (
            select(HrPoruka)
            .where(HrPoruka.pitanje_id == pitanje_id)
            .order_by(HrPoruka.datum_kreiranja, HrPoruka.id)
        )
        return list(self.db.execute(stmt).scalars().all())

    def first_messages(self, pitanje_ids: list[int]) -> dict[int, HrPoruka]:
        """Prva poruka (samo pitanje) za listu."""
        if not pitanje_ids:
            return {}
        first = (
            select(HrPoruka.pitanje_id, func.min(HrPoruka.id).label("prva"))
            .where(HrPoruka.pitanje_id.in_(pitanje_ids))
            .group_by(HrPoruka.pitanje_id)
            .subquery()
        )
        stmt = select(HrPoruka).join(first, HrPoruka.id == first.c.prva)
        return {int(m.pitanje_id): m for m in self.db.execute(stmt).scalars().all()}

    def admin_list(
        self, status: str | None, kategorija: str | None, offset: int, limit: int
    ) -> tuple[int, list[HrPitanje]]:
        base = select(HrPitanje)
        count = select(func.count()).select_from(HrPitanje)
        if status is not None:
            base = base.where(HrPitanje.status == status)
            count = count.where(HrPitanje.status == status)
        if kategorija is not None:
            base = base.where(HrPitanje.kategorija_sifra == kategorija)
            count = count.where(HrPitanje.kategorija_sifra == kategorija)
        total = int(self.db.execute(count).scalar() or 0)
        if status == STATUS_POSLATO:  # najduze ceka - prvo
            order = (HrPitanje.datum_izmene, HrPitanje.id)
        else:
            order = (HrPitanje.datum_izmene.desc(), HrPitanje.id.desc())
        stmt = base.order_by(*order).offset(offset).limit(limit)
        return total, list(self.db.execute(stmt).scalars().all())

    # ========================================================= cesta pitanja
    def list_faq(self, aktivno: str | None, kategorija: str | None) -> list[HrCestoPitanje]:
        stmt = select(HrCestoPitanje)
        if aktivno is not None:
            stmt = stmt.where(HrCestoPitanje.aktivno == aktivno)
        if kategorija is not None:
            stmt = stmt.where(HrCestoPitanje.kategorija_sifra == kategorija)
        stmt = stmt.order_by(HrCestoPitanje.redosled, HrCestoPitanje.id)
        return list(self.db.execute(stmt).scalars().all())

    def get_faq_for_update(self, faq_id: int) -> HrCestoPitanje | None:
        stmt = select(HrCestoPitanje).where(HrCestoPitanje.id == faq_id).with_for_update()
        return self.db.execute(stmt).scalars().first()

    def add_faq(self, f: HrCestoPitanje) -> HrCestoPitanje:
        self.db.add(f)
        self.db.flush()
        return f
