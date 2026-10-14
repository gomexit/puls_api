"""Repository upiti REALNO kompajliraju za Oracle dijalekat (bez konekcije) i lista
nikada ne selektuje BLOB kolonu SADRZAJ niti koristi SELECT *."""

from sqlalchemy.dialects import oracle

from app.repositories.onboarding_document_repository import OnboardingDocumentRepository


class _Result:
    def all(self):
        return []

    def first(self):
        return None

    def scalar_one(self):
        return 0

    def scalar_one_or_none(self):
        return None


class _CompileCapturingDb:
    def __init__(self):
        self.compiled: list[str] = []

    def execute(self, stmt):
        self.compiled.append(
            str(stmt.compile(dialect=oracle.dialect(), compile_kwargs={"literal_binds": False})).upper()
        )
        return _Result()


def _repo():
    db = _CompileCapturingDb()
    return OnboardingDocumentRepository(db), db


def test_list_published_has_no_blob_and_no_select_star():
    repo, db = _repo()
    repo.list_published()
    sql = "".join(db.compiled)
    assert "PULS_ONBOARDING_DOKUMENTI" in sql
    assert "SADRZAJ" not in sql
    assert "SHA256" not in sql
    assert "SELECT *" not in sql
    assert "STATUS" in sql
    assert "ORDER BY" in sql and "REDOSLED" in sql and "ID" in sql


def test_employee_detail_has_no_blob():
    repo, db = _repo()
    repo.get_published(1)
    assert "SADRZAJ" not in "".join(db.compiled)


def test_admin_list_has_no_blob_and_supports_all_filters():
    repo, db = _repo()
    rows, total = repo.list_admin("PUBLISHED", "pravil_nik%", 2, 25)
    assert rows == [] and total == 0
    sql = "".join(db.compiled)
    assert "SADRZAJ" not in sql
    assert "SELECT *" not in sql
    assert "COUNT(" in sql
    assert "LOWER(" in sql and "LIKE" in sql
    assert "OFFSET" in sql and "FETCH" in sql  # paginacija na Oracle 19c
    assert "ORDER BY" in sql


def test_admin_detail_has_no_blob():
    repo, db = _repo()
    repo.get_admin(1)
    assert "SADRZAJ" not in "".join(db.compiled)


def test_content_queries_select_blob_explicitly_for_one_row():
    repo, db = _repo()
    repo.get_published_content(1)
    repo.get_admin_content(1)
    assert all("SADRZAJ" in sql for sql in db.compiled)
    assert all("WHERE" in sql for sql in db.compiled)


def test_get_for_update_uses_for_update_and_defers_blob():
    repo, db = _repo()
    repo.get_for_update(1)
    sql = "".join(db.compiled)
    assert "FOR UPDATE" in sql
    assert "SADRZAJ" not in sql  # deferred kolona
