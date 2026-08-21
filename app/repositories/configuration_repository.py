from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.konfiguracija import Konfiguracija


class ConfigurationRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_value(self, kljuc: str) -> str | None:
        stmt = select(Konfiguracija.vrednost).where(
            Konfiguracija.kljuc == kljuc, Konfiguracija.aktivna == "D"
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def get_values(self, kljucevi: list[str]) -> dict[str, str | None]:
        """Batch verzija get_value - jedan upit za više ključeva (izbegava N+1).
        Aditivna metoda, ne menja ponašanje get_value ni postojećih pozivalaca."""
        if not kljucevi:
            return {}
        stmt = select(Konfiguracija.kljuc, Konfiguracija.vrednost).where(
            Konfiguracija.kljuc.in_(kljucevi), Konfiguracija.aktivna == "D"
        )
        return dict(self.db.execute(stmt).all())
