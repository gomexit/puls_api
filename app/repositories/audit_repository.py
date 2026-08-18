import datetime

from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog


class AuditRepository:
    def __init__(self, db: Session):
        self.db = db

    def add(
        self,
        korisnik_id: int | None,
        platni_broj: str | None,
        sifra_akcije: str,
        izvor: str,
        tip_entiteta: str | None = None,
        entitet_id: str | None = None,
        detalji: str | None = None,
        ip_adresa: str | None = None,
        korisnicki_agent: str | None = None,
    ) -> None:
        entry = AuditLog(
            korisnik_id=korisnik_id,
            platni_broj=platni_broj,
            sifra_akcije=sifra_akcije,
            tip_entiteta=tip_entiteta,
            entitet_id=entitet_id,
            izvor=izvor,
            detalji=detalji,
            ip_adresa=ip_adresa,
            korisnicki_agent=korisnicki_agent,
            datum_kreiranja=datetime.datetime.now(),
        )
        self.db.add(entry)
