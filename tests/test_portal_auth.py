"""Testovi trusted-service + acting-on-behalf-of autentikacije ADMIN ruta.

Ne koriste pravu Oracle bazu: KorisnikRepository se monkeypatch-uje fake objektom,
a na HTTP nivou get_settings/get_db se override-uju preko dependency_overrides.
"""

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.exceptions import ForbiddenError, InvalidServiceCredentialsError
from app.db.session import get_db
from app.dependencies import portal_auth
from app.dependencies.portal_auth import require_portal_admin, require_portal_admin_or_hr
from app.core.config import get_settings
from app.main import app
from app.api.v1 import admin_ideas as admin_ideas_module
from app.api.v1 import admin_surveys as admin_surveys_module
from tests.fakes import make_korisnik

VALID_KEY = "s" * 40


def _settings(key: str = VALID_KEY) -> Settings:
    return Settings(_env_file=None, portal_service_key=key)


class FakePortalRepo:
    """Stoji na mestu KorisnikRepository(db): drži korisnike po platnom broju i uloge."""

    def __init__(self, users=None, roles=None):
        self._users = {u.platni_broj: u for u in (users or [])}
        self._roles = roles or {}

    def get_by_platni_broj(self, platni_broj):
        return self._users.get(platni_broj)

    def get_active_role_codes(self, korisnik_id):
        return self._roles.get(korisnik_id, [])


@pytest.fixture(autouse=True)
def _patch_repo(monkeypatch):
    # KorisnikRepository(db) -> vraća sam db (koji je već FakePortalRepo).
    monkeypatch.setattr(portal_auth, "KorisnikRepository", lambda db: db)


def _call(service_key, acting, repo, key=VALID_KEY):
    return require_portal_admin_or_hr(
        service_key=service_key,
        x_acting_platni_broj=acting,
        settings=_settings(key),
        db=repo,
    )


# --------------------------------------------------------------- servisni ključ (401)
def test_missing_service_key_returns_401():
    with pytest.raises(InvalidServiceCredentialsError):
        _call(None, "admin1", FakePortalRepo())


def test_wrong_service_key_returns_401():
    with pytest.raises(InvalidServiceCredentialsError):
        _call("pogresan", "admin1", FakePortalRepo())


def test_service_key_not_configured_returns_401_not_500():
    # Ključ nije konfigurisan (prazno) -> odbij, nikad 500, čak i ako je poslat neki ključ.
    with pytest.raises(InvalidServiceCredentialsError):
        _call("bilo-sta", "admin1", FakePortalRepo(), key="")


def test_non_ascii_service_key_does_not_raise_500():
    # Malformed/non-ASCII ključ mora dati čist 401, bez unhandled izuzetka.
    with pytest.raises(InvalidServiceCredentialsError):
        _call("ključ-šđčćž", "admin1", FakePortalRepo())


def test_service_key_must_match_exactly_no_trim():
    with pytest.raises(InvalidServiceCredentialsError):
        _call(VALID_KEY + " ", "admin1", FakePortalRepo())


# ------------------------------------------------------ acting identitet / autorizacija (403)
def _admin(pb="admin1", **ov):
    return make_korisnik(id=1, platni_broj=pb, **ov)


def test_valid_key_missing_acting_header_returns_403():
    with pytest.raises(ForbiddenError):
        _call(VALID_KEY, None, FakePortalRepo())


@pytest.mark.parametrize("acting", ["", "   ", "a" * 31, "12\x0034"])
def test_invalid_acting_platni_broj_returns_403(acting):
    with pytest.raises(ForbiddenError):
        _call(VALID_KEY, acting, FakePortalRepo())


def test_user_not_found_returns_403():
    with pytest.raises(ForbiddenError):
        _call(VALID_KEY, "nepostojeci", FakePortalRepo())


def test_inactive_employee_returns_403():
    u = _admin(status_zaposlenja="NEAKTIVAN")
    repo = FakePortalRepo([u], {1: ["ADMIN"]})
    with pytest.raises(ForbiddenError):
        _call(VALID_KEY, "admin1", repo)


def test_disabled_account_returns_403():
    u = _admin(status_naloga="ONEMOGUCEN")
    repo = FakePortalRepo([u], {1: ["ADMIN"]})
    with pytest.raises(ForbiddenError):
        _call(VALID_KEY, "admin1", repo)


def test_locked_user_returns_403():
    u = _admin(zakljucan="D")
    repo = FakePortalRepo([u], {1: ["ADMIN"]})
    with pytest.raises(ForbiddenError):
        _call(VALID_KEY, "admin1", repo)


def test_active_user_without_admin_or_hr_role_returns_403():
    u = _admin()
    repo = FakePortalRepo([u], {1: ["ZAPOSLENI"]})
    with pytest.raises(ForbiddenError):
        _call(VALID_KEY, "admin1", repo)


def test_inactive_admin_role_returns_403():
    # Uloga se čita iz baze; neaktivna uloga se ne vraća u get_active_role_codes -> prazno.
    u = _admin()
    repo = FakePortalRepo([u], {1: []})
    with pytest.raises(ForbiddenError):
        _call(VALID_KEY, "admin1", repo)


# --------------------------------------------------------------------- happy path
def test_valid_admin_allows_access_and_returns_korisnik():
    u = _admin()
    repo = FakePortalRepo([u], {1: ["ADMIN"]})
    result = _call(VALID_KEY, "admin1", repo)
    assert result is u


