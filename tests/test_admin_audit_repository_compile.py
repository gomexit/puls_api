"""Proverava da AdminAuditRepository upiti REALNO kompajliraju za Oracle dijalekt
(bez zive konekcije), i eksplicitno da list_logs() NIKADA ne selektuje DETALJI CLOB,
IP_ADRESU niti KORISNICKI_AGENT."""

import datetime

from sqlalchemy.dialects import oracle

from app.repositories.admin_audit_repository import AdminAuditRepository


class _StubResult:
    def all(self):
        return []

    def scalar_one(self):
        return 0


class _CompileCapturingDb:
    def __init__(self):
        self.compiled: list[str] = []

    def execute(self, stmt):
        compiled = stmt.compile(dialect=oracle.dialect())
        self.compiled.append(str(compiled).upper())
        return _StubResult()

    def get(self, model, pk):
        return None


def _repo():
    db = _CompileCapturingDb()
    return AdminAuditRepository(db), db


def test_list_logs_no_filters_compiles_without_clob_or_sensitive_columns():
    repo, db = _repo()
    rows, total = repo.list_logs(None, None, None, None, None, None, None, 1, 20)
    assert rows == [] and total == 0
    sql = "".join(db.compiled)
    assert "PULS_AUDIT_LOG" in sql
    assert "DETALJI" not in sql
    assert "IP_ADRESA" not in sql
    assert "KORISNICKI_AGENT" not in sql


def test_list_logs_all_filters_compile():
    repo, db = _repo()
    rows, total = repo.list_logs(
        platni_broj="123456",
        sifra_akcije="LOGIN",
        tip_entiteta="KORISNIK",
        entitet_id="5",
        izvor="PORTAL",
        datum_od=datetime.datetime(2026, 1, 1),
        datum_do=datetime.datetime(2026, 2, 1),
        page=1,
        page_size=20,
    )
    assert rows == [] and total == 0
    sql = "".join(db.compiled)
    assert "PULS_AUDIT_LOG" in sql
    assert "DETALJI" not in sql
    assert "IP_ADRESA" not in sql
    assert "KORISNICKI_AGENT" not in sql


def test_list_logs_orders_by_datum_desc_then_id_desc():
    repo, db = _repo()
    repo.list_logs(None, None, None, None, None, None, None, 1, 20)
    sql = db.compiled[-1]
    assert "ORDER BY" in sql
    assert 'DATUM_KREIRANJA" DESC' in sql
    assert 'ID" DESC' in sql


def test_get_by_id_does_not_query_via_execute():
    repo, db = _repo()
    assert repo.get_by_id(1) is None
    # db.get(...) (Session.get) se koristi za detalj - ne prolazi kroz execute().
    assert db.compiled == []
