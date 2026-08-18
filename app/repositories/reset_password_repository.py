import datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models.reset_lozinke import ResetLozinke


class ResetPasswordRepository:
    def __init__(self, db: Session):
        self.db = db

    def deactivate_active_for_user(self, korisnik_id: int) -> None:
        stmt = (
            update(ResetLozinke)
            .where(ResetLozinke.korisnik_id == korisnik_id, ResetLozinke.aktivan == "D")
            .values(aktivan="N")
        )
        self.db.execute(stmt)

    def create(
        self, korisnik_id: int, kod_hash: str, ttl_minutes: int, ip_adresa: str | None
    ) -> ResetLozinke:
        now = datetime.datetime.now()
        reset = ResetLozinke(
            korisnik_id=korisnik_id,
            kod_hash=kod_hash,
            aktivan="D",
            broj_pokusaja=0,
            datum_zahteva=now,
            datum_isteka=now + datetime.timedelta(minutes=ttl_minutes),
            ip_adresa=ip_adresa,
            datum_kreiranja=now,
        )
        self.db.add(reset)
        self.db.flush()
        return reset

    def get_active_for_user(self, korisnik_id: int) -> ResetLozinke | None:
        stmt = (
            select(ResetLozinke)
            .where(ResetLozinke.korisnik_id == korisnik_id, ResetLozinke.aktivan == "D")
            .order_by(ResetLozinke.datum_zahteva.desc())
        )
        return self.db.execute(stmt).scalars().first()

    def increment_attempts(self, reset: ResetLozinke) -> None:
        reset.broj_pokusaja = (reset.broj_pokusaja or 0) + 1

    def mark_used(self, reset: ResetLozinke) -> None:
        reset.aktivan = "N"
        reset.datum_koriscenja = datetime.datetime.now()