def test_valid_hr_allows_access():
    u = _admin(pb="hr1")
    repo = FakePortalRepo([u], {1: ["HR"]})
    assert _call(VALID_KEY, "hr1", repo) is u


def test_acting_platni_broj_is_trimmed():
    u = _admin()
    repo = FakePortalRepo([u], {1: ["ADMIN"]})
    assert _call(VALID_KEY, "  admin1  ", repo) is u


def test_no_bearer_needed_first_login_flags_ignored():
    # Portal acting korisnik ne mora imati završen prvi login (promena lozinke / telefon).
    u = _admin(obavezna_promena_lozinke="D", telefon_potvrdjen="N", lozinka_hash=None)
    repo = FakePortalRepo([u], {1: ["ADMIN"]})
    assert _call(VALID_KEY, "admin1", repo) is u


# ---------------------------------------------------------- require_portal_admin
def test_require_portal_admin_allows_admin_role():
    u = _admin()
    repo = FakePortalRepo([u], {1: ["ADMIN"]})
    assert require_portal_admin(korisnik=u, db=repo) is u


def test_require_portal_admin_rejects_hr_only():
    u = _admin()
    repo = FakePortalRepo([u], {1: ["HR"]})
    with pytest.raises(ForbiddenError):
        require_portal_admin(korisnik=u, db=repo)


def test_require_portal_admin_rejects_zaposleni():
    u = _admin()
    repo = FakePortalRepo([u], {1: ["ZAPOSLENI"]})
    with pytest.raises(ForbiddenError):
        require_portal_admin(korisnik=u, db=repo)


# ---------------------------------------------------------------- ključ se ne curi
def test_service_key_not_in_exception_message():
    try:
        _call("tajni-kljuc-12345", "admin1", FakePortalRepo())
    except InvalidServiceCredentialsError as exc:
        assert "tajni-kljuc-12345" not in str(exc)
        assert "tajni-kljuc-12345" not in repr(exc)


# =====================================================================
# HTTP nivo: prava dependency preko TestClient-a
# =====================================================================
@pytest.fixture
def http(monkeypatch):
    def _apply(repo, key=VALID_KEY):
        app.dependency_overrides[get_settings] = lambda: _settings(key)
        app.dependency_overrides[get_db] = lambda: repo
        return TestClient(app)

    yield _apply
    app.dependency_overrides.clear()


def _admin_repo():
    return FakePortalRepo([_admin()], {1: ["ADMIN"]})


def test_http_no_headers_returns_401(http):
    client = http(_admin_repo())
    resp = client.get("/api/v1/admin/idea-cycles")
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "INVALID_SERVICE_CREDENTIALS"


def test_http_wrong_key_same_401(http):
    client = http(_admin_repo())
    resp = client.get("/api/v1/admin/idea-cycles", headers={"X-Service-Key": "wrong-key-123"})
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "INVALID_SERVICE_CREDENTIALS"
    assert "wrong-key-123" not in resp.text


def test_http_valid_key_no_acting_returns_403(http):
    client = http(_admin_repo())
    resp = client.get("/api/v1/admin/idea-cycles", headers={"X-Service-Key": VALID_KEY})
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "FORBIDDEN"


def test_http_bearer_without_portal_headers_blocked(http):
    # Bearer token bez portal zaglavlja NE otvara admin rutu (nema fallback-a).
    client = http(_admin_repo())
    resp = client.get(
        "/api/v1/admin/idea-cycles", headers={"Authorization": "Bearer nekitoken"}
    )
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "INVALID_SERVICE_CREDENTIALS"


def test_http_admin_ideas_route_with_portal_headers_ok(http, monkeypatch):
    client = http(_admin_repo())

    class _Stub:
        def list_cycles(self):
            return []

    app.dependency_overrides[admin_ideas_module.get_idea_admin_service] = lambda: _Stub()
    resp = client.get(
        "/api/v1/admin/idea-cycles",
        headers={"X-Service-Key": VALID_KEY, "X-Acting-Platni-Broj": "admin1"},
    )
    assert resp.status_code == 200
    assert resp.json()["items"] == []


def test_http_admin_surveys_route_with_portal_headers_ok(http):
    client = http(_admin_repo())

    class _Stub:
        def list_types(self):
            return []

    app.dependency_overrides[admin_surveys_module.get_survey_admin_service] = lambda: _Stub()
    resp = client.get(
        "/api/v1/admin/survey-types",
        headers={"X-Service-Key": VALID_KEY, "X-Acting-Platni-Broj": "admin1"},
    )
    assert resp.status_code == 200


def test_employee_route_ignores_portal_headers(http):
    # Employee rute i dalje traže Bearer sesiju; portal zaglavlja im ništa ne znače.
    client = http(_admin_repo())
    resp = client.get(
        "/api/v1/surveys",
        headers={"X-Service-Key": VALID_KEY, "X-Acting-Platni-Broj": "admin1"},
    )
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "INVALID_SESSION"


# ------------------------------------------------------------------- OpenAPI (Swagger)
def test_openapi_exposes_service_key_scheme_and_acting_header():
    schema = app.openapi()
    schemes = schema["components"]["securitySchemes"]
    # X-Service-Key kao API key security scheme (header).
    assert any(
        s.get("in") == "header" and s.get("name") == "X-Service-Key"
        for s in schemes.values()
    )
    # X-Acting-Platni-Broj kao header parametar na admin ruti.
    params = schema["paths"]["/api/v1/admin/idea-cycles"]["get"].get("parameters", [])
    assert any(p["name"] == "X-Acting-Platni-Broj" and p["in"] == "header" for p in params)
