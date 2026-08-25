"""HTTP-level testovi za GET /api/v1/auth/me: novi orgjed_naziv/radno_mesto_naziv
u 'raspored'. KorisnikRepository se monkeypatch-uje (kao u test_portal_auth.py) da
/auth/me ne zahteva pravu Oracle konekciju."""

import pytest
from fastapi.testclient import TestClient

from app.api.v1 import auth as auth_module
from app.dependencies.auth import AuthContext, get_current_context
from app.main import app
from app.repositories.korisnik_repository import RasporedWithNames
from tests.fakes import make_korisnik


class FakeMeRepo:
    def __init__(self, raspored: RasporedWithNames | None, uloge: list[str] | None = None):
        self._raspored = raspored
        self._uloge = uloge or ["ZAPOSLENI"]

    def get_active_role_codes(self, korisnik_id):
        return self._uloge

    def get_primary_active_raspored_with_names(self, korisnik_id):
        return self._raspored


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _login_as(client, korisnik, repo):
    app.dependency_overrides[get_current_context] = lambda: AuthContext(
        korisnik=korisnik, sesija=None
    )
    auth_module.KorisnikRepository = lambda db: repo


def _me(client):
    return client.get("/api/v1/auth/me", headers={"Authorization": "Bearer irrelevant"})


@pytest.fixture(autouse=True)
def _restore_repository_class(monkeypatch):
    original = auth_module.KorisnikRepository
    yield
    auth_module.KorisnikRepository = original


def test_raspored_with_both_names_found(client):
    korisnik = make_korisnik(obavezna_promena_lozinke="N", telefon_potvrdjen="D")
    raspored = RasporedWithNames(
        orgjed_sifra="5011",
        orgjed_naziv="IT SEKTOR",
        radno_mesto_sifra="1015",
        radno_mesto_naziv="FULL-STACK DEVELOPER / AI ENGINEER",
    )
    _login_as(client, korisnik, FakeMeRepo(raspored))

    resp = _me(client)

    assert resp.status_code == 200
    body = resp.json()
    assert body["raspored"] == {
        "orgjed_sifra": "5011",
        "orgjed_naziv": "IT SEKTOR",
        "radno_mesto_sifra": "1015",
        "radno_mesto_naziv": "FULL-STACK DEVELOPER / AI ENGINEER",
    }


def test_orgjed_found_radno_mesto_not_found(client):
    korisnik = make_korisnik(obavezna_promena_lozinke="N", telefon_potvrdjen="D")
    raspored = RasporedWithNames(
        orgjed_sifra="5011",
        orgjed_naziv="IT SEKTOR",
        radno_mesto_sifra="9999",
        radno_mesto_naziv=None,
    )
    _login_as(client, korisnik, FakeMeRepo(raspored))

    body = _me(client).json()

    assert body["raspored"]["orgjed_naziv"] == "IT SEKTOR"
    assert body["raspored"]["radno_mesto_sifra"] == "9999"
    assert body["raspored"]["radno_mesto_naziv"] is None


def test_radno_mesto_sifra_is_null(client):
    korisnik = make_korisnik(obavezna_promena_lozinke="N", telefon_potvrdjen="D")
    raspored = RasporedWithNames(
        orgjed_sifra="5011",
        orgjed_naziv="IT SEKTOR",
        radno_mesto_sifra=None,
        radno_mesto_naziv=None,
    )
    _login_as(client, korisnik, FakeMeRepo(raspored))

    body = _me(client).json()

    assert body["raspored"]["radno_mesto_sifra"] is None
    assert body["raspored"]["radno_mesto_naziv"] is None


def test_neither_sifrarnik_has_matching_row(client):
    korisnik = make_korisnik(obavezna_promena_lozinke="N", telefon_potvrdjen="D")
    raspored = RasporedWithNames(
        orgjed_sifra="0000",
        orgjed_naziv=None,
        radno_mesto_sifra="0000",
        radno_mesto_naziv=None,
    )
    _login_as(client, korisnik, FakeMeRepo(raspored))

    body = _me(client).json()

    assert body["raspored"]["orgjed_sifra"] == "0000"
    assert body["raspored"]["orgjed_naziv"] is None
    assert body["raspored"]["radno_mesto_sifra"] == "0000"
    assert body["raspored"]["radno_mesto_naziv"] is None


def test_no_active_raspored_returns_null(client):
    korisnik = make_korisnik(obavezna_promena_lozinke="N", telefon_potvrdjen="D")
    _login_as(client, korisnik, FakeMeRepo(None))

    body = _me(client).json()

    assert body["raspored"] is None


def test_full_response_shape(client):
    korisnik = make_korisnik(
        id=1,
        platni_broj="12345",
        ime="Boro",
        prezime="Radojcic",
        broj_telefona="060000000",
        status_zaposlenja="AKTIVAN",
        status_naloga="OMOGUCEN",
        obavezna_promena_lozinke="N",
        telefon_potvrdjen="D",
    )
    raspored = RasporedWithNames(
        orgjed_sifra="5011",
        orgjed_naziv="IT SEKTOR",
        radno_mesto_sifra="1015",
        radno_mesto_naziv="FULL-STACK DEVELOPER / AI ENGINEER",
    )
    _login_as(client, korisnik, FakeMeRepo(raspored, uloge=["ZAPOSLENI"]))

    resp = _me(client)

    assert resp.status_code == 200
    assert resp.json() == {
        "id": 1,
        "platni_broj": "12345",
        "ime": "Boro",
        "prezime": "Radojcic",
        "broj_telefona": "060000000",
        "status_zaposlenja": "AKTIVAN",
        "status_naloga": "OMOGUCEN",
        "obavezna_promena_lozinke": False,
        "telefon_potvrdjen": True,
        "uloge": ["ZAPOSLENI"],
        "raspored": {
            "orgjed_sifra": "5011",
            "orgjed_naziv": "IT SEKTOR",
            "radno_mesto_sifra": "1015",
            "radno_mesto_naziv": "FULL-STACK DEVELOPER / AI ENGINEER",
        },
    }
