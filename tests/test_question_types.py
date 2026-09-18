"""Tipovi pitanja iz baze: registar + tip koji postoji SAMO u tabeli (RATING_1_4)
mora da radi kroz payload, strukturu, uslove, odgovore, vidljivost i statistiku."""

import datetime

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings, get_settings
from app.core.exceptions import ValidationBusinessError
from app.db.session import get_db
from app.dependencies import portal_auth
from app.main import app
from app.models.anketa import KOMP_SCALE, AnketaTipPitanja
from app.schemas.survey import (
    AdminCiljIn,
    AdminPitanjeIn,
    AdminSekcijaIn,
    AdminSurveyCreateRequest,
    AdminUslovIn,
    OdgovorIn,
)
from app.services import question_types
from app.services.question_types import BUILTIN_TYPES, QuestionType
from app.services.survey_payload_validation import validate_admin_survey_payload
from app.services.survey_results_service import SurveyResultsService
from app.services.survey_service import SurveyService
from app.services.survey_validation import validate_structure
from app.services.survey_visibility import AnswerValue, answer_tokens, is_answered
from tests.fakes import FakeAuditService, make_korisnik
from tests.survey_fakes import (
    FakeSurveyDb,
    FakeSurveyRepo,
    FakeTargetingRepo,
    add_cilj,
    add_pitanje,
    add_sekcija,
    add_ucesce,
    add_uslov,
    make_anketa,
    make_tip,
)
from tests.survey_results_fakes import FakeSurveyResultsRepo, make_odgovor, make_predaja

RATING_1_4 = QuestionType("RATING_1_4", "Ocena 1-4", KOMP_SCALE, 1, 4, redosled=55)
POVUCEN = QuestionType("RATING_0_3", "Ocena 0-3", KOMP_SCALE, 0, 3, aktivan=False)


@pytest.fixture
def db_types():
    """Simulira sadrzaj PULS_ANKETA_TIPOVI_PITANJA: 7 seed tipova + 2 dodata iz baze."""
    types = {t.sifra: t for t in (*BUILTIN_TYPES, RATING_1_4, POVUCEN)}
    question_types.set_provider(lambda: types)
    return types


# ==================================================================== registar
def test_builtin_types_match_legacy_codes():
    sifre = {t.sifra for t in question_types.list_question_types()}
    assert sifre == {
        "SINGLE_CHOICE",
        "MULTI_CHOICE",
        "DROPDOWN",
        "TEXT",
        "BOOLEAN",
        "RATING_1_5",
        "RATING_1_10",
    }
    assert question_types.get_question_type("RATING_1_5").raspon == (1, 5)
    assert question_types.get_question_type("RATING_1_10").raspon == (1, 10)


def test_unknown_or_empty_type_is_none():
    assert question_types.get_question_type("NEPOSTOJI") is None
    assert question_types.get_question_type(None) is None


def test_list_hides_inactive_by_default_and_sorts(db_types):
    aktivni = [t.sifra for t in question_types.list_question_types()]
    assert "RATING_0_3" not in aktivni
    assert aktivni.index("RATING_1_4") < aktivni.index("RATING_1_5")  # REDOSLED 55 < 60
    assert "RATING_0_3" in [t.sifra for t in question_types.list_question_types(only_active=False)]


def test_component_flags():
    assert question_types.get_question_type("SINGLE_CHOICE").jedna_opcija
    assert question_types.get_question_type("DROPDOWN").jedna_opcija
    multi = question_types.get_question_type("MULTI_CHOICE")
    assert multi.ima_opcije and not multi.jedna_opcija
    assert not question_types.get_question_type("TEXT").ima_opcije
    assert question_types.get_question_type("RATING_1_5").je_skala


def _reset_db_cache(monkeypatch):
    monkeypatch.setattr(question_types, "_cache", None)
    monkeypatch.setattr(question_types, "_cache_at", 0.0)
    question_types.set_provider(question_types._db_provider)


def test_db_provider_falls_back_to_builtins_when_table_is_missing(monkeypatch):
    def boom():
        raise RuntimeError("ORA-00942: table or view does not exist")

    _reset_db_cache(monkeypatch)
    monkeypatch.setattr(question_types, "_load_from_db", boom)

    assert question_types.get_question_type("RATING_1_5").raspon == (1, 5)


