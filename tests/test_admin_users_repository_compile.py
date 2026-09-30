"""Proverava da AdminUsersRepository upiti REALNO kompajliraju za Oracle dijalekt
(bez zive konekcije) - hvata greske u nazivima ORM kolona/join-ova koje in-memory
fake repo ne bi otkrio."""

from sqlalchemy.dialects import oracle

from app.repositories.admin_users_repository import AdminUsersRepository


class _StubResult:
    def all(self):
        return []

    def scalars(self):
        return self

    def scalar_one(self):
        return 0

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
    return AdminUsersRepository(db), db


def test_get_by_id_for_update_compiles_with_lock():
    repo, db = _repo()
    assert repo.get_by_id_for_update(1) is None
    sql = db.compiled[-1]
    assert "PULS_KORISNICI" in sql
    assert "FOR UPDATE" in sql


def test_list_users_all_filters_compile():
    repo, db = _repo()
    rows, total = repo.list_users(
        search="petar",
        status_zaposlenja="AKTIVAN",
        status_naloga="OMOGUCEN",
        zakljucan=True,
        uloga="ADMIN",
        page=1,
        page_size=20,
    )
    assert rows == [] and total == 0
    sql = "".join(db.compiled).upper()
    assert "PULS_KORISNICI" in sql
    assert "PULS_KORISNIK_ULOGE" in sql
    assert "PULS_ULOGE" in sql
    assert "EXISTS" in sql
    # NAPOMENA: select(Korisnik) ucitava ceo ORM entitet (uklj. LOZINKA_HASH kolonu)
    # jer tako SQLAlchemy puni objekat - to je ocekivano. Zastita od curenja hash-a
    # je na nivou servisa/schema serijalizacije (vidi test_admin_users_service.py
    # test_response_never_contains_secrets i HTTP test test_list_response_shape_and_no_secrets).


def test_list_users_no_filters_compiles():
    repo, db = _repo()
    rows, total = repo.list_users(None, None, None, None, None, 1, 20)
    assert rows == [] and total == 0
    assert "PULS_KORISNICI" in db.compiled[-1]


def test_batch_active_role_codes_compiles():
    repo, db = _repo()
    assert repo.batch_active_role_codes([1, 2, 3]) == {}
    sql = db.compiled[-1]
    assert "PULS_KORISNIK_ULOGE" in sql
    assert "PULS_ULOGE" in sql
    assert "AKTIVNA" in sql


def test_batch_primary_active_rasporedi_orders_by_case_not_primarni_desc():
    """Regresija: primarni.desc() bi stavilo 'N' ispred 'D'. ORDER BY mora koristiti CASE."""
    repo, db = _repo()
    assert repo.batch_primary_active_rasporedi([1, 2, 3]) == {}
    sql = db.compiled[-1]
    assert "PULS_KORISNIK_RASPOREDI" in sql
    assert "ORDER BY" in sql
    assert "CASE" in sql
    assert "PRIMARNI DESC" not in sql


def test_empty_id_lists_short_circuit_without_query():
    repo, db = _repo()
    assert repo.batch_active_role_codes([]) == {}
    assert repo.batch_primary_active_rasporedi([]) == {}
    assert db.compiled == []


def _plain(sql: str) -> str:
    return sql.replace('"', "")


def test_list_users_orgjed_filter_compiles_with_primary_raspored():
    repo, db = _repo()
    rows, total = repo.list_users(None, None, None, None, None, 1, 20, orgjed=["101", "205"])
    assert rows == [] and total == 0
    count_sql, page_sql = _plain(db.compiled[-2]), _plain(db.compiled[-1])
    for sql in (count_sql, page_sql):  # i total i stranica postuju filter
        assert "PULS_KORISNIK_RASPOREDI" in sql
        assert "ORGJED_SIFRA IN" in sql
        # primarni raspored: COALESCE(MIN primarni, MIN bilo koji) - bez FETCH/ROWNUM u korelaciji
        assert "COALESCE" in sql and "MIN(" in sql
        assert "ROWNUM" not in sql
    assert "FETCH" not in count_sql
    assert page_sql.count("FETCH") == 1  # samo stranicenje


def test_list_users_orgjed_filter_combines_with_other_filters():
    repo, db = _repo()
    repo.list_users("petar", "AKTIVAN", None, None, "ADMIN", 1, 20, orgjed=["101"])
    sql = _plain(db.compiled[-1])
    assert "EXISTS" in sql and "ORGJED_SIFRA IN" in sql


def test_batch_primary_active_rasporedi_joins_iis_names():
    repo, db = _repo()
    assert repo.batch_primary_active_rasporedi([1, 2]) == {}
    sql = _plain(db.compiled[-1])
    assert "LEFT OUTER JOIN IIS.ORGJED" in sql
    assert "LEFT OUTER JOIN IIS.RADNAMESTA" in sql
    assert "TO_CHAR(IIS.RADNAMESTA.SIFRA)" in sql


def test_list_orgjed_compiles_distinct_active_only():
    repo, db = _repo()
    assert repo.list_orgjed() == []
    sql = _plain(db.compiled[-1])
    assert "SELECT DISTINCT" in sql
    assert "LEFT OUTER JOIN IIS.ORGJED" in sql
    assert "AKTIVAN" in sql
