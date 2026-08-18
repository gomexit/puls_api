from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.korisnik import Korisnik
from app.models.korisnik_raspored import KorisnikRaspored

# Aktivan i omogucen korisnik.
_ACTIVE = (Korisnik.status_zaposlenja == "AKTIVAN", Korisnik.status_naloga == "OMOGUCEN")


class SurveyTargetingRepository:
    """Read-only razresavanje ciljanih korisnika iz postojecih HR/PULS podataka.

    NAPOMENA (bloker): CENTRALA/MALOPRODAJA se NE razresavaju ovde - ne postoji
    pouzdan HR podatak koji ih razlikuje (potvrdjeno read-only pre-flight proverom).
    Vidi SurveyAdminService._materialize_targets."""

    def __init__(self, db: Session):
        self.db = db

    def all_active_user_ids(self) -> set[int]:
        return set(self.db.execute(select(Korisnik.id).where(*_ACTIVE)).scalars().all())

    def user_ids_by_orgjed(self, orgjed_sifra: str) -> set[int]:
        """Svi aktivni redovi u PULS_KORISNIK_RASPOREDI (ne samo primarni raspored)."""
        stmt = (
            select(Korisnik.id)
            .join(KorisnikRaspored, KorisnikRaspored.korisnik_id == Korisnik.id)
            .where(
                *_ACTIVE,
                KorisnikRaspored.aktivan == "D",
                KorisnikRaspored.orgjed_sifra == orgjed_sifra,
            )
            .distinct()
        )
        return set(self.db.execute(stmt).scalars().all())

    def user_id_by_platni_broj(self, platni_broj: str) -> int | None:
        stmt = select(Korisnik.id).where(*_ACTIVE, Korisnik.platni_broj == platni_broj)
        return self.db.execute(stmt).scalars().first()