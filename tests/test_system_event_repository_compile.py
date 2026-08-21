"""Proverava da SystemEventRepository upiti REALNO kompajliraju za Oracle dijalekt
(bez zive konekcije) - hvata greske u nazivima ORM kolona/tabela."""

import datetime

from sqlalchemy.dialects import oracle

from app.repositories.system_event_repository import SystemEventRepository


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
    return SystemEventRepository(db), db


NOW = datetime.datetime(2026, 1, 1, 10, 0, 0)
WINDOW_END = NOW + datetime.timedelta(hours=24)


def test_enqueue_if_absent_select_compiles():
    repo, db = _repo()
    created = repo.enqueue_if_absent("SURVEY_ACTIVATED:1", "SURVEY_ACTIVATED", 1, None, NOW)
    assert created is True
    sql = db.compiled[-1]
    assert "PULS_SISTEMSKI_DOGADJAJI" in sql
    assert "DOGADJAJ_KLJUC" in sql


def test_list_ready_ids_compiles():
    repo, db = _repo()
    assert repo.list_ready_ids(NOW, 50) == []
    sql = db.compiled[-1]
    assert "PULS_SISTEMSKI_DOGADJAJI" in sql
    assert "STATUS" in sql
    assert "ORDER BY" in sql


def test_get_for_update_compiles_with_lock():
    repo, db = _repo()
    assert repo.get_for_update(1) is None
    sql = db.compiled[-1]
    assert "PULS_SISTEMSKI_DOGADJAJI" in sql
    assert "FOR UPDATE" in sql


def test_find_scheduled_surveys_now_active_compiles():
    repo, db = _repo()
    assert repo.find_scheduled_surveys_now_active(NOW) == []
    sql = db.compiled[-1]
    assert "PULS_ANKETE" in sql
    assert "SCHEDULED" in sql


def test_find_surveys_expiring_within_compiles():
    repo, db = _repo()
    assert repo.find_surveys_expiring_within(NOW, WINDOW_END) == []
    sql = db.compiled[-1]
    assert "PULS_ANKETE" in sql


def test_find_cycles_expiring_within_compiles():
    repo, db = _repo()
    assert repo.find_cycles_expiring_within(NOW, WINDOW_END) == []
    sql = db.compiled[-1]
    assert "PULS_IDEA_CIKLUSI" in sql
    assert "AKTIVAN" in sql


def test_survey_participant_ids_compiles():
    repo, db = _repo()
    assert repo.survey_participant_ids(1) == set()
    sql = db.compiled[-1]
    assert "PULS_ANKETA_UCESCA" in sql


def test_survey_participant_ids_not_submitted_compiles():
    repo, db = _repo()
    assert repo.survey_participant_ids_not_submitted(1) == set()
    sql = db.compiled[-1]
    assert "PULS_ANKETA_UCESCA" in sql
    assert "SUBMITTED" in sql


def test_user_ids_with_idea_in_cycle_compiles():
    repo, db = _repo()
    assert repo.user_ids_with_idea_in_cycle(1) == set()
    sql = db.compiled[-1]
    assert "PULS_IDEJE" in sql


def test_get_survey_get_cycle_get_idea_use_session_get_not_execute():
    repo, db = _repo()
    assert repo.get_survey(1) is None
    assert repo.get_cycle(1) is None
    assert repo.get_idea(1) is None
    # db.get(...) (Session.get) se koristi za resolve po ID-u - ne prolazi kroz execute().
    assert db.compiled == []