def test_db_provider_caches_within_ttl_and_keeps_last_good_state(monkeypatch):
    calls = {"n": 0}

    def load():
        calls["n"] += 1
        return {"RATING_1_4": RATING_1_4}

    _reset_db_cache(monkeypatch)
    monkeypatch.setattr(question_types, "_load_from_db", load)
    assert question_types.get_question_type("RATING_1_4") is RATING_1_4
    assert question_types.get_question_type("RATING_1_4") is RATING_1_4
    assert calls["n"] == 1  # drugi poziv je iz kesa

    def boom():
        raise RuntimeError("baza nedostupna")

    monkeypatch.setattr(question_types, "_cache_at", -10_000.0)  # istekao TTL
    monkeypatch.setattr(question_types, "_load_from_db", boom)
    assert question_types.get_question_type("RATING_1_4") is RATING_1_4  # poslednje dobro stanje


def test_load_from_db_maps_rows(monkeypatch):
    rows = [
        AnketaTipPitanja(
            sifra="RATING_1_4", naziv="Ocena 1-4", komponenta="SCALE",
            min_vrednost=1, max_vrednost=4, aktivan="D", redosled=55,
        ),
        AnketaTipPitanja(sifra="TEXT", naziv="Tekst", komponenta="TEXT", aktivan="N", redosled=40),
    ]

    class _Result:
        def scalars(self):
            return self

        def all(self):
            return rows

    class _Session:
        def execute(self, stmt):
            return _Result()

        def close(self):
            pass

    import app.db.session as session_mod

    monkeypatch.setattr(session_mod, "SessionLocal", lambda: _Session())
    loaded = question_types._load_from_db()
    assert loaded["RATING_1_4"].raspon == (1, 4)
    assert loaded["RATING_1_4"].aktivan is True
    assert loaded["TEXT"].aktivan is False and loaded["TEXT"].min_vrednost is None


# ============================================================= payload (admin)
def _payload(pitanja):
    now = datetime.datetime.now()
    return AdminSurveyCreateRequest(
        naziv="Anketa",
        tip_sifra="PULS",
        anonimna=False,
        datum_pocetka=now,
        datum_zavrsetka=now + datetime.timedelta(days=5),
        sekcije=[AdminSekcijaIn(naziv="S", redosled=1, pitanja=pitanja)],
        ciljevi=[AdminCiljIn(tip_cilja="SVI")],
    )


def test_payload_accepts_type_defined_only_in_database(db_types):
    validate_admin_survey_payload(_payload([AdminPitanjeIn(tekst="Ocena", tip="RATING_1_4", redosled=1)]))


def test_payload_rejects_type_missing_from_database():
    # Bez db_types fixture-a RATING_1_4 ne postoji -> isti odgovor kao za bilo koji nepoznat tip.
    with pytest.raises(ValidationBusinessError):
        validate_admin_survey_payload(_payload([AdminPitanjeIn(tekst="Ocena", tip="RATING_1_4", redosled=1)]))


def test_payload_rejects_inactive_type_for_new_question(db_types):
    with pytest.raises(ValidationBusinessError):
        validate_admin_survey_payload(_payload([AdminPitanjeIn(tekst="Ocena", tip="RATING_0_3", redosled=1)]))


def test_payload_condition_on_scale_control_needs_no_option_keys(db_types):
    validate_admin_survey_payload(
        _payload(
            [
                AdminPitanjeIn(kljuc="q1", tekst="Ocena", tip="RATING_1_4", redosled=1),
                AdminPitanjeIn(
                    tekst="Zašto?",
                    tip="TEXT",
                    redosled=2,
                    uslov=AdminUslovIn(pitanje_kljuc="q1", operator="IN", vrednosti=["1", "2"]),
                ),
            ]
        )
    )


