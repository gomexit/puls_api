"""Oracle compile test (bez zive konekcije) za OnboardingAutomationRepository +
logicki testovi nad find_qualified_candidates uz fake-repo pattern (SQLite ne
podrzava Oracle DATE+dani aritmetiku pouzdano, pa logika ide preko fake-a)."""

import datetime

from sqlalchemy.dialects import oracle

from app.models.anketa_ucesce import AnketaAutomatika
from app.repositories.onboarding_automation_repository import OnboardingAutomationRepository


class _StubResult:
    def all(self):
        return []

    def scalars(self):
        return self

    def scalar_one(self):
        return 0

    def scalar_one_or_none(self):
        return None

    def first(self):
        return None


class _CompileCapturingDb:
    def __init__(self):
        self.compiled: list[str] = []

    def execute(self, stmt):
        compiled = stmt.compile(dialect=oracle.dialect(), compile_kwargs={"literal_binds": True})
        self.compiled.append(str(compiled).upper())
        return _StubResult()

    def add(self, obj) -> None:
        pass

    def flush(self) -> None:
        pass

    def get(self, model, pk):
        return None


def _repo():
    db = _CompileCapturingDb()
    return OnboardingAutomationRepository(db), db


def _pravilo(**ov) -> AnketaAutomatika:
    defaults = dict(
        id=1,
        anketa_id=10,
        dani_od_zaposlenja=7,
        rok_dana=7,
        datum_primene_od=datetime.date(2026, 1, 1),
        aktivna="D",
    )
    defaults.update(ov)
    return AnketaAutomatika(**defaults)


NOW = datetime.datetime(2026, 6, 1, 10, 0, 0)


def test_list_all_compiles():
    repo, db = _repo()
    assert repo.list_all() == []
    sql = db.compiled[-1]
    assert "PULS_ANKETA_AUTOMATIKA" in sql


def test_get_by_survey_id_compiles():
    repo, db = _repo()
    assert repo.get_by_survey_id(10) is None
    sql = db.compiled[-1]
    assert "PULS_ANKETA_AUTOMATIKA" in sql
    assert "ANKETA_ID" in sql


def test_get_for_update_compiles_with_lock():
    repo, db = _repo()
    assert repo.get_for_update(1) is None
    sql = db.compiled[-1]
    assert "PULS_ANKETA_AUTOMATIKA" in sql
    assert "FOR UPDATE" in sql


def test_find_active_rules_compiles():
    repo, db = _repo()
    assert repo.find_active_rules() == []
    sql = db.compiled[-1]
    assert "PULS_ANKETA_AUTOMATIKA" in sql
    assert "AKTIVNA" in sql


def test_find_qualified_candidates_compiles():
    repo, db = _repo()
    pravilo = _pravilo()
    assert repo.find_qualified_candidates(pravilo, NOW) == []
    sql = db.compiled[-1]
    assert "PULS_KORISNICI" in sql
    assert "STATUS_ZAPOSLENJA" in sql
    assert "STATUS_NALOGA" in sql
    assert "DATUM_ZAPOSLENJA" in sql


def test_find_qualified_candidates_uses_not_exists_against_ucesca():
    """N+1 fix: provera postojeceg PULS_ANKETA_UCESCA reda mora biti KORELISANI
    NOT EXISTS unutar istog upita, ne poseban upit po kandidatu."""
    repo, db = _repo()
    pravilo = _pravilo(anketa_id=10)
    assert repo.find_qualified_candidates(pravilo, NOW) == []
    sql = db.compiled[-1]
    assert "NOT (EXISTS" in sql or "NOT EXISTS" in sql
    assert "PULS_ANKETA_UCESCA" in sql


def test_existing_participation_exists_compiles():
    repo, db = _repo()
    assert repo.existing_participation_exists(10, 5) is False
    sql = db.compiled[-1]
    assert "PULS_ANKETA_UCESCA" in sql


def test_get_and_add_use_session_get_not_execute():
    repo, db = _repo()
    assert repo.get(1) is None
    assert db.compiled == []
