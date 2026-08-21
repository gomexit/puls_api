from sqlalchemy import case, exists, func, select
from sqlalchemy.orm import Session

from app.models.korisnik import Korisnik
from app.models.korisnik_raspored import KorisnikRaspored
from app.models.korisnik_uloga import KorisnikUloga
from app.models.uloga import Uloga


class AdminUsersRepository:
    """Read/write pristup PULS_KORISNICI za admin USERS modul. Nikada ne selektuje
    LOZINKA_HASH u listi/detalju odgovora (samo za internu proveru/izmenu)."""

    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, user_id: int) -> Korisnik | None:
        return self.db.get(Korisnik, user_id)

    def get_by_id_for_update(self, user_id: int) -> Korisnik | None:
        stmt = select(Korisnik).where(Korisnik.id == user_id).with_for_update()
        return self.db.execute(stmt).scalars().first()

    def list_users(
        self,
        search: str | None,
        status_zaposlenja: str | None,
        status_naloga: str | None,
        zakljucan: bool | None,
        uloga: str | None,
        page: int,
        page_size: int,
    ) -> tuple[list[Korisnik], int]:
        stmt = select(Korisnik)
        if search is not None:
            pattern = f"%{search.upper()}%"
            stmt = stmt.where(
                func.upper(Korisnik.platni_broj).like(pattern)
                | func.upper(Korisnik.ime).like(pattern)
                | func.upper(Korisnik.prezime).like(pattern)
            )
        if status_zaposlenja is not None:
            stmt = stmt.where(Korisnik.status_zaposlenja == status_zaposlenja)
        if status_naloga is not None:
            stmt = stmt.where(Korisnik.status_naloga == status_naloga)
        if zakljucan is not None:
            stmt = stmt.where(Korisnik.zakljucan == ("D" if zakljucan else "N"))
        if uloga is not None:
            stmt = stmt.where(
                exists(
                    select(1)
                    .select_from(KorisnikUloga)
                    .join(Uloga, Uloga.id == KorisnikUloga.uloga_id)
                    .where(
                        KorisnikUloga.korisnik_id == Korisnik.id,
                        Uloga.sifra == uloga,
                        Uloga.aktivna == "D",
                    )
                )
            )

        total = int(self.db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one())
        rows = self.db.execute(
            stmt.order_by(Korisnik.id).offset((page - 1) * page_size).limit(page_size)
        ).scalars().all()
        return list(rows), total

    def batch_active_role_codes(self, korisnik_ids: list[int]) -> dict[int, list[str]]:
        """Jedan upit za celu stranicu (izbegava N+1)."""
        if not korisnik_ids:
            return {}
        stmt = (
            select(KorisnikUloga.korisnik_id, Uloga.sifra)
            .join(Uloga, Uloga.id == KorisnikUloga.uloga_id)
            .where(KorisnikUloga.korisnik_id.in_(korisnik_ids), Uloga.aktivna == "D")
        )
        result: dict[int, list[str]] = {}
        for kid, sifra in self.db.execute(stmt).all():
            result.setdefault(int(kid), []).append(sifra)
        return result

    def batch_primary_active_rasporedi(self, korisnik_ids: list[int]) -> dict[int, KorisnikRaspored]:
        """Batch verzija KorisnikRepository.get_primary_active_raspored - jedan upit
        za celu stranicu. CASE prioritet PRIMARNI='D' + ID kao stabilan tie-breaker
        (primarni.desc() bi pogresno stavilo 'N' ispred 'D')."""
        if not korisnik_ids:
            return {}
        primarni_prioritet = case((KorisnikRaspored.primarni == "D", 0), else_=1)
        stmt = (
            select(KorisnikRaspored)
            .where(KorisnikRaspored.korisnik_id.in_(korisnik_ids), KorisnikRaspored.aktivan == "D")
            .order_by(KorisnikRaspored.korisnik_id, primarni_prioritet, KorisnikRaspored.id)
        )
        result: dict[int, KorisnikRaspored] = {}
        for r in self.db.execute(stmt).scalars().all():
            result.setdefault(r.korisnik_id, r)
        return result
