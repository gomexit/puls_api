import datetime

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.models.push import (
    PUSH_STATUS_PENDING,
    PUSH_STATUS_SENT,
    PushIsporuka,
)


class PushDeliveryRepository:
    """Pristup PULS_PUSH_ISPORUKE (outbox). Batch operacije umesto ucitavanja svega."""

    def __init__(self, db: Session):
        self.db = db

    # ---------------------------------------------------------------- publish
    def existing_user_ids(self, obavestenje_id: int) -> set[int]:
        stmt = select(PushIsporuka.korisnik_id).where(
            PushIsporuka.obavestenje_id == obavestenje_id
        )
        return set(self.db.execute(stmt).scalars().all())

    def add_pending(self, obavestenje_id: int, korisnik_id: int, now: datetime.datetime) -> PushIsporuka:
        red = PushIsporuka(
            obavestenje_id=obavestenje_id,
            korisnik_id=korisnik_id,
            status=PUSH_STATUS_PENDING,
            broj_pokusaja=0,
            datum_sledeceg_pokusaja=now,
            datum_kreiranja=now,
            broj_ponovnih_slanja=0,
        )
        self.db.add(red)
        return red

    def create_pending_for_recipients(
        self, obavestenje_id: int, korisnik_ids: set[int], now: datetime.datetime
    ) -> int:
        """Kreira PENDING red za svakog primaoca koji ga jos nema (idempotentno)."""
        existing = self.existing_user_ids(obavestenje_id)
        created = 0
        for uid in korisnik_ids - existing:
            self.add_pending(obavestenje_id, uid, now)
            created += 1
        return created

    def requeue_unread(
        self, obavestenje_id: int, unread_user_ids: set[int], now: datetime.datetime
    ) -> int:
        """Resend: vrati postojece redove nepr. primalaca u PENDING (+ponovnih_slanja),
        a za one bez reda kreiraj nov PENDING. Bez duplih redova."""
        rows = list(
            self.db.execute(
                select(PushIsporuka).where(
                    PushIsporuka.obavestenje_id == obavestenje_id,
                    PushIsporuka.korisnik_id.in_(unread_user_ids) if unread_user_ids else False,
                )
            ).scalars().all()
        )
        seen = set()
        affected = 0
        for red in rows:
            seen.add(red.korisnik_id)
            red.status = PUSH_STATUS_PENDING
            red.broj_pokusaja = 0
            red.datum_sledeceg_pokusaja = now
            red.poslednji_error_code = None
            # Cist resend state: staro SENT/FAILED stanje ne sme "procuriti" kroz
            # ponovljeni ciklus (npr. stari DATUM_SLANJA bi tvrdio da je vec poslato).
            red.datum_slanja = None
            red.datum_poslednjeg_pokusaja = None
            red.broj_ponovnih_slanja = (red.broj_ponovnih_slanja or 0) + 1
            affected += 1
        for uid in unread_user_ids - seen:
            red = self.add_pending(obavestenje_id, uid, now)
            red.broj_ponovnih_slanja = 1
            affected += 1
        return affected

    # ----------------------------------------------------------------- worker
    def claim_ready_batch(self, now: datetime.datetime, limit: int) -> list[PushIsporuka]:
        """PENDING redovi spremni za slanje (datum sledeceg pokusaja proso ili NULL).
        FOR UPDATE SKIP LOCKED nije potreban: jedna instanca workera je deployment pravilo."""
        stmt = (
            select(PushIsporuka)
            .where(
                PushIsporuka.status == PUSH_STATUS_PENDING,
                (PushIsporuka.datum_sledeceg_pokusaja.is_(None))
                | (PushIsporuka.datum_sledeceg_pokusaja <= now),
            )
            .order_by(PushIsporuka.datum_sledeceg_pokusaja.asc().nulls_first(), PushIsporuka.id.asc())
            .limit(limit)
        )
        return list(self.db.execute(stmt).scalars().all())

    def get(self, delivery_id: int) -> PushIsporuka | None:
        return self.db.get(PushIsporuka, delivery_id)

    # --------------------------------------------------------------- statistika
    def stats_for_notification(self, obavestenje_id: int) -> dict:
        row = self.db.execute(
            select(
                func.coalesce(func.sum(case((PushIsporuka.status == "PENDING", 1), else_=0)), 0),
                func.coalesce(func.sum(case((PushIsporuka.status == "SENT", 1), else_=0)), 0),
                func.coalesce(func.sum(case((PushIsporuka.status == "FAILED", 1), else_=0)), 0),
                func.coalesce(func.sum(case((PushIsporuka.status == "SKIPPED", 1), else_=0)), 0),
            ).where(PushIsporuka.obavestenje_id == obavestenje_id)
        ).one()
        return {
            "push_pending": int(row[0]),
            "push_sent": int(row[1]),
            "push_failed": int(row[2]),
            "push_skipped": int(row[3]),
        }

    def count_sent(self, obavestenje_id: int) -> int:
        return int(
            self.db.execute(
                select(func.count()).select_from(PushIsporuka).where(
                    PushIsporuka.obavestenje_id == obavestenje_id,
                    PushIsporuka.status == PUSH_STATUS_SENT,
                )
            ).scalar_one()
        )
