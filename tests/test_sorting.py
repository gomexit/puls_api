"""Zajednicki modul za sortiranje GET lista (app/core/sorting.py)."""

import pytest
from sqlalchemy import Column, Integer, MetaData, Table, select
from sqlalchemy.dialects import oracle
from sqlalchemy.dialects.oracle import NVARCHAR2

from app.core.exceptions import ValidationBusinessError
from app.core.sorting import SortColumn, SortSpec, build_order_by, sort_params

_t = Table(
    "T",
    MetaData(),
    Column("ID", Integer, primary_key=True),
    Column("NAZIV", NVARCHAR2(50)),
    Column("BROJ", Integer),
)
COLUMNS = {
    "id": SortColumn(_t.c.ID),
    "naziv": SortColumn(_t.c.NAZIV, text=True),
    "broj": SortColumn(_t.c.BROJ),
}


def _sql(spec: SortSpec) -> str:
    stmt = select(_t.c.ID).order_by(*build_order_by(spec, COLUMNS, _t.c.ID))
    # navodnici oko imena se uklanjaju radi citljivijih poredjenja
    compiled = str(stmt.compile(dialect=oracle.dialect())).upper().replace('"', "")
    return " ".join(compiled.split())


# ------------------------------------------------------------------ ORDER BY
def test_asc_has_nulls_last_and_tiebreaker_in_same_direction():
    sql = _sql(SortSpec("broj", "asc"))
    assert sql.endswith("ORDER BY T.BROJ ASC NULLS LAST, T.ID ASC")


def test_desc_has_nulls_last_and_tiebreaker_in_same_direction():
    sql = _sql(SortSpec("broj", "desc"))
    assert sql.endswith("ORDER BY T.BROJ DESC NULLS LAST, T.ID DESC")


def test_text_column_uses_serbian_linguistic_collation():
    sql = _sql(SortSpec("naziv", "asc"))
    assert "NLSSORT(T.NAZIV, 'NLS_SORT=XCROATIAN') ASC NULLS LAST" in sql
    assert sql.endswith("T.ID ASC")


def test_text_column_puts_digit_leading_values_first_then_the_collation():
    # XCROATIAN stavlja cifre IZA slova; zato prvo ide grupa 'pocinje cifrom', pa kolacija
    sql = _sql(SortSpec("naziv", "asc"))
    order_by = sql.split("ORDER BY", 1)[1]
    assert order_by.index("REGEXP_LIKE") < order_by.index("NLSSORT") < order_by.rindex("T.ID")
    assert "WHEN (T.NAZIV IS NULL) THEN NULL" in order_by  # NULL ostaje NULL -> uvek na kraju
    assert order_by.count("NULLS LAST") == 2
    desc = _sql(SortSpec("naziv", "desc"))
    assert desc.count("DESC NULLS LAST") == 2 and desc.endswith("T.ID DESC")


def test_non_text_columns_have_no_digit_group():
    assert "REGEXP_LIKE" not in _sql(SortSpec("broj", "asc"))
    assert "REGEXP_LIKE" not in _sql(SortSpec("id", "desc"))


def test_non_text_column_does_not_use_collation():
    assert "NLSSORT" not in _sql(SortSpec("broj", "asc"))
    assert "NLSSORT" not in _sql(SortSpec("id", "asc"))


def test_unknown_column_is_a_programming_error_not_sql():
    with pytest.raises(ValueError):
        build_order_by(SortSpec("naziv; DROP TABLE T", "asc"), COLUMNS, _t.c.ID)


def test_user_text_never_reaches_sql():
    # `by` mora biti kljuc mape: bilo sta drugo se odbija pre pravljenja ORDER BY-a
    for bad in ("1=1", "ID DESC, (SELECT 1 FROM DUAL)", "naziv --", ""):
        with pytest.raises(ValueError):
            build_order_by(SortSpec(bad, "asc"), COLUMNS, _t.c.ID)


# --------------------------------------------------------------- sort_params
def _dep(default_by="naziv", default_dir="asc"):
    return sort_params(allowed=list(COLUMNS), default_by=default_by, default_dir=default_dir)


def test_defaults_when_nothing_sent():
    assert _dep("broj", "desc")(sort_by=None, sort_dir=None) == SortSpec("broj", "desc")


def test_sort_by_only_defaults_to_ascending():
    assert _dep("broj", "desc")(sort_by="naziv", sort_dir=None) == SortSpec("naziv", "asc")


def test_sort_dir_only_applies_to_default_column():
    assert _dep("broj", "asc")(sort_by=None, sort_dir="desc") == SortSpec("broj", "desc")


def test_values_are_trimmed_and_case_insensitive():
    assert _dep()(sort_by="  BROJ ", sort_dir=" DESC ") == SortSpec("broj", "desc")


def test_blank_values_are_treated_as_missing():
    # DataTables moze da posalje prazne parametre
    assert _dep("broj", "desc")(sort_by="  ", sort_dir="") == SortSpec("broj", "desc")


@pytest.mark.parametrize("bad", ["opis", "sadrzaj", "x; drop table t", "1=1", "naziv,broj"])
def test_unknown_column_is_validation_error_listing_allowed(bad):
    with pytest.raises(ValidationBusinessError) as exc:
        _dep()(sort_by=bad, sort_dir=None)
    assert "id, naziv, broj" in str(exc.value)


@pytest.mark.parametrize("bad", ["up", "ascending", "asc,desc", "1"])
def test_unknown_direction_is_validation_error(bad):
    with pytest.raises(ValidationBusinessError):
        _dep()(sort_by="naziv", sort_dir=bad)


def test_misconfigured_defaults_fail_fast():
    with pytest.raises(ValueError):
        sort_params(allowed=["id"], default_by="naziv")
    with pytest.raises(ValueError):
        sort_params(allowed=["id"], default_by="id", default_dir="sideways")