# ======================================================== struktura (pre ACTIVE)
def _structure_survey(repo, uslov_vrednost):
    repo.add_type(make_tip())
    a = make_anketa(repo, status="DRAFT")
    sec = add_sekcija(repo, a.id, 1)
    q1 = add_pitanje(repo, sec.id, "RATING_1_4", redosled=1)
    q2 = add_pitanje(repo, sec.id, "TEXT", redosled=2, uslov_pitanje_id=q1.id, uslov_operator="EQUALS")
    add_uslov(repo, q2.id, uslov_vrednost)
    add_cilj(repo, a.id, "SVI")
    return a


def test_structure_condition_value_inside_database_range(db_types):
    repo = FakeSurveyRepo()
    a = _structure_survey(repo, "4")
    validate_structure(repo, FakeTargetingRepo(all_ids={1}), a)


def test_structure_condition_value_outside_database_range(db_types):
    repo = FakeSurveyRepo()
    a = _structure_survey(repo, "5")  # validno za RATING_1_5, ne za RATING_1_4
    with pytest.raises(ValidationBusinessError) as exc:
        validate_structure(repo, FakeTargetingRepo(all_ids={1}), a)
    assert "1-4" in str(exc.value.message if hasattr(exc.value, "message") else exc.value)


def test_structure_rejects_question_with_unknown_type():
    repo = FakeSurveyRepo()
    a = _structure_survey(repo, "4")  # bez db_types: RATING_1_4 nepoznat
    with pytest.raises(ValidationBusinessError):
        validate_structure(repo, FakeTargetingRepo(all_ids={1}), a)


def test_structure_scale_must_not_have_options(db_types):
    from tests.survey_fakes import add_opcija

    repo = FakeSurveyRepo()
    repo.add_type(make_tip())
    a = make_anketa(repo, status="DRAFT")
    sec = add_sekcija(repo, a.id, 1)
    q = add_pitanje(repo, sec.id, "RATING_1_4", redosled=1)
    add_opcija(repo, q.id, 1)
    add_cilj(repo, a.id, "SVI")
    with pytest.raises(ValidationBusinessError):
        validate_structure(repo, FakeTargetingRepo(all_ids={1}), a)


# ================================================================== vidljivost
def test_visibility_helpers_use_component(db_types):
    assert is_answered("RATING_1_4", AnswerValue(broj=3))
    assert not is_answered("RATING_1_4", AnswerValue())
    assert answer_tokens("RATING_1_4", AnswerValue(broj=3)) == {"3"}
    assert answer_tokens("NEPOSTOJI", AnswerValue(broj=3)) == set()


# ============================================================ odgovori zaposlenog
USER_ID = 7


def _answer_service(repo):
    repo.add_type(make_tip())
    return SurveyService(db=FakeSurveyDb(), repository=repo, audit_service=FakeAuditService())


def _user():
    return make_korisnik(id=USER_ID, platni_broj="55", obavezna_promena_lozinke="N", telefon_potvrdjen="D")


def _rating_survey(repo):
    a = make_anketa(repo, status="ACTIVE", anonimna="N")
    sec = add_sekcija(repo, a.id, 1)
    q = add_pitanje(repo, sec.id, "RATING_1_4", redosled=1, obavezno="D")
    add_ucesce(repo, a.id, USER_ID, "NOT_STARTED")
    return a, q


def test_answer_inside_database_range_is_accepted(db_types):
    repo = FakeSurveyRepo()
    service = _answer_service(repo)
    a, q = _rating_survey(repo)
    service.submit(_user(), a.id, [OdgovorIn(pitanje_id=q.id, broj=4)])
    assert repo.get_ucesce(a.id, USER_ID).status == "SUBMITTED"


def test_answer_outside_database_range_is_rejected(db_types):
    repo = FakeSurveyRepo()
    service = _answer_service(repo)
    a, q = _rating_survey(repo)
    with pytest.raises(ValidationBusinessError):
        service.submit(_user(), a.id, [OdgovorIn(pitanje_id=q.id, broj=5)])


def test_scale_answer_must_be_number_only(db_types):
    repo = FakeSurveyRepo()
    service = _answer_service(repo)
    a, q = _rating_survey(repo)
    with pytest.raises(ValidationBusinessError):
        service.submit(_user(), a.id, [OdgovorIn(pitanje_id=q.id, broj=2, tekst="dva")])


