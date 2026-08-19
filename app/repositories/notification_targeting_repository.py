from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.korisnik import Korisnik
from app.models.korisnik_raspored import KorisnikRaspored

# Aktivan i omogucen korisnik.
_ACTIVE = (Korisnik.status_zaposlenja == "AKTIVAN", Korisnik.status_naloga == "OMOGUCEN")


class NotificationTargetingRepository:
    """Read-only razresavanje ciljanih korisnika iz postojecih HR/PULS podataka.

    Namerno odvojeno od SurveyTargetingRepository (isti izvor podataka, ali modul
    OBAVESTENJA se ne oslanja na modul ANKETE). CENTRALA/MALOPRODAJA se NE razresavaju
    - nema pouzdanog HR podatka; publishing servis ih odbija VALIDATION_ERROR-om."""

    def __init__(self, db: Session):
        self.db = db

    def all_active_user_ids(self) -> set[int]:
        return set(self.db.execute(select(Korisnik.id).where(*_ACTIVE)).scalars().all())

    def user_ids_by_orgjed(self, orgjed_sifra: str) -> set[int]:
        """Svi aktivni korisnici sa aktivnim rasporedom za datu ORGJED sifru."""
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
