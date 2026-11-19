"""Faza 0 (Osnova): ukljucivanje modula, ciljanje, pocetni ekran, konfiguracija,
upiti za Oracle i SQL skripta 010."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.dialects import oracle

from app.api.v1 import home as home_mod
from app.core.configuration_definitions import CONFIGURATION_DEFINITIONS
from app.core.exceptions import ValidationBusinessError
from app.core.modules import MODULE_CODES, normalize_mode, parse_code_list
from app.dependencies.auth import (
    AuthContext,
    get_current_context,
    get_current_ready_user,
)
from app.main import app
from app.models.obavestenje import AKCIJA_TIPOVI, AKCIJE_NOVIH_MODULA
from app.models.sistemski_dogadjaj import DOGADJAJ_TIPOVI, DOGADJAJ_TIPOVI_NOVIH_MODULA
from app.repositories.image_repository import ImageRepository
from app.repositories.module_access_repository import ModuleAccessRepository
from app.services.home_summary_service import HomeSummaryService
from app.services.module_access_service import ModuleAccessService
from app.services.targeting import Cilj, KorisnikZaCiljanje, matches, matches_any
from tests.fakes import make_korisnik

SQL_010 = Path(__file__).resolve().parents[1] / "sql" / "010_osnova_module.sql"


# ============================================================ konfiguracija
def test_module_keys_are_in_configuration_allowlist():
    for key in ("MODUL_POGODNOSTI", "MODUL_PITAJ_HR", "MODUL_KVIZ", "MODUL_IGRA", "MODUL_ZAHVALNICE"):
        d = CONFIGURATION_DEFINITIONS[key]
        assert d.default == "ISKLJUCEN" and d.tip_podatka == "TEKST" and not d.nullable
        assert d.validate(" pilot ") == "PILOT"
        with pytest.raises(ValidationBusinessError):
            d.validate("UKLJUCEN")
    for key in ("MODUL_PILOT_ORGJED", "MODUL_PILOT_PLATNI_BROJ"):
        assert CONFIGURATION_DEFINITIONS[key].nullable


@pytest.mark.parametrize("raw,expected", [("318", "318"), (" 318 , 401,318,, ", "318,401"), ("A-1,b_2", "A-1,b_2")])
def test_code_list_is_normalized(raw, expected):
    assert CONFIGURATION_DEFINITIONS["MODUL_PILOT_ORGJED"].validate(raw) == expected


@pytest.mark.parametrize("raw", [" , ", "318;401", "x" * 51, ",".join(str(i) for i in range(101)), "1" * 4001])
def test_code_list_rejects_bad_values(raw):
    with pytest.raises(ValidationBusinessError):
        CONFIGURATION_DEFINITIONS["MODUL_PILOT_PLATNI_BROJ"].validate(raw)


def test_normalize_mode_and_parse_code_list():
    assert normalize_mode(None) == "ISKLJUCEN"
    assert normalize_mode("nesto") == "ISKLJUCEN"
    assert normalize_mode(" svi ") == "SVI"
    assert parse_code_list(None) == frozenset()
    assert parse_code_list("318, 401,") == {"318", "401"}


# =================================================================== ciljanje
def test_targeting_rules():
    k = KorisnikZaCiljanje(platni_broj="123", orgjed_sifre=frozenset({"318"}))
    assert matches(Cilj("SVI"), k)
    assert matches(Cilj("orgjed", " 318 "), k)
    assert not matches(Cilj("ORGJED", "401"), k)
    assert not matches(Cilj("ORGJED", None), k)
    assert matches(Cilj("PLATNI_BROJ", "123"), k)
    assert not matches(Cilj("PLATNI_BROJ", "1234"), k)
    # Nepodrzani i nepoznati ciljevi nikad ne pogadjaju (isto kao ankete/obavestenja).
    for tip in ("CENTRALA", "MALOPRODAJA", "NESTO"):
        assert not matches(Cilj(tip), k)
    assert not matches_any([], k)
    assert matches_any([Cilj("ORGJED", "1"), Cilj("PLATNI_BROJ", "123")], k)


# =========================================================== ukljucivanje
class FakeConfigRepo:
    def __init__(self, values):
        self.values = values
        self.calls = 0

    def get_values(self, keys):
        self.calls += 1
        return {k: v for k, v in self.values.items() if k in keys}


class FakeAccessRepo:
    def __init__(self, orgjed=()):
        self.orgjed = frozenset(orgjed)
        self.calls = 0

    def active_orgjed_codes(self, korisnik_id):
        self.calls += 1
        return self.orgjed


def _service(values, orgjed=()):
    access = FakeAccessRepo(orgjed)
    config = FakeConfigRepo(values)
    return ModuleAccessService(config, access), config, access


def test_all_modules_off_by_default_without_orgjed_query():
    service, config, access = _service({})
    result = service.enabled_modules(make_korisnik())
    assert list(result) == list(MODULE_CODES)
    assert not any(result.values())
    assert config.calls == 1 and access.calls == 0


def test_svi_and_pilot_by_orgjed():
    values = {"MODUL_POGODNOSTI": "SVI", "MODUL_KVIZ": "PILOT", "MODUL_IGRA": "PILOT", "MODUL_PILOT_ORGJED": "318"}
    service, _, access = _service(values, orgjed={"318", "500"})
    result = service.enabled_modules(make_korisnik(id=7))
    assert result == {"POGODNOSTI": True, "PITAJ_HR": False, "KVIZ": True, "IGRA": True, "ZAHVALNICE": False}
    assert access.calls == 1  # pilot se racuna jednom za sve module

    service, *_ = _service(values, orgjed={"401"})
    assert service.enabled_modules(make_korisnik())["KVIZ"] is False


def test_pilot_by_platni_broj_skips_orgjed_query():
    values = {"MODUL_ZAHVALNICE": "pilot", "MODUL_PILOT_ORGJED": "318", "MODUL_PILOT_PLATNI_BROJ": "999,12345"}
    service, _, access = _service(values)
    assert service.is_enabled(make_korisnik(platni_broj="12345"), "ZAHVALNICE") is True
    assert access.calls == 0


def test_pilot_without_pilot_lists_is_off_and_unknown_module_is_off():
    service, _, access = _service({"MODUL_PITAJ_HR": "PILOT"})
    assert service.is_enabled(make_korisnik(), "PITAJ_HR") is False
    assert service.is_enabled(make_korisnik(), "NEPOSTOJECI") is False
    assert access.calls == 0


# ======================================================== pocetni ekran
@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_home_summary_requires_ready_user(client):
    assert client.get("/api/v1/home/summary").status_code == 401
    korisnik = make_korisnik(obavezna_promena_lozinke="N", telefon_potvrdjen="N")
    app.dependency_overrides[get_current_context] = lambda: AuthContext(korisnik=korisnik, sesija=None)
    resp = client.get("/api/v1/home/summary")
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "PHONE_CONFIRMATION_REQUIRED"


def test_home_summary_lists_all_modules_in_order(client):
    service, *_ = _service({"MODUL_POGODNOSTI": "SVI"})
    app.dependency_overrides[home_mod.get_home_summary_service] = lambda: HomeSummaryService(service)
    app.dependency_overrides[get_current_ready_user] = lambda: make_korisnik(
        obavezna_promena_lozinke="N", telefon_potvrdjen="D"
    )
    resp = client.get("/api/v1/home/summary")
    assert resp.status_code == 200
    moduli = resp.json()["moduli"]
    assert [m["kod"] for m in moduli] == list(MODULE_CODES)
    assert moduli[0] == {"kod": "POGODNOSTI", "naziv": "Moje pogodnosti", "aktivan": True, "broj_novih": 0}
    assert all(m["aktivan"] is False for m in moduli[1:])


# ======================================================= rezervisane vrednosti
def test_new_action_and_event_types_are_reserved_not_yet_usable():
    assert set(AKCIJE_NOVIH_MODULA) == {"BENEFIT", "HR_QUESTION", "QUIZ", "KUDOS", "GAME"}
    assert not set(AKCIJE_NOVIH_MODULA) & set(AKCIJA_TIPOVI)
    assert not set(DOGADJAJ_TIPOVI_NOVIH_MODULA) & set(DOGADJAJ_TIPOVI)


# ================================================================ Oracle upiti
class _Result:
    def all(self):
        return []

    def first(self):
        return None

    def scalar_one(self):
        return 0

    def scalar_one_or_none(self):
        return None

    def scalars(self):
        return self


class _CompileDb:
    def __init__(self):
        self.sql: list[str] = []

    def execute(self, stmt):
        self.sql.append(str(stmt.compile(dialect=oracle.dialect())).upper())
        return _Result()


def test_module_access_query_reads_only_puls_tables():
    db = _CompileDb()
    assert ModuleAccessRepository(db).active_orgjed_codes(5) == frozenset()
    sql = db.sql[0]
    assert "PULS_KORISNIK_RASPOREDI" in sql and "AKTIVAN" in sql
    assert "HR." not in sql and "IIS." not in sql


def test_image_queries_never_select_blob_outside_content():
    db = _CompileDb()
    repo = ImageRepository(db)
    repo.list_admin(None, "logo", 1, 20)
    repo.get_admin(1)
    repo.get_active_etag(1)
    for sql in db.sql:
        assert "SADRZAJ" not in sql and "SELECT *" not in sql
    db.sql.clear()
    repo.get_active_content(1)
    assert "SADRZAJ" in db.sql[0] and "STATUS" in db.sql[0]


# ================================================================ SQL skripta
def test_sql_010_is_additive_and_complete():
    sql = SQL_010.read_text(encoding="utf-8")
    # Komentari (--) se ne proveravaju - u zaglavlju se namerno nabraja sta skripta NE sadrzi.
    code = "\n".join(line.split("--", 1)[0] for line in sql.splitlines())
    upper = code.upper()
    for forbidden in ("DROP TABLE", "DELETE FROM", "TRUNCATE", "HR.UGOVOR", "IIS."):
        assert forbidden not in upper
    assert "CREATE TABLE PULS_SLIKE" in sql
    # Stari tipovi ostaju, novi su dodati.
    for value in ("'NONE'", "'SURVEY'", "'IDEA'", "'URL'", "'IDEA_CYCLE'", *[f"'{a}'" for a in AKCIJE_NOVIH_MODULA]):
        assert value in sql
    for value in (*DOGADJAJ_TIPOVI, *DOGADJAJ_TIPOVI_NOVIH_MODULA):
        assert f"'{value}'" in sql
    for key in ("MODUL_POGODNOSTI", "MODUL_PITAJ_HR", "MODUL_KVIZ", "MODUL_IGRA", "MODUL_ZAHVALNICE",
                "MODUL_PILOT_ORGJED", "MODUL_PILOT_PLATNI_BROJ"):
        assert f"'{key}'" in sql
    assert "'318'" in sql
    assert upper.rstrip().endswith("COMMIT;")
