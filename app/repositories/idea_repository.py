import datetime

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.models.ideja import IDEJA_STATUS_POSLATA, IDEJA_TOP_STATUSI, Ideja


class IdeaRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, idea_id: int) -> Ideja | None:
        return self.db.get(Ideja, idea_id)

    def count_user_ideas_in_cycle(self, korisnik_id: int, ciklus_id: int) -> int:
        """Broji SVE ideje koje je korisnik poslao u ciklusu (ukljucujuci kasnije odbijene)."""
        stmt = (
            select(func.count())
            .select_from(Ideja)
            .where(Ideja.korisnik_id == korisnik_id, Ideja.ciklus_id == ciklus_id)
        )
        return int(self.db.execute(stmt).scalar_one())

    def create(
        self,
        korisnik_id: int,
        ciklus_id: int,
        platni_broj: str,
        ime_autora: str,
        prezime_autora: str,
        orgjed_sifra: str | None,
        naslov: str,
        opis: str,
    ) -> Ideja:
        now = datetime.datetime.now()
        ideja = Ideja(
            korisnik_id=korisnik_id,
            ciklus_id=ciklus_id,
            platni_broj=platni_broj,
            ime_autora=ime_autora,
            prezime_autora=prezime_autora,
            orgjed_sifra=orgjed_sifra,
            naslov=naslov,
            opis=opis,
            status=IDEJA_STATUS_POSLATA,
            datum_kreiranja=now,
        )
        self.db.add(ideja)
        self.db.flush()
        return ideja

    def list_by_user(self, korisnik_id: int, ciklus_id: int | None = None) -> list[Ideja]:
        stmt = select(Ideja).where(Ideja.korisnik_id == korisnik_id)
        if ciklus_id is not None:
            stmt = stmt.where(Ideja.ciklus_id == ciklus_id)
        stmt = stmt.order_by(Ideja.datum_kreiranja.desc(), Ideja.id.desc())
        return list(self.db.execute(stmt).scalars().all())

    def list_top(self, ciklus_id: int, limit: int) -> list[Ideja]:
        """Najbolje ideje jednog ciklusa. Sort:
        1) KONACNA_OCENA DESC (NULL poslednje)
        2) HR_OCENA DESC (NULL poslednje)
        3) DATUM_KREIRANJA ASC
        4) ID ASC (deterministicki redosled)"""
        stmt = (
            select(Ideja)
            .where(Ideja.ciklus_id == ciklus_id, Ideja.status.in_(IDEJA_TOP_STATUSI))
            .order_by(
                Ideja.konacna_ocena.desc().nulls_last(),
                Ideja.hr_ocena.desc().nulls_last(),
                Ideja.datum_kreiranja.asc(),
                Ideja.id.asc(),
            )
            .limit(limit)
        )
        return list(self.db.execute(stmt).scalars().all())

    def _admin_filter_query(
        self,
        ciklus_id: int | None,
        status: str | None,
        korisnik_id: int | None,
        platni_broj: str | None,
    ) -> Select:
        stmt = select(Ideja)
        if ciklus_id is not None:
            stmt = stmt.where(Ideja.ciklus_id == ciklus_id)
        if status is not None:
            stmt = stmt.where(Ideja.status == status)
        if korisnik_id is not None:
            stmt = stmt.where(Ideja.korisnik_id == korisnik_id)
        if platni_broj is not None:
            stmt = stmt.where(Ideja.platni_broj == platni_broj)
        return stmt

    def admin_list(
        self,
        ciklus_id: int | None,
        status: str | None,
        korisnik_id: int | None,
        platni_broj: str | None,
        page: int,
        page_size: int,
    ) -> tuple[list[Ideja], int]:
        base = self._admin_filter_query(ciklus_id, status, korisnik_id, platni_broj)
        total = int(
            self.db.execute(select(func.count()).select_from(base.subquery())).scalar_one()
        )
        stmt = (
            base.order_by(Ideja.datum_kreiranja.desc(), Ideja.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        items = list(self.db.execute(stmt).scalars().all())
        return items, total