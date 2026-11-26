"""Pristup bazi za modul PULS IZAZOV (sql/011_kviz_module.sql).

Repozitorijum ne commit-uje; transakcijom upravlja servis. Citaju se samo PULS tabele
(HR izvori se ne koriste - org. jedinica dolazi iz PULS_KORISNIK_RASPOREDI)."""

import datetime
from collections.abc import Iterable

from sqlalchemy import case, delete, func, select
from sqlalchemy.orm import Session

from app.models.korisnik_raspored import KorisnikRaspored
from app.models.kviz import (
    KVIZ_STATUS_OBJAVLJEN,
    POKUSAJ_ZAVRSEN,
    Kviz,
    KvizCilj,
    KvizKategorija,
    KvizOdgovor,
    KvizOpcija,
    KvizPitanje,
    KvizPokusaj,
)
from app.models.slika import SLIKA_STATUS_AKTIVNA, Slika


def _escape_like(term: str) -> str:
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class QuizRepository:
    def __init__(self, db: Session):
        self.db = db

    # ============================================================ kategorije
    def list_categories(self, aktivna: str | None = None) -> list[KvizKategorija]:
        stmt = select(KvizKategorija)
        if aktivna is not None:
            stmt = stmt.where(KvizKategorija.aktivna == aktivna)
        stmt = stmt.order_by(KvizKategorija.redosled, KvizKategorija.sifra)
        return list(self.db.execute(stmt).scalars().all())

    def get_category(self, sifra: str) -> KvizKategorija | None:
        return self.db.execute(select(KvizKategorija).where(KvizKategorija.sifra == sifra)).scalar_one_or_none()

    def get_category_for_update(self, sifra: str) -> KvizKategorija | None:
        stmt = select(KvizKategorija).where(KvizKategorija.sifra == sifra).with_for_update()
        return self.db.execute(stmt).scalar_one_or_none()

    def add_category(self, kategorija: KvizKategorija) -> KvizKategorija:
        self.db.add(kategorija)
        return kategorija

    def active_category_codes(self, codes: Iterable[str]) -> set[str]:
        codes = list(set(codes))
        if not codes:
            return set()
        stmt = select(KvizKategorija.sifra).where(
            KvizKategorija.sifra.in_(codes), KvizKategorija.aktivna == "D"
        )
        return set(self.db.execute(stmt).scalars().all())

    def category_names(self, codes: Iterable[str]) -> dict[str, str]:
        codes = list(set(codes))
        if not codes:
            return {}
        stmt = select(KvizKategorija.sifra, KvizKategorija.naziv).where(KvizKategorija.sifra.in_(codes))
        return {row.sifra: row.naziv for row in self.db.execute(stmt).all()}

    # ================================================================ slike
    def active_image_ids(self, ids: Iterable[int]) -> set[int]:
        ids = list(set(ids))
        if not ids:
            return set()
        # Samo ID (bez BLOB-a).
        stmt = select(Slika.id).where(Slika.id.in_(ids), Slika.status == SLIKA_STATUS_AKTIVNA)
        return {int(i) for i in self.db.execute(stmt).scalars().all()}

    # ================================================================ kvizovi
    def list_admin(self, status: str | None, search: str | None, page: int, page_size: int):
        conditions = []
        if status is not None:
            conditions.append(Kviz.status == status)
        if search:
            pattern = f"%{_escape_like(search.lower())}%"
            conditions.append(func.lower(Kviz.naziv).like(pattern, escape="\\"))
        total = self.db.execute(select(func.count()).select_from(Kviz).where(*conditions)).scalar_one()
        stmt = (
            select(Kviz)
            .where(*conditions)
            .order_by(Kviz.datum_od.desc(), Kviz.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return list(self.db.execute(stmt).scalars().all()), int(total)

    def question_counts(self, kviz_ids: Iterable[int]) -> dict[int, int]:
        ids = list(set(kviz_ids))
        if not ids:
            return {}
        stmt = (
            select(KvizPitanje.kviz_id, func.count())
            .where(KvizPitanje.kviz_id.in_(ids))
            .group_by(KvizPitanje.kviz_id)
        )
        return {int(k): int(c) for k, c in self.db.execute(stmt).all()}

    def get(self, kviz_id: int) -> Kviz | None:
        return self.db.execute(select(Kviz).where(Kviz.id == kviz_id)).scalar_one_or_none()

    def get_for_update(self, kviz_id: int) -> Kviz | None:
        return self.db.execute(select(Kviz).where(Kviz.id == kviz_id).with_for_update()).scalar_one_or_none()

    def add(self, kviz: Kviz) -> Kviz:
        self.db.add(kviz)
        return kviz

    def find_overlapping_published(
        self, datum_od: datetime.datetime, datum_do: datetime.datetime, exclude_id: int | None
    ) -> list[Kviz]:
        conditions = [
            Kviz.status == KVIZ_STATUS_OBJAVLJEN,
            Kviz.datum_od < datum_do,
            Kviz.datum_do > datum_od,
        ]
        if exclude_id is not None:
            conditions.append(Kviz.id != exclude_id)
        return list(self.db.execute(select(Kviz).where(*conditions)).scalars().all())

    def find_open_published(self, now: datetime.datetime) -> list[Kviz]:
        stmt = (
            select(Kviz)
            .where(Kviz.status == KVIZ_STATUS_OBJAVLJEN, Kviz.datum_od <= now, Kviz.datum_do > now)
            .order_by(Kviz.datum_od.desc(), Kviz.id.desc())
        )
        return list(self.db.execute(stmt).scalars().all())

    # ----------------------------------------------------- ciljevi / pitanja
    def get_targets(self, kviz_id: int) -> list[KvizCilj]:
        stmt = select(KvizCilj).where(KvizCilj.kviz_id == kviz_id).order_by(KvizCilj.id)
        return list(self.db.execute(stmt).scalars().all())

    def get_questions(self, kviz_id: int) -> list[KvizPitanje]:
        stmt = select(KvizPitanje).where(KvizPitanje.kviz_id == kviz_id).order_by(KvizPitanje.redosled)
        return list(self.db.execute(stmt).scalars().all())

    def get_options(self, pitanje_ids: Iterable[int]) -> list[KvizOpcija]:
        ids = list(set(pitanje_ids))
        if not ids:
            return []
        stmt = (
            select(KvizOpcija)
            .where(KvizOpcija.pitanje_id.in_(ids))
            .order_by(KvizOpcija.pitanje_id, KvizOpcija.redosled)
        )
        return list(self.db.execute(stmt).scalars().all())

    def replace_targets(self, kviz_id: int, ciljevi: list[tuple[str, str]]) -> None:
        self.db.execute(delete(KvizCilj).where(KvizCilj.kviz_id == kviz_id))
        for tip, vrednost in ciljevi:
            self.db.add(KvizCilj(kviz_id=kviz_id, tip_cilja=tip, vrednost=vrednost))

    def replace_questions(self, kviz_id: int, pitanja: list[dict]) -> None:
        """Brise postojeca pitanja i opcije (samo DRAFT - bez pokusaja) i upisuje nova.
        Brisanje ide pre upisa (flush) zbog UQ (KVIZ_ID, REDOSLED)."""
        old_ids = select(KvizPitanje.id).where(KvizPitanje.kviz_id == kviz_id).scalar_subquery()
        self.db.execute(delete(KvizOpcija).where(KvizOpcija.pitanje_id.in_(old_ids)))
        self.db.execute(delete(KvizPitanje).where(KvizPitanje.kviz_id == kviz_id))
        self.db.flush()
        for redosled, p in enumerate(pitanja, start=1):
            pitanje = KvizPitanje(
                kviz_id=kviz_id,
                redosled=redosled,
                tekst=p["tekst"],
                kategorija_sifra=p["kategorija_sifra"],
                slika_id=p["slika_id"],
                objasnjenje=p["objasnjenje"],
            )
            self.db.add(pitanje)
            self.db.flush()  # ID pitanja za opcije
            for o_redosled, o in enumerate(p["opcije"], start=1):
                self.db.add(
                    KvizOpcija(
                        pitanje_id=pitanje.id,
                        redosled=o_redosled,
                        tekst=o["tekst"],
                        tacna="D" if o["tacna"] else "N",
                    )
                )

    # ================================================================ pokusaji
    def primary_orgjed(self, korisnik_id: int) -> str | None:
        stmt = (
            select(KorisnikRaspored.orgjed_sifra)
            .where(KorisnikRaspored.korisnik_id == korisnik_id, KorisnikRaspored.aktivan == "D")
            .order_by(KorisnikRaspored.primarni, KorisnikRaspored.id)  # 'D' pre 'N'
            .limit(1)
        )
        return self.db.execute(stmt).scalars().first()

    def get_attempt(self, kviz_id: int, korisnik_id: int) -> KvizPokusaj | None:
        stmt = select(KvizPokusaj).where(KvizPokusaj.kviz_id == kviz_id, KvizPokusaj.korisnik_id == korisnik_id)
        return self.db.execute(stmt).scalar_one_or_none()

    def get_attempt_for_update(self, kviz_id: int, korisnik_id: int) -> KvizPokusaj | None:
        stmt = (
            select(KvizPokusaj)
            .where(KvizPokusaj.kviz_id == kviz_id, KvizPokusaj.korisnik_id == korisnik_id)
            .with_for_update()
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def get_attempt_by_id_for_update(self, pokusaj_id: int) -> KvizPokusaj | None:
        stmt = select(KvizPokusaj).where(KvizPokusaj.id == pokusaj_id).with_for_update()
        return self.db.execute(stmt).scalar_one_or_none()

    def add_attempt(self, pokusaj: KvizPokusaj) -> KvizPokusaj:
        self.db.add(pokusaj)
        return pokusaj

    def get_answers(self, pokusaj_id: int) -> list[KvizOdgovor]:
        stmt = select(KvizOdgovor).where(KvizOdgovor.pokusaj_id == pokusaj_id).order_by(KvizOdgovor.id)
        return list(self.db.execute(stmt).scalars().all())

    def add_answer(self, odgovor: KvizOdgovor) -> KvizOdgovor:
        self.db.add(odgovor)
        return odgovor

    def orgjed_average(self, kviz_id: int, orgjed_sifra: str) -> tuple[int, float | None]:
        stmt = select(func.count(), func.avg(KvizPokusaj.broj_tacnih)).where(
            KvizPokusaj.kviz_id == kviz_id,
            KvizPokusaj.orgjed_sifra == orgjed_sifra,
            KvizPokusaj.status == POKUSAJ_ZAVRSEN,
        )
        count, avg = self.db.execute(stmt).one()
        return int(count or 0), (float(avg) if avg is not None else None)

    # ================================================================ rezultati
    def attempt_totals(self, kviz_id: int) -> dict:
        stmt = (
            select(
                KvizPokusaj.status,
                func.count(),
                func.avg(KvizPokusaj.broj_tacnih),
                func.avg(KvizPokusaj.trajanje_ms),
            )
            .where(KvizPokusaj.kviz_id == kviz_id)
            .group_by(KvizPokusaj.status)
        )
        result = {"ukupno": 0, "zavrseno": 0, "prosek_tacnih": None, "prosek_trajanja_ms": None}
        for status, count, avg, avg_ms in self.db.execute(stmt).all():
            result["ukupno"] += int(count)
            if status == POKUSAJ_ZAVRSEN:
                result["zavrseno"] = int(count)
                result["prosek_tacnih"] = float(avg) if avg is not None else None
                result["prosek_trajanja_ms"] = float(avg_ms) if avg_ms is not None else None
        return result

    def orgjed_stats(self, kviz_id: int) -> list[tuple[str | None, int, float | None]]:
        stmt = (
            select(KvizPokusaj.orgjed_sifra, func.count(), func.avg(KvizPokusaj.broj_tacnih))
            .where(KvizPokusaj.kviz_id == kviz_id, KvizPokusaj.status == POKUSAJ_ZAVRSEN)
            .group_by(KvizPokusaj.orgjed_sifra)
            .order_by(KvizPokusaj.orgjed_sifra)
        )
        return [(o, int(c), float(a) if a is not None else None) for o, c, a in self.db.execute(stmt).all()]

    def question_stats(self, kviz_id: int) -> dict[int, tuple[int, int]]:
        """pitanje_id -> (broj odgovora, broj tacnih)."""
        stmt = (
            select(KvizOdgovor.pitanje_id, func.count(), func.sum(case((KvizOdgovor.tacan == "D", 1), else_=0)))
            .join(KvizPitanje, KvizPitanje.id == KvizOdgovor.pitanje_id)
            .where(KvizPitanje.kviz_id == kviz_id)
            .group_by(KvizOdgovor.pitanje_id)
        )
        return {int(p): (int(c), int(t or 0)) for p, c, t in self.db.execute(stmt).all()}
