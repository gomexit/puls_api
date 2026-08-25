"""Proverava da KorisnikRepository.get_primary_active_raspored_with_names REALNO
kompajlira za Oracle dijalekt (bez zive konekcije) - hvata greske u nazivima
ORM kolona/join-ova/tabela koje in-memory fake repo ne bi otkrio."""

from sqlalchemy.dialects import oracle

from app.repositories.korisnik_repository import KorisnikRepository


class _StubResult:
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
    return KorisnikRepository(db), db


def test_returns_none_when_no_row():
    repo, db = _repo()
    assert repo.get_primary_active_raspored_with_names(1) is None
    assert db.compiled  # upit je pokusan


def test_uses_iis_orgjed_and_radnamesta_with_left_outer_join():
    repo, db = _repo()
    repo.get_primary_active_raspored_with_names(1)
    sql = db.compiled[-1]
    assert '"IIS"."ORGJED"' in sql
    assert '"IIS"."RADNAMESTA"' in sql
    assert "LEFT OUTER JOIN" in sql


def test_radno_mesto_join_uses_to_char_on_iis_side_only():
    repo, db = _repo()
    repo.get_primary_active_raspored_with_names(1)
    sql = db.compiled[-1]
    # IIS.RADNAMESTA.SIFRA (NUMBER) se konvertuje u tekst radi bezbednog poredjenja.
    assert 'TO_CHAR("IIS"."RADNAMESTA"."SIFRA")' in sql
    # PULS RADNO_MESTO_SIFRA (VARCHAR2) se NE sme konvertovati u NUMBER (ORA-01722 rizik).
    assert 'TO_NUMBER("PULS_KORISNIK_RASPOREDI"."RADNO_MESTO_SIFRA")' not in sql


def test_selects_only_needed_columns_not_star():
    repo, db = _repo()
    repo.get_primary_active_raspored_with_names(1)
    sql = db.compiled[-1]
    assert "SELECT *" not in sql
    assert "ORGJED_SIFRA" in sql
    assert "RADNO_MESTO_SIFRA" in sql


def test_filters_only_active_raspored_for_the_user():
    repo, db = _repo()
    repo.get_primary_active_raspored_with_names(42)
    sql = db.compiled[-1]
    assert "AKTIVAN" in sql
    assert '"PULS_KORISNIK_RASPOREDI"."KORISNIK_ID"' in sql


def test_orders_by_primarni_case_then_id_not_primarni_desc():
    """Regresija: primarni.desc() bi pogresno stavilo 'N' ispred 'D' (alfabetski).
    ORDER BY mora koristiti CASE prioritet + ID kao stabilan tie-breaker."""
    repo, db = _repo()
    repo.get_primary_active_raspored_with_names(1)
    sql = db.compiled[-1]
    assert "ORDER BY" in sql
    assert "CASE" in sql
    assert "PRIMARNI DESC" not in sql
    order_by_clause = sql.split("ORDER BY", 1)[1]
    assert '"PULS_KORISNIK_RASPOREDI"."ID"' in order_by_clause
