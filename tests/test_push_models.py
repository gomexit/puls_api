"""Oracle kompilacija tipova + provere DDL ugovora modula FCM PUSH."""

from sqlalchemy.dialects import oracle
from sqlalchemy.schema import CreateTable

from app.core.security import hash_push_token
from app.models.push import PUSH_STATUSI, PushIsporuka, PushToken

SQL = open("sql/004_fcm_push_module.sql", encoding="utf-8").read().upper()


def _ddl(model) -> str:
    return str(CreateTable(model.__table__).compile(dialect=oracle.dialect())).upper()


def test_token_column_types():
    ddl = _ddl(PushToken)
    assert '"FCM_TOKEN" VARCHAR(4000 CHAR)' in ddl
    assert '"TOKEN_HASH" VARCHAR(64 CHAR)' in ddl
    assert '"AKTIVAN" CHAR(1)' in ddl
    assert '"KORISNIK_ID" NUMERIC(19, 0)' in ddl


def test_delivery_column_types():
    ddl = _ddl(PushIsporuka)
    assert '"STATUS" VARCHAR(20 CHAR)' in ddl
    assert '"OBAVESTENJE_ID" NUMERIC(19, 0)' in ddl
    assert '"BROJ_POKUSAJA" NUMERIC(10, 0)' in ddl


def test_allowed_statuses():
    assert PUSH_STATUSI == ("PENDING", "SENT", "FAILED", "SKIPPED")


def test_hash_is_64_hex_and_deterministic():
    h = hash_push_token("some-fcm-token")
    assert len(h) == 64 and all(c in "0123456789abcdef" for c in h)
    assert h == hash_push_token("some-fcm-token")
    assert h != hash_push_token("drugi-token")


# --- DDL ugovori (iz sql/004) ---
def test_no_global_unique_constraint_on_token_hash():
    # Globalni UNIQUE(TOKEN_HASH) je UKLONJEN - isti fizicki token prirodno prolazi
    # kroz vise (istorijskih/neaktivnih) redova tokom vremena. Regex trazi tacno
    # "CONSTRAINT UX_PUSH_TOKEN_HASH" (a ne kao podstring imena drugih indeksa).
    import re

    assert re.search(r"CONSTRAINT\s+UX_PUSH_TOKEN_HASH\b", SQL) is None


def test_fcm_token_not_indexed_directly():
    # Pun FCM_TOKEN se NE indeksira direktno (nema indeksa nad tom kolonom).
    assert "(FCM_TOKEN" not in SQL and "(FCM_TOKEN)" not in SQL


def test_active_only_unique_indexes_present():
    # Function-based unique indeksi: jedinstvenost SAMO medju aktivnim (AKTIVAN='D')
    # redovima - istorijski/neaktivni redovi smeju deliti isti hash/korisnika.
    assert "CREATE UNIQUE INDEX UX_PUSH_TOKEN_AKTIVAN_HASH" in SQL
    assert "CASE WHEN AKTIVAN = 'D' THEN TOKEN_HASH END" in SQL
    assert "CREATE UNIQUE INDEX UX_PUSH_TOKEN_AKTIVAN_KOR" in SQL
    assert "CASE WHEN AKTIVAN = 'D' THEN KORISNIK_ID END" in SQL


def test_unique_constraints_present():
    assert "UX_PUSH_TOKEN_KOR_UREDJAJ UNIQUE (KORISNIK_ID, UREDJAJ_ID)" in SQL
    assert "UX_PUSH_ISP_OBAV_KOR UNIQUE (OBAVESTENJE_ID, KORISNIK_ID)" in SQL


def test_status_and_attempt_checks_present():
    assert "CK_PUSH_ISP_STATUS" in SQL
    assert "'PENDING', 'SENT', 'FAILED', 'SKIPPED'" in SQL
    assert "CK_PUSH_TOKEN_AKTIVAN" in SQL
    assert "CK_PUSH_ISP_POKUSAJA" in SQL


def test_ddl_marks_not_auto_executed():
    assert "NE IZVRSAVA" in SQL or "NE IZVRŠAVA" in SQL
