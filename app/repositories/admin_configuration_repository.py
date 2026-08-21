"""Read/write pristup PULS_KONFIGURACIJA za admin CONFIGURATION modul. Radi
isključivo sa ključevima iz allowlist-e (app.core.configuration_definitions) -
poziv sa proizvoljnim ključem je odgovornost sloja iznad (servis), ovaj repository
samo izvršava upite nad prosleđenim ključevima."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.konfiguracija import Konfiguracija


class AdminConfigurationRepository:
    def __init__(self, db: Session):
        self.db = db

    def list_active_by_keys(self, keys: list[str]) -> dict[str, Konfiguracija]:
        """Jedan batch upit za sve dozvoljene ključeve (izbegava N+1)."""
        if not keys:
            return {}
        stmt = select(Konfiguracija).where(Konfiguracija.kljuc.in_(keys), Konfiguracija.aktivna == "D")
        return {row.kljuc: row for row in self.db.execute(stmt).scalars().all()}

    def get_for_update(self, key: str) -> Konfiguracija | None:
        """SELECT FOR UPDATE - vraća red bez obzira na AKTIVNA (da bi PUT mogao da
        reaktivira postojeći neaktivan red umesto da pravi duplikat po PK-u)."""
        stmt = select(Konfiguracija).where(Konfiguracija.kljuc == key).with_for_update()
        return self.db.execute(stmt).scalars().first()

    def get_for_update_batch(self, keys: list[str]) -> dict[str, Konfiguracija]:
        """Batch SELECT FOR UPDATE za više ključeva odjednom (npr. CURRENT_VERSION +
        MIN_SUPPORTED_VERSION) - zaključava postojeće redove u STABILNOM redosledu
        po KLJUC (ORDER BY) da bi se izbegao deadlock kada dva paralelna PUT-a menjaju
        isti par ključeva u različitom redosledu. Redovi koji ne postoje se ne
        pojavljuju u rezultatu (kao i kod get_for_update)."""
        if not keys:
            return {}
        stmt = (
            select(Konfiguracija)
            .where(Konfiguracija.kljuc.in_(keys))
            .order_by(Konfiguracija.kljuc)
            .with_for_update()
        )
        return {row.kljuc: row for row in self.db.execute(stmt).scalars().all()}

    def get_active_value(self, key: str) -> str | None:
        """Bez zaključavanja - koristi se za unakrsnu validaciju (npr. CURRENT_VERSION
        naspram MIN_SUPPORTED_VERSION) kada se menja samo jedan od dva ključa."""
        stmt = select(Konfiguracija.vrednost).where(Konfiguracija.kljuc == key, Konfiguracija.aktivna == "D")
        return self.db.execute(stmt).scalar_one_or_none()
