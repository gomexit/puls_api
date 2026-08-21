"""Read-only pristup PULS_AUDIT_LOG za admin AUDIT LOG modul.

list_logs() NAMERNO selektuje samo uzak skup kolona (bez DETALJI CLOB-a, IP_ADRESE
i KORISNICKOG_AGENTA) - lista se moze ucestalo osvezavati i ne sme povlaciti teske
CLOB podatke niti osetljive tehnicke detalje. get_by_id() vraca pun entitet i koristi
se samo za detalj pojedinacnog zapisa."""

import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog

LIST_COLUMNS = (
    AuditLog.id,
    AuditLog.korisnik_id,
    AuditLog.platni_broj,
    AuditLog.sifra_akcije,
    AuditLog.tip_entiteta,
    AuditLog.entitet_id,
    AuditLog.izvor,
    AuditLog.datum_kreiranja,
)


class AdminAuditRepository:
    def __init__(self, db: Session):
        self.db = db

    def list_logs(
        self,
        platni_broj: str | None,
        sifra_akcije: str | None,
        tip_entiteta: str | None,
        entitet_id: str | None,
        izvor: str | None,
        datum_od: datetime.datetime | None,
        datum_do: datetime.datetime | None,
        page: int,
        page_size: int,
    ) -> tuple[list[dict], int]:
        stmt = select(*LIST_COLUMNS)
        if platni_broj is not None:
            stmt = stmt.where(AuditLog.platni_broj == platni_broj)
        if sifra_akcije is not None:
            stmt = stmt.where(AuditLog.sifra_akcije == sifra_akcije)
        if tip_entiteta is not None:
            stmt = stmt.where(AuditLog.tip_entiteta == tip_entiteta)
        if entitet_id is not None:
            stmt = stmt.where(AuditLog.entitet_id == entitet_id)
        if izvor is not None:
            stmt = stmt.where(AuditLog.izvor == izvor)
        if datum_od is not None:
            stmt = stmt.where(AuditLog.datum_kreiranja >= datum_od)
        if datum_do is not None:
            stmt = stmt.where(AuditLog.datum_kreiranja <= datum_do)

        total = int(self.db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one())
        rows = self.db.execute(
            stmt.order_by(AuditLog.datum_kreiranja.desc(), AuditLog.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
        items = [
            {
                "id": r.id,
                "korisnik_id": r.korisnik_id,
                "platni_broj": r.platni_broj,
                "sifra_akcije": r.sifra_akcije,
                "tip_entiteta": r.tip_entiteta,
                "entitet_id": r.entitet_id,
                "izvor": r.izvor,
                "datum_kreiranja": r.datum_kreiranja,
            }
            for r in rows
        ]
        return items, total

    def get_by_id(self, audit_id: int) -> AuditLog | None:
        return self.db.get(AuditLog, audit_id)
