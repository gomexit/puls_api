"""Admin AUDIT LOG modul: strogo read-only pregled PULS_AUDIT_LOG. Nema commit-a,
nema SELECT FOR UPDATE, i namerno se NE upisuje novi audit zapis prilikom pregleda
(izbegava beskonacnu audit buku)."""

import datetime

from sqlalchemy.orm import Session

from app.core.exceptions import AuditLogNotFoundError
from app.repositories.admin_audit_repository import AdminAuditRepository


class AdminAuditService:
    def __init__(self, db: Session, repository: AdminAuditRepository | None = None):
        self.db = db
        self.repo = repository or AdminAuditRepository(db)

    def list_logs(
        self,
        page: int,
        page_size: int,
        platni_broj: str | None,
        sifra_akcije: str | None,
        tip_entiteta: str | None,
        entitet_id: str | None,
        izvor: str | None,
        datum_od: datetime.datetime | None,
        datum_do: datetime.datetime | None,
    ) -> dict:
        items, total = self.repo.list_logs(
            platni_broj, sifra_akcije, tip_entiteta, entitet_id, izvor, datum_od, datum_do, page, page_size
        )
        return {
            "items": items,
            "page": page,
            "page_size": page_size,
            "total": total,
            "has_more": page * page_size < total,
        }

    def get_log(self, audit_id: int) -> dict:
        log = self.repo.get_by_id(audit_id)
        if log is None:
            raise AuditLogNotFoundError()
        return {
            "id": log.id,
            "korisnik_id": log.korisnik_id,
            "platni_broj": log.platni_broj,
            "sifra_akcije": log.sifra_akcije,
            "tip_entiteta": log.tip_entiteta,
            "entitet_id": log.entitet_id,
            "izvor": log.izvor,
            "datum_kreiranja": log.datum_kreiranja,
            "detalji": log.detalji,
            "ip_adresa": log.ip_adresa,
            "korisnicki_agent": log.korisnicki_agent,
        }
