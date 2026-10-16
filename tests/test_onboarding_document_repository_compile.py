"""Repository upiti REALNO kompajliraju za Oracle dijalekat (bez konekcije) i lista
nikada ne selektuje BLOB kolonu SADRZAJ niti koristi SELECT *."""

import pytest
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


# ============================================================ SORTIRANJE (admin lista)
from app.core.sorting import SortSpec  # noqa: E402
from app.repositories.onboarding_document_repository import (  # noqa: E402
    ADMIN_DEFAULT_SORT,
    ADMIN_SORT_COLUMNS,
)

_TEXT_COLUMNS = {"naziv", "originalni_naziv_fajla"}


def _last_select(sort):
    repo, db = _repo()
    repo.list_admin(None, None, 1, 20, sort)
    # compiled[0] je COUNT, compiled[-1] je SELECT sa ORDER BY (navodnici se uklanjaju)
    return " ".join(db.compiled[-1].replace('"', "").split())


def test_admin_sortable_columns_are_the_documented_whitelist():
    assert list(ADMIN_SORT_COLUMNS) == [
        "id", "naziv", "originalni_naziv_fajla", "status", "redosled", "verzija",
        "velicina_bajtova", "datum_kreiranja", "datum_izmene", "datum_objave",
    ]
    for blocked in ("opis", "sadrzaj", "sha256", "mime_tip", "kreirao_platni_broj"):
        assert blocked not in ADMIN_SORT_COLUMNS


def test_default_sort_is_redosled_then_id_like_before():
    assert ADMIN_DEFAULT_SORT == SortSpec("redosled", "asc")
    sql = _last_select(None)
    assert "ORDER BY PULS_ONBOARDING_DOKUMENTI.REDOSLED ASC NULLS LAST, PULS_ONBOARDING_DOKUMENTI.ID ASC" in sql


def test_every_sortable_column_both_directions_compiles_with_tiebreaker_and_no_blob():
    for by in ADMIN_SORT_COLUMNS:
        for direction in ("asc", "desc"):
            sql = _last_select(SortSpec(by, direction))
            word = direction.upper()
            order_by = sql.split("ORDER BY", 1)[1].split("OFFSET")[0]
            assert f"{word} NULLS LAST" in order_by, (by, direction)
            assert order_by.strip().split(",")[-1].strip().startswith("PULS_ONBOARDING_DOKUMENTI.ID " + word), (
                by, direction, order_by,
            )
            assert "SADRZAJ" not in sql
            assert ("NLSSORT" in order_by) == (by in _TEXT_COLUMNS), (by, order_by)


def test_status_is_sorted_by_workflow_not_alphabet():
    # CASE vrednosti su bind parametri, pa se izraz kompajlira sa ugradjenim literalima
    expr = ADMIN_SORT_COLUMNS["status"].expr
    sql = str(expr.compile(dialect=oracle.dialect(), compile_kwargs={"literal_binds": True}))
    sql = " ".join(sql.replace('"', "").upper().split())
    assert sql.startswith("CASE")
    assert sql.index("'DRAFT'") < sql.index("'PUBLISHED'") < sql.index("'ARCHIVED'")
    # i stvarno se koristi u ORDER BY upitu
    assert "CASE" in _last_select(SortSpec("status", "asc")).split("ORDER BY", 1)[1]


def test_sort_works_together_with_filter_search_and_pagination():
    repo, db = _repo()
    repo.list_admin("PUBLISHED", "pravil", 3, 25, SortSpec("naziv", "desc"))
    sql = " ".join(db.compiled[-1].replace('"', "").split())
    assert "WHERE" in sql and "LOWER(" in sql and "LIKE" in sql
    assert "NLSSORT" in sql and "DESC NULLS LAST" in sql
    assert "OFFSET" in sql and "FETCH" in sql


def test_repository_rejects_a_column_outside_the_whitelist():
    repo, _ = _repo()
    with pytest.raises(ValueError):
        repo.list_admin(None, None, 1, 20, SortSpec("sadrzaj", "asc"))
