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
