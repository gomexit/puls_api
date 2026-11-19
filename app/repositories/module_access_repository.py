from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.korisnik_raspored import KorisnikRaspored


class ModuleAccessRepository:
    """Read-only podaci za ukljucivanje modula i ciljanje: aktivne org. jedinice korisnika
    iz PULS_KORISNIK_RASPOREDI (PULS tabela koju puni HR sinhronizacija; HR izvori se ovde
    ne citaju)."""

    def __init__(self, db: Session):
        self.db = db

    def active_orgjed_codes(self, korisnik_id: int) -> frozenset[str]:
        stmt = (
            select(KorisnikRaspored.orgjed_sifra)
            .where(KorisnikRaspored.korisnik_id == korisnik_id, KorisnikRaspored.aktivan == "D")
            .distinct()
        )
        return frozenset(str(code) for code in self.db.execute(stmt).scalars().all() if code)
