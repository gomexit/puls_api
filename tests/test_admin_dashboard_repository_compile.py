"""Proverava da AdminDashboardRepository upiti REALNO kompajliraju za Oracle dijalekt
(bez zive konekcije) i da je svaki domen tacno JEDAN SQL round-trip (ukljucujuci
domene koji obuhvataju vise tabela preko skalarnih pod-upita)."""

from sqlalchemy.dialects import oracle

from app.repositories.admin_dashboard_repository import AdminDashboardRepository


class _StubResult:
    def __init__(self, row):
        self._row = row

    def one(self):
        return self._row


class _CompileCapturingDb:
    def __init__(self):
        self.compiled: list[str] = []

    def execute(self, stmt):
        compiled = stmt.compile(dialect=oracle.dialect())
        self.compiled.append(str(compiled).upper())
        # Row duzine tacno onoliko koliko upit stvarno selektuje kolona - potrebno
        # jer repository metode raspakuju/zip-uju (strict=True) po tacnom broju.
        width = len(stmt.selected_columns)
        return _StubResult(tuple(0 for _ in range(width)))


def _repo():
    db = _CompileCapturingDb()
    return AdminDashboardRepository(db), db


def test_korisnici_counts_single_query():
    repo, db = _repo()
    result = repo.korisnici_counts()
    assert len(db.compiled) == 1
    sql = db.compiled[-1]
    assert "PULS_KORISNICI" in sql
    assert result == {"aktivni": 0, "neaktivni": 0, "aktivirali_aplikaciju": 0, "zakljucani": 0}


def test_ankete_counts_single_query_multi_table():
    repo, db = _repo()
    result = repo.ankete_counts()
    assert len(db.compiled) == 1
    sql = db.compiled[-1]
    assert "PULS_ANKETE" in sql
    assert "PULS_ANKETA_UCESCA" in sql
    assert "FROM DUAL" in sql
    assert result["procenat_odziva"] == 0.0


def test_ideje_counts_single_query():
    repo, db = _repo()
    repo.ideje_counts()
    assert len(db.compiled) == 1
    sql = db.compiled[-1]
    assert "PULS_IDEJE" in sql


def test_obavestenja_counts_single_query_multi_table():
    repo, db = _repo()
    repo.obavestenja_counts()
    assert len(db.compiled) == 1
    sql = db.compiled[-1]
    assert "PULS_OBAVESTENJA" in sql
    assert "PULS_OBAVESTENJE_PRIMAOCI" in sql
    assert "PULS_PUSH_ISPORUKE" in sql
    assert "FROM DUAL" in sql