# ================================================================== statistika
def test_statistics_distribution_follows_database_range(db_types):
    survey_repo = FakeSurveyRepo()
    results_repo = FakeSurveyResultsRepo(survey_repo)
    service = SurveyResultsService(db=None, results_repository=results_repo, survey_repository=survey_repo)
    a = make_anketa(survey_repo, status="CLOSED")
    sec = add_sekcija(survey_repo, a.id)
    q = add_pitanje(survey_repo, sec.id, "RATING_1_4", redosled=1)
    for i, v in enumerate([1, 4, 4]):
        p = make_predaja(survey_repo, a.id, korisnik_id=i)
        make_odgovor(survey_repo, p.id, q.id, broj=v)

    pitanje = service.get_statistics(a.id)["pitanja"][0]
    assert pitanje["tip_pitanja"] == "RATING_1_4"
    assert pitanje["komponenta"] == "SCALE"
    assert [r["vrednost"] for r in pitanje["raspodela"]] == [1, 2, 3, 4]
    assert pitanje["maksimum"] == 4


def test_statistics_reports_component_for_legacy_types():
    survey_repo = FakeSurveyRepo()
    results_repo = FakeSurveyResultsRepo(survey_repo)
    service = SurveyResultsService(db=None, results_repository=results_repo, survey_repository=survey_repo)
    a = make_anketa(survey_repo, status="CLOSED")
    sec = add_sekcija(survey_repo, a.id)
    add_pitanje(survey_repo, sec.id, "RATING_1_10", redosled=1)
    add_pitanje(survey_repo, sec.id, "TEXT", redosled=2)

    pitanja = service.get_statistics(a.id)["pitanja"]
    assert pitanja[0]["komponenta"] == "SCALE" and len(pitanja[0]["raspodela"]) == 10
    assert pitanja[1]["komponenta"] == "TEXT"


# ======================================================================== HTTP
VALID_KEY = "s" * 40


class _PortalRepo:
    def __init__(self, role):
        self._user = make_korisnik(id=1, platni_broj="admin1")
        self._role = role

    def get_by_platni_broj(self, pb):
        return self._user if pb == "admin1" else None

    def get_active_role_codes(self, kid):
        return [self._role]


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _portal(monkeypatch, role):
    monkeypatch.setattr(portal_auth, "KorisnikRepository", lambda db: db)
    app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None, portal_service_key=VALID_KEY)
    app.dependency_overrides[get_db] = lambda: _PortalRepo(role)


HEADERS = {"X-Service-Key": VALID_KEY, "X-Acting-Platni-Broj": "admin1"}


def test_question_types_endpoint_lists_active_types(client, monkeypatch, db_types):
    _portal(monkeypatch, "HR")
    resp = client.get("/api/v1/admin/survey-question-types", headers=HEADERS)
    assert resp.status_code == 200
    items = {i["sifra"]: i for i in resp.json()["items"]}
    assert items["RATING_1_4"] == {
        "sifra": "RATING_1_4",
        "naziv": "Ocena 1-4",
        "komponenta": "SCALE",
        "min_vrednost": 1,
        "max_vrednost": 4,
    }
    assert items["TEXT"]["min_vrednost"] is None
    assert "RATING_0_3" not in items  # povucen tip se ne nudi


def test_question_types_endpoint_requires_service_key(client):
    assert client.get("/api/v1/admin/survey-question-types").status_code == 401


def test_question_types_endpoint_forbidden_for_employee_role(client, monkeypatch):
    _portal(monkeypatch, "ZAPOSLENI")
    assert client.get("/api/v1/admin/survey-question-types", headers=HEADERS).status_code == 403


def test_openapi_exposes_route_and_additive_question_fields():
    schema = app.openapi()
    assert "/api/v1/admin/survey-question-types" in schema["paths"]
    for model in ("PitanjeOut", "AdminPitanjeOut"):
        props = schema["components"]["schemas"][model]["properties"]
        assert {"tip", "komponenta", "min_vrednost", "max_vrednost"} <= set(props)
        # Nova polja su opciona: stariji klijenti i dalje dobijaju `tip` kao i do sada.
        required = set(schema["components"]["schemas"][model].get("required", []))
        assert "tip" in required and "komponenta" not in required
