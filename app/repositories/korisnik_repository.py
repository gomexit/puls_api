from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.models.korisnik import Korisnik
from app.models.korisnik_raspored import KorisnikRaspored
from app.models.korisnik_uloga import KorisnikUloga
from app.models.uloga import Uloga


class KorisnikRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, korisnik_id: int) -> Korisnik | None:
        return self.db.get(Korisnik, korisnik_id)

    def get_by_platni_broj(self, platni_broj: str) -> Korisnik | None:
        stmt = select(Korisnik).where(Korisnik.platni_broj == platni_broj)
        return self.db.execute(stmt).scalar_one_or_none()

    def candidates_for_provisioning_query(self, limit: int | None = None) -> Select:
        """Plain SELECT (no FOR UPDATE / SKIP LOCKED). The provisioning worker runs as a
        single instance, so row locking is unnecessary; the exposed builder lets tests
        assert the generated SQL stays lock-free. Phone validation happens in the
        service layer so no-phone and invalid-phone candidates can be counted."""
        stmt = (
            select(Korisnik)
            .where(
                Korisnik.status_zaposlenja == "AKTIVAN",
                Korisnik.status_naloga == "OMOGUCEN",
                Korisnik.lozinka_hash.is_(None),
            )
            .order_by(Korisnik.id)
        )
        if limit is not None:
            stmt = stmt.limit(limit)
        return stmt

    def list_candidates_for_provisioning(self, limit: int | None = None) -> list[Korisnik]:
        return list(self.db.execute(self.candidates_for_provisioning_query(limit)).scalars().all())

    def get_active_role_codes(self, korisnik_id: int) -> list[str]:
        stmt = (
            select(Uloga.sifra)
            .join(KorisnikUloga, KorisnikUloga.uloga_id == Uloga.id)
            .where(KorisnikUloga.korisnik_id == korisnik_id, Uloga.aktivna == "D")
        )
        return list(self.db.execute(stmt).scalars().all())

    def get_primary_active_raspored(self, korisnik_id: int) -> KorisnikRaspored | None:
        stmt = (
            select(KorisnikRaspored)
            .where(KorisnikRaspored.korisnik_id == korisnik_id, KorisnikRaspored.aktivan == "D")
            .order_by(KorisnikRaspored.primarni.desc())
        )
        return self.db.execute(stmt).scalars().first()
