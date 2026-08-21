"""Proverava da AdminConfigurationRepository i prosireni ConfigurationRepository
upiti REALNO kompajliraju za Oracle dijalekt (bez zive konekcije)."""

from sqlalchemy.dialects import oracle

from app.repositories.admin_configuration_repository import AdminConfigurationRepository
from app.repositories.configuration_repository import ConfigurationRepository


class _StubResult:
    def scalars(self):
        return self

    def all(self):
        return []

    def scalar_one_or_none(self):
        return None

    def first(self):
        return None


class _CompileCapturingDb:
    def __init__(self):
        self.compiled: list[str] = []

    def execute(self, stmt):
        compiled = stmt.compile(dialect=oracle.dialect())
        self.compiled.append(str(compiled).upper())
        return _StubResult()


def _repo():
    db = _CompileCapturingDb()
    return AdminConfigurationRepository(db), db


def test_list_active_by_keys_compiles():
    repo, db = _repo()
    result = repo.list_active_by_keys(["MAX_IDEJA_PO_CIKLUSU", "TOP_IDEAS_COUNT"])
    assert result == {}
    sql = db.compiled[-1]
    assert "PULS_KONFIGURACIJA" in sql
    assert "AKTIVNA" in sql
    assert "IN" in sql


def test_get_for_update_compiles_with_lock():
    repo, db = _repo()
    assert repo.get_for_update("MAX_IDEJA_PO_CIKLUSU") is None
    sql = db.compiled[-1]
    assert "PULS_KONFIGURACIJA" in sql
    assert "FOR UPDATE" in sql
    # get_for_update NE filtrira po AKTIVNA u WHERE delu (mora videti i neaktivan red
    # da bi ga reaktivirao) - AKTIVNA se pojavljuje samo u SELECT listi cele kolone.
    where_clause = sql.split("WHERE", 1)[1]
    assert "AKTIVNA" not in where_clause


def test_get_active_value_compiles():
    repo, db = _repo()
    assert repo.get_active_value("CURRENT_VERSION") is None
    sql = db.compiled[-1]
    assert "PULS_KONFIGURACIJA" in sql
    assert "AKTIVNA" in sql


def test_empty_key_list_short_circuits_without_query():
    repo, db = _repo()
    assert repo.list_active_by_keys([]) == {}
    assert db.compiled == []


def test_get_for_update_batch_compiles_with_lock_and_stable_order():
    repo, db = _repo()
    result = repo.get_for_update_batch(["CURRENT_VERSION", "MIN_SUPPORTED_VERSION"])
    assert result == {}
    sql = db.compiled[-1]
    assert "PULS_KONFIGURACIJA" in sql
    assert "FOR UPDATE" in sql
    assert "ORDER BY" in sql
    order_by_idx = sql.index("ORDER BY")
    for_update_idx = sql.index("FOR UPDATE")
    assert order_by_idx < for_update_idx  # ORDER BY mora doci PRE FOR UPDATE
    assert "KLJUC" in sql[order_by_idx:for_update_idx]


def test_get_for_update_batch_empty_list_short_circuits():
    repo, db = _repo()
    assert repo.get_for_update_batch([]) == {}
    assert db.compiled == []


def test_configuration_repository_get_values_batch_compiles():
    db = _CompileCapturingDb()
    repo = ConfigurationRepository(db)
    assert repo.get_values(["CURRENT_VERSION", "MIN_SUPPORTED_VERSION", "DOWNLOAD_URL"]) == {}
    sql = db.compiled[-1]
    assert "PULS_KONFIGURACIJA" in sql
    assert "AKTIVNA" in sql
    assert "IN" in sql


def test_configuration_repository_get_value_unchanged_compiles():
    """Regresija: postojeca get_value metoda mora i dalje raditi identicno."""
    db = _CompileCapturingDb()
    repo = ConfigurationRepository(db)
    assert repo.get_value("MIN_DUZINA_LOZINKE") is None
    sql = db.compiled[-1]
    assert "PULS_KONFIGURACIJA" in sql
    assert "AKTIVNA" in sql
