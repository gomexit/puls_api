"""In-memory fake AdminAuditRepository (bez prave Oracle baze) - koristi se za
servisne/HTTP testove modula ADMIN AUDIT LOG."""

import datetime


class FakeAuditLog:
    def __init__(
        self,
        id,
        korisnik_id=None,
        platni_broj=None,
        sifra_akcije="NEKA_AKCIJA",
        tip_entiteta=None,
        entitet_id=None,
        izvor="PORTAL",
        datum_kreiranja=None,
        detalji=None,
        ip_adresa=None,
        korisnicki_agent=None,
    ):
        self.id = id
        self.korisnik_id = korisnik_id
        self.platni_broj = platni_broj
        self.sifra_akcije = sifra_akcije
        self.tip_entiteta = tip_entiteta
        self.entitet_id = entitet_id
        self.izvor = izvor
        self.datum_kreiranja = datum_kreiranja or datetime.datetime(2026, 1, 1, 10, 0, 0)
        self.detalji = detalji
        self.ip_adresa = ip_adresa
        self.korisnicki_agent = korisnicki_agent


class FakeAdminAuditRepository:
    def __init__(self, logs: list[FakeAuditLog] | None = None):
        self.logs = {log.id: log for log in (logs or [])}

    def list_logs(
        self,
        platni_broj,
        sifra_akcije,
        tip_entiteta,
        entitet_id,
        izvor,
        datum_od,
        datum_do,
        page,
        page_size,
    ):
        items = list(self.logs.values())
        if platni_broj is not None:
            items = [l for l in items if l.platni_broj == platni_broj]
        if sifra_akcije is not None:
            items = [l for l in items if l.sifra_akcije == sifra_akcije]
        if tip_entiteta is not None:
            items = [l for l in items if l.tip_entiteta == tip_entiteta]
        if entitet_id is not None:
            items = [l for l in items if l.entitet_id == entitet_id]
        if izvor is not None:
            items = [l for l in items if l.izvor == izvor]
        if datum_od is not None:
            items = [l for l in items if l.datum_kreiranja >= datum_od]
        if datum_do is not None:
            items = [l for l in items if l.datum_kreiranja <= datum_do]
        items.sort(key=lambda l: (l.datum_kreiranja, l.id), reverse=True)
        total = len(items)
        start = (page - 1) * page_size
        page_items = items[start : start + page_size]
        dicts = [
            {
                "id": l.id,
                "korisnik_id": l.korisnik_id,
                "platni_broj": l.platni_broj,
                "sifra_akcije": l.sifra_akcije,
                "tip_entiteta": l.tip_entiteta,
                "entitet_id": l.entitet_id,
                "izvor": l.izvor,
                "datum_kreiranja": l.datum_kreiranja,
            }
            for l in page_items
        ]
        return dicts, total

    def get_by_id(self, audit_id):
        return self.logs.get(audit_id)
