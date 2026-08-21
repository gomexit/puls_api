"""Proverava da SurveyResultsRepository upiti REALNO kompajliraju za Oracle dijalekt
(bez zive konekcije), koristeci prave metode/model atribute - hvata greske u
nazivima ORM kolona/join-ova koje in-memory fake repo ne bi otkrio."""

from sqlalchemy.dialects import oracle

from app.repositories.korisnik_repository import KorisnikRepository
from app.repositories.survey_results_repository import SurveyResultsRepository


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
    """Ne izvrsava upit nad bazom - kompajlira ga za Oracle dijalekt (baca izuzetak
    na svaku gresku u imenima kolona/tabela/join-ova) i belezi generisani SQL."""

    def __init__(self):
        self.compiled: list[str] = []

    def execute(self, stmt):
        compiled = stmt.compile(dialect=oracle.dialect())
        self.compiled.append(str(compiled).upper())
        return _StubResult()


def _repo():
    db = _CompileCapturingDb()
    return SurveyResultsRepository(db), db


def test_ucesce_status_counts_compiles():
    repo, db = _repo()
    assert repo.ucesce_status_counts(1) == {}
    assert "PULS_ANKETA_UCESCA" in db.compiled[-1]
    assert "GROUP BY" in db.compiled[-1]


def test_answer_counts_by_question_compiles():
    repo, db = _repo()
    assert repo.answer_counts_by_question(1) == {}
    sql = db.compiled[-1]
    assert "PULS_ANKETA_ODGOVORI" in sql
    assert "PULS_ANKETA_PREDAJE" in sql
    # Nikad ne sme selektovati KORISNIK_ID (identitet) u agregatnom upitu.
    assert "KORISNIK_ID" not in sql


def test_option_choice_counts_compiles():
    repo, db = _repo()
    assert repo.option_choice_counts(1) == {}
    sql = db.compiled[-1]
    assert "PULS_ANKETA_ODGOVOR_OPCIJE" in sql
    assert "PULS_ANKETA_ODGOVORI" in sql
    assert "KORISNIK_ID" not in sql


def test_boolean_counts_compiles():
    repo, db = _repo()
    assert repo.boolean_counts(1) == {}
    sql = db.compiled[-1]
    assert "LOGICKA" in sql
    assert "KORISNIK_ID" not in sql


def test_rating_value_counts_compiles():
    repo, db = _repo()
    assert repo.rating_value_counts(1) == {}
    sql = db.compiled[-1]
    assert "BROJ" in sql
    assert "KORISNIK_ID" not in sql


def test_list_final_submissions_compiles_with_all_filters():
    import datetime

    repo, db = _repo()
    rows, total = repo.list_final_submissions(
        survey_id=1,
        platni_broj="12345",
        orgjed_sifra="001",
        radno_mesto_sifra="PRODAVAC",
        datum_od=datetime.datetime(2026, 1, 1),
        datum_do=datetime.datetime(2026, 2, 1),
        page=1,
        page_size=20,
    )
    assert rows == [] and total == 0
    sql = "".join(db.compiled).upper()
    assert "PULS_ANKETA_PREDAJE" in sql
    assert "PULS_KORISNICI" in sql
    assert "PULS_KORISNIK_RASPOREDI" in sql
    assert "EXISTS" in sql


def test_get_final_answers_for_predaje_compiles():
    repo, db = _repo()
    assert repo.get_final_answers_for_predaje([1, 2, 3]) == []
    assert "PULS_ANKETA_ODGOVORI" in db.compiled[-1]


def test_get_final_answer_options_for_odgovori_compiles():
    repo, db = _repo()
    assert repo.get_final_answer_options_for_odgovori([1, 2, 3]) == []
    assert "PULS_ANKETA_ODGOVOR_OPCIJE" in db.compiled[-1]


def test_primary_active_rasporedi_compiles():
    repo, db = _repo()
    assert repo.primary_active_rasporedi([1, 2, 3]) == {}
    sql = db.compiled[-1]
    assert "PULS_KORISNIK_RASPOREDI" in sql
    assert "AKTIVAN" in sql


def test_primary_active_rasporedi_orders_by_case_not_primarni_desc():
    """Regresija: primarni.desc() bi stavilo 'N' ispred 'D'. ORDER BY mora koristiti CASE."""
    repo, db = _repo()
    repo.primary_active_rasporedi([1])
    sql = db.compiled[-1]
    assert "ORDER BY" in sql
    assert "CASE" in sql
    assert "PRIMARNI DESC" not in sql


def test_orgjed_and_radno_mesto_use_single_combined_exists():
    repo, db = _repo()
    repo.list_final_submissions(
        survey_id=1,
        platni_broj=None,
        orgjed_sifra="001",
        radno_mesto_sifra="PRODAVAC",
        datum_od=None,
        datum_do=None,
        page=1,
        page_size=20,
    )
    page_sql = db.compiled[-1]  # paginirani upit (poslednji izvrsen)
    # Jedan korelisani EXISTS (ne dva nezavisna) kada su oba filtera prosledjena.
    assert page_sql.count("EXISTS") == 1
    assert "ORGJED_SIFRA" in page_sql and "RADNO_MESTO_SIFRA" in page_sql


def test_empty_id_lists_short_circuit_without_query():
    repo, db = _repo()
    assert repo.get_final_answers_for_predaje([]) == []
    assert repo.get_final_answer_options_for_odgovori([]) == []
    assert repo.primary_active_rasporedi([]) == {}
    assert db.compiled == []  # nijedan upit nije ni pokusan


def test_korisnik_repository_primary_raspored_orders_by_case_not_primarni_desc():
    """Ista regresija kao za primary_active_rasporedi, u KorisnikRepository."""
    db = _CompileCapturingDb()
    KorisnikRepository(db).get_primary_active_raspored(1)
    sql = db.compiled[-1]
    assert "ORDER BY" in sql
    assert "CASE" in sql
    assert "PRIMARNI DESC" not in sql
