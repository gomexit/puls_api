"""HTTP-level provera modula ONBOARDING DOKUMENTI: employee (Bearer) i admin (OBO) rute,
multipart upload, binarni PDF response, statusi, greske i OpenAPI."""

import hashlib

import pytest
from fastapi.testclient import TestClient

from app.api.v1 import admin_onboarding_documents as admin_mod
from app.api.v1 import onboarding_documents as employee_mod
from app.core.config import Settings, get_settings
from app.core.exceptions import InvalidSessionError
from app.db.session import get_db
from app.dependencies import auth as auth_deps
from app.dependencies import portal_auth
from app.dependencies.auth import AuthContext, get_current_context, get_current_ready_user
from app.main import app
from app.services.onboarding_document_service import OnboardingDocumentService
from tests.fakes import FakeAuditService, make_korisnik
from tests.onboarding_document_fakes import (
    FIXED_NOW,
    FakeOnbDb,
    FakeOnboardingDocumentRepo,
    make_dokument,
    make_pdf_bytes,
)

VALID_KEY = "s" * 40
BASE = "/api/v1/onboarding/documents"
ADMIN = "/api/v1/admin/onboarding-documents"
NOT_FOUND = {
    "error": {
        "code": "ONBOARDING_DOCUMENT_NOT_FOUND",
        "message": "Dokument nije pronađen ili više nije dostupan.",
    }
}


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


class Env:
    """Deljeni fake repo/audit/db po testu; servis se gradi po zahtevu nad istim stanjem."""

    def __init__(self, max_mb: int = 20):
        self.db = FakeOnbDb()
        self.repo = FakeOnboardingDocumentRepo(self.db)
        self.audit = FakeAuditService()
        self.settings = Settings(_env_file=None, onboarding_pdf_max_size_mb=max_mb)

    def service(self) -> OnboardingDocumentService:
        return OnboardingDocumentService(
            db=self.db,
            repository=self.repo,
            audit_service=self.audit,
            settings=self.settings,
            now_fn=lambda: FIXED_NOW,
        )


def _wire_services(env: Env) -> None:
    app.dependency_overrides[employee_mod.get_onboarding_document_service] = env.service
    app.dependency_overrides[admin_mod.get_onboarding_document_service] = env.service


class FakePortalRepo:
    def __init__(self, users=None, roles=None):
        self._users = {u.platni_broj: u for u in (users or [])}
        self._roles = roles or {}

    def get_by_platni_broj(self, pb):
        return self._users.get(pb)

    def get_active_role_codes(self, kid):
        return self._roles.get(kid, [])


def _use_portal(monkeypatch, roles=("ADMIN",), pb="admin1"):
    repo = FakePortalRepo([make_korisnik(id=1, platni_broj=pb)], {1: list(roles)})
    monkeypatch.setattr(portal_auth, "KorisnikRepository", lambda db: db)
    app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None, portal_service_key=VALID_KEY)
    app.dependency_overrides[get_db] = lambda: repo


def _h(acting="admin1"):
    return {"X-Service-Key": VALID_KEY, "X-Acting-Platni-Broj": acting}


def _as_employee():
    app.dependency_overrides[get_current_ready_user] = lambda: make_korisnik(
        obavezna_promena_lozinke="N", telefon_potvrdjen="D"
    )


def _upload(pdf=None, name="pravilnik.pdf", ctype="application/pdf"):
    return {"file": (name, pdf if pdf is not None else make_pdf_bytes(), ctype)}


# ============================================================ EMPLOYEE
def test_employee_requires_bearer(client):
    resp = client.get(BASE)
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "INVALID_SESSION"


def test_employee_revoked_session_rejected(client):
    class RevokedAuth:
        def authenticate_token(self, token):
            raise InvalidSessionError()

    app.dependency_overrides[auth_deps.get_auth_service] = lambda: RevokedAuth()
    resp = client.get(f"{BASE}/1/content", headers={"Authorization": "Bearer ponisten"})
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "INVALID_SESSION"


def test_employee_first_login_flow_blocks_documents(client):
    korisnik = make_korisnik(obavezna_promena_lozinke="D", telefon_potvrdjen="D")
    app.dependency_overrides[get_current_context] = lambda: AuthContext(korisnik=korisnik, sesija=None)
    resp = client.get(BASE)
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "PASSWORD_CHANGE_REQUIRED"


def test_employee_list_only_published_sorted_without_blob_or_hash(client):
    env = Env()
    for dok in (
        make_dokument(id=10, status="DRAFT", redosled=1),
        make_dokument(id=11, status="PUBLISHED", redosled=3, naziv="Treci"),
        make_dokument(id=12, status="PUBLISHED", redosled=1, naziv="Prvi"),
        make_dokument(id=13, status="ARCHIVED", redosled=1),
        make_dokument(id=14, status="PUBLISHED", redosled=3, naziv="Treci-b"),
    ):
        env.repo.seed(dok)
    _wire_services(env)
    _as_employee()

    resp = client.get(BASE)
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert [i["id"] for i in items] == [12, 11, 14]
    for item in items:
        assert set(item) == {
            "id", "naziv", "opis", "originalni_naziv_fajla",
            "velicina_bajtova", "redosled", "verzija", "datum_objave",
        }
    assert "sadrzaj" not in resp.text and "sha256" not in resp.text


def test_employee_detail(client):
    env = Env()
    dok = env.repo.seed(make_dokument(id=1, status="PUBLISHED", naziv="Pravilnik", opis="Opis"))
    _wire_services(env)
    _as_employee()

    body = client.get(f"{BASE}/1").json()
    assert body["id"] == 1 and body["naziv"] == "Pravilnik" and body["opis"] == "Opis"
    assert body["velicina_bajtova"] == dok.velicina_bajtova and body["verzija"] == 1
    assert body["datum_objave"] is not None
    assert "sha256" not in body and "sadrzaj" not in body


def test_employee_content_headers_and_body(client):
    env = Env()
    dok = env.repo.seed(
        make_dokument(id=1, status="PUBLISHED", originalni_naziv_fajla="Uputstvo šđ.pdf")
    )
    _wire_services(env)
    _as_employee()

    resp = client.get(f"{BASE}/1/content")
    assert resp.status_code == 200
    assert resp.content == dok.sadrzaj
    assert resp.headers["content-type"] == "application/pdf"
    assert resp.headers["content-length"] == str(len(dok.sadrzaj))
    assert resp.headers["etag"] == f'"{dok.sha256}"'
    assert resp.headers["cache-control"] == "private, no-store"
    assert resp.headers["x-content-type-options"] == "nosniff"
    disposition = resp.headers["content-disposition"]
    assert disposition.startswith("inline; filename=")
    assert "filename*=UTF-8''Uputstvo%20%C5%A1%C4%91.pdf" in disposition


def test_employee_draft_archived_and_missing_return_identical_404(client):
    env = Env()
    env.repo.seed(make_dokument(id=1, status="DRAFT"))
    env.repo.seed(make_dokument(id=2, status="ARCHIVED"))
    _wire_services(env)
    _as_employee()

    for doc_id in (1, 2, 999):
        for suffix in ("", "/content"):
            resp = client.get(f"{BASE}/{doc_id}{suffix}")
            assert resp.status_code == 404
            assert resp.json() == NOT_FOUND


def test_employee_invalid_id_is_validation_error(client):
    _wire_services(Env())
    _as_employee()
    resp = client.get(f"{BASE}/abc")
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"


# ================================================================= ADMIN auth
def test_admin_no_service_key_401(client, monkeypatch):
    _use_portal(monkeypatch)
    resp = client.get(ADMIN)
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "INVALID_SERVICE_CREDENTIALS"


def test_admin_wrong_service_key_401(client, monkeypatch):
    _use_portal(monkeypatch)
    resp = client.get(ADMIN, headers={"X-Service-Key": "pogresan", "X-Acting-Platni-Broj": "admin1"})
    assert resp.status_code == 401


def test_admin_missing_or_unknown_actor_403(client, monkeypatch):
    _use_portal(monkeypatch)
    _wire_services(Env())
    assert client.get(ADMIN, headers={"X-Service-Key": VALID_KEY}).status_code == 403
    assert client.get(ADMIN, headers=_h("nepoznat")).status_code == 403


def test_admin_plain_employee_role_forbidden_everywhere(client, monkeypatch):
    _use_portal(monkeypatch, roles=("ZAPOSLENI",))
    env = Env()
    env.repo.seed(make_dokument(id=1))
    _wire_services(env)
    for method, url, kwargs in [
        ("get", ADMIN, {}),
        ("get", f"{ADMIN}/1", {}),
        ("get", f"{ADMIN}/1/content", {}),
        ("post", ADMIN, {"data": {"naziv": "N"}, "files": _upload()}),
        ("put", f"{ADMIN}/1", {"json": {"naziv": "N", "redosled": 1}}),
        ("put", f"{ADMIN}/1/content", {"files": _upload()}),
        ("patch", f"{ADMIN}/1/status", {"json": {"status": "PUBLISHED"}}),
    ]:
        resp = getattr(client, method)(url, headers=_h(), **kwargs)
        assert resp.status_code == 403, (method, url)
    assert env.db.committed == 0


@pytest.mark.parametrize("role", ["ADMIN", "HR"])
def test_admin_and_hr_allowed(client, monkeypatch, role):
    _use_portal(monkeypatch, roles=(role,))
    _wire_services(Env())
    assert client.get(ADMIN, headers=_h()).status_code == 200


def test_bearer_only_does_not_authorize_admin_routes(client, monkeypatch):
    _use_portal(monkeypatch)
    resp = client.get(ADMIN, headers={"Authorization": "Bearer x"})
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "INVALID_SERVICE_CREDENTIALS"


# ============================================================= ADMIN create
def test_admin_create_multipart_draft(client, monkeypatch):
    _use_portal(monkeypatch, pb="hr1")
    env = Env()
    _wire_services(env)
    pdf = make_pdf_bytes()

    resp = client.post(
        ADMIN,
        headers=_h("hr1"),
        data={"naziv": "  Pravilnik  ", "opis": "Opis", "redosled": "4"},
        files=_upload(pdf, name="Pravilnik za nove.pdf"),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["status"] == "DRAFT" and body["verzija"] == 1 and body["datum_objave"] is None
    assert body["naziv"] == "Pravilnik" and body["redosled"] == 4
    assert body["originalni_naziv_fajla"] == "Pravilnik za nove.pdf"
    assert body["mime_tip"] == "application/pdf"
    assert body["velicina_bajtova"] == len(pdf)
    assert body["sha256"] == hashlib.sha256(pdf).hexdigest()
    assert body["kreirao_platni_broj"] == "hr1" and body["izmenio_platni_broj"] == "hr1"
    assert "sadrzaj" not in resp.text
    assert env.db.committed == 1
    assert [e["sifra_akcije"] for e in env.audit.entries] == ["ADMIN_ONBOARDING_DOCUMENT_CREATED"]


def test_admin_create_default_redosled_is_one(client, monkeypatch):
    _use_portal(monkeypatch)
    _wire_services(Env())
    resp = client.post(ADMIN, headers=_h(), data={"naziv": "N"}, files=_upload())
    assert resp.status_code == 201 and resp.json()["redosled"] == 1


def test_admin_create_ignores_spoofed_actor_fields(client, monkeypatch):
    _use_portal(monkeypatch, pb="admin1")
    env = Env()
    _wire_services(env)
    resp = client.post(
        ADMIN,
        headers=_h("admin1"),
        data={"naziv": "N", "kreirao_platni_broj": "lazni", "izmenio_platni_broj": "lazni"},
        files=_upload(),
    )
    assert resp.status_code == 201
    assert resp.json()["kreirao_platni_broj"] == "admin1"
    assert resp.json()["izmenio_platni_broj"] == "admin1"


@pytest.mark.parametrize(
    "kwargs, code, status",
    [
        ({"files": _upload(name="a.txt")}, "INVALID_PDF_DOCUMENT", 422),
        ({"files": _upload(ctype="text/plain")}, "INVALID_PDF_DOCUMENT", 422),
        ({"files": _upload(pdf=b"nije pdf")}, "INVALID_PDF_DOCUMENT", 422),
        ({"files": _upload(pdf=b"")}, "INVALID_PDF_DOCUMENT", 422),
        ({"files": _upload(pdf=make_pdf_bytes(password="x"))}, "INVALID_PDF_DOCUMENT", 422),
        ({"files": _upload(pdf=b"%PDF-" + b"0" * (1024 * 1024 + 1))}, "PDF_DOCUMENT_TOO_LARGE", 413),
    ],
)
def test_admin_create_invalid_file(client, monkeypatch, kwargs, code, status):
    _use_portal(monkeypatch)
    env = Env(max_mb=1)
    _wire_services(env)
    resp = client.post(ADMIN, headers=_h(), data={"naziv": "N"}, **kwargs)
    assert resp.status_code == status
    assert resp.json()["error"]["code"] == code
    assert env.db.committed == 0 and env.repo.added == []


def test_admin_create_missing_file_or_name_is_validation_error(client, monkeypatch):
    _use_portal(monkeypatch)
    _wire_services(Env())
    no_file = client.post(ADMIN, headers=_h(), data={"naziv": "N"})
    no_name = client.post(ADMIN, headers=_h(), files=_upload())
    blank = client.post(ADMIN, headers=_h(), data={"naziv": "   "}, files=_upload())
    bad_order = client.post(ADMIN, headers=_h(), data={"naziv": "N", "redosled": "0"}, files=_upload())
    for resp in (no_file, no_name, blank, bad_order):
        assert resp.status_code == 422
        assert resp.json()["error"]["code"] == "VALIDATION_ERROR"


def test_admin_create_exactly_at_limit_passes_size_check(client, monkeypatch):
    # Tacno 1 MB prolazi proveru velicine (ne 413); nevalidan PDF je tada 422.
    _use_portal(monkeypatch)
    _wire_services(Env(max_mb=1))
    resp = client.post(
        ADMIN, headers=_h(), data={"naziv": "N"}, files=_upload(pdf=b"%PDF-" + b"0" * (1024 * 1024 - 5))
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "INVALID_PDF_DOCUMENT"


@pytest.mark.parametrize(
    "headers, content",
    [
        ({"Content-Type": "multipart/form-data; boundary=xyz"}, b"--xyz\r\nbroken body without end"),
        ({"Content-Type": "multipart/form-data"}, b"nesto"),
        ({"Content-Type": "multipart/form-data; boundary=xyz"}, b""),
        ({"Content-Type": "text/plain"}, b"abc"),
    ],
)
def test_admin_malformed_multipart_is_validation_error_never_500(client, monkeypatch, headers, content):
    _use_portal(monkeypatch)
    env = Env()
    _wire_services(env)
    resp = client.post(ADMIN, headers={**_h(), **headers}, content=content)
    assert resp.status_code == 422
    assert resp.json() == {
        "error": {
            "code": "VALIDATION_ERROR",
            "message": resp.json()["error"]["message"],
        }
    }
    assert env.db.committed == 0 and env.repo.added == []


def test_admin_malformed_multipart_on_content_replace_is_validation_error(client, monkeypatch):
    _use_portal(monkeypatch)
    env = Env()
    env.repo.seed(make_dokument(id=1, status="DRAFT"))
    _wire_services(env)
    resp = client.put(
        f"{ADMIN}/1/content",
        headers={**_h(), "Content-Type": "multipart/form-data; boundary=xyz"},
        content=b"--xyz\r\nbroken body without end",
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"


# ============================================================= ADMIN update
def test_admin_update_metadata(client, monkeypatch):
    _use_portal(monkeypatch, pb="hr2")
    env = Env()
    env.repo.seed(make_dokument(id=1))
    _wire_services(env)
    resp = client.put(
        f"{ADMIN}/1", headers=_h("hr2"), json={"naziv": " Novi ", "opis": None, "redosled": 7}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["naziv"] == "Novi" and body["opis"] is None and body["redosled"] == 7
    assert body["izmenio_platni_broj"] == "hr2" and body["verzija"] == 1
    assert [e["sifra_akcije"] for e in env.audit.entries] == ["ADMIN_ONBOARDING_DOCUMENT_UPDATED"]


def test_admin_update_identical_metadata_creates_no_audit(client, monkeypatch):
    _use_portal(monkeypatch)
    env = Env()
    env.repo.seed(make_dokument(id=1, naziv="Naziv", opis="Opis", redosled=2))
    _wire_services(env)
    resp = client.put(f"{ADMIN}/1", headers=_h(), json={"naziv": "Naziv", "opis": "Opis", "redosled": 2})
    assert resp.status_code == 200 and env.audit.entries == []


@pytest.mark.parametrize(
    "payload",
    [
        {"naziv": "N", "redosled": 1, "izmenio_platni_broj": "lazni"},  # nepoznato polje
        {"naziv": "   ", "redosled": 1},
        {"naziv": "a" * 201, "redosled": 1},
        {"naziv": "N", "opis": "b" * 4001, "redosled": 1},
        {"naziv": "N", "redosled": 0},
        {"naziv": "N"},
    ],
)
def test_admin_update_validation_errors(client, monkeypatch, payload):
    _use_portal(monkeypatch)
    env = Env()
    env.repo.seed(make_dokument(id=1))
    _wire_services(env)
    resp = client.put(f"{ADMIN}/1", headers=_h(), json=payload)
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"
    assert env.db.committed == 0


def test_admin_update_archived_and_missing(client, monkeypatch):
    _use_portal(monkeypatch)
    env = Env()
    env.repo.seed(make_dokument(id=1, status="ARCHIVED"))
    _wire_services(env)
    archived = client.put(f"{ADMIN}/1", headers=_h(), json={"naziv": "N", "redosled": 1})
    missing = client.put(f"{ADMIN}/9", headers=_h(), json={"naziv": "N", "redosled": 1})
    assert archived.status_code == 409
    assert archived.json()["error"]["code"] == "ONBOARDING_DOCUMENT_ARCHIVED"
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "ONBOARDING_DOCUMENT_NOT_FOUND"


# ===================================================== ADMIN replace content
def test_admin_replace_content_in_draft_increments_version(client, monkeypatch):
    _use_portal(monkeypatch)
    env = Env()
    env.repo.seed(make_dokument(id=1, status="DRAFT"))
    _wire_services(env)
    new_pdf = make_pdf_bytes(pages=2)

    resp = client.put(f"{ADMIN}/1/content", headers=_h(), files=_upload(new_pdf, name="novi.pdf"))
    assert resp.status_code == 200
    body = resp.json()
    assert body["verzija"] == 2 and body["sha256"] == hashlib.sha256(new_pdf).hexdigest()
    assert body["originalni_naziv_fajla"] == "novi.pdf"
    assert [e["sifra_akcije"] for e in env.audit.entries] == [
        "ADMIN_ONBOARDING_DOCUMENT_CONTENT_REPLACED"
    ]


def test_admin_replace_with_same_pdf_is_noop(client, monkeypatch):
    _use_portal(monkeypatch)
    env = Env()
    dok = env.repo.seed(make_dokument(id=1, status="DRAFT"))
    _wire_services(env)
    resp = client.put(f"{ADMIN}/1/content", headers=_h(), files=_upload(bytes(dok.sadrzaj)))
    assert resp.status_code == 200 and resp.json()["verzija"] == 1
    assert env.audit.entries == []


def test_admin_replace_content_requires_draft(client, monkeypatch):
    _use_portal(monkeypatch)
    env = Env()
    env.repo.seed(make_dokument(id=1, status="PUBLISHED"))
    env.repo.seed(make_dokument(id=2, status="ARCHIVED"))
    _wire_services(env)
    published = client.put(f"{ADMIN}/1/content", headers=_h(), files=_upload(make_pdf_bytes(pages=3)))
    archived = client.put(f"{ADMIN}/2/content", headers=_h(), files=_upload(make_pdf_bytes(pages=3)))
    assert published.status_code == 409
    assert published.json()["error"]["code"] == "ONBOARDING_DOCUMENT_NOT_DRAFT"
    assert archived.status_code == 409
    assert archived.json()["error"]["code"] == "ONBOARDING_DOCUMENT_ARCHIVED"
    assert env.db.committed == 0


def test_admin_replace_content_invalid_pdf_rejected(client, monkeypatch):
    _use_portal(monkeypatch)
    env = Env()
    env.repo.seed(make_dokument(id=1, status="DRAFT"))
    _wire_services(env)
    resp = client.put(f"{ADMIN}/1/content", headers=_h(), files=_upload(b"nije pdf"))
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "INVALID_PDF_DOCUMENT"
    assert env.repo.docs[1].verzija == 1


# ========================================================== ADMIN status
def test_admin_status_flow_publish_unpublish_archive(client, monkeypatch):
    _use_portal(monkeypatch)
    env = Env()
    env.repo.seed(make_dokument(id=1, status="DRAFT"))
    _wire_services(env)

    published = client.patch(f"{ADMIN}/1/status", headers=_h(), json={"status": "PUBLISHED"})
    assert published.status_code == 200
    assert published.json()["status"] == "PUBLISHED" and published.json()["datum_objave"] is not None

    unpublished = client.patch(f"{ADMIN}/1/status", headers=_h(), json={"status": "DRAFT"})
    assert unpublished.json()["status"] == "DRAFT" and unpublished.json()["datum_objave"] is None

    archived = client.patch(f"{ADMIN}/1/status", headers=_h(), json={"status": "ARCHIVED"})
    assert archived.json()["status"] == "ARCHIVED"

    assert [e["sifra_akcije"] for e in env.audit.entries] == [
        "ADMIN_ONBOARDING_DOCUMENT_PUBLISHED",
        "ADMIN_ONBOARDING_DOCUMENT_UNPUBLISHED",
        "ADMIN_ONBOARDING_DOCUMENT_ARCHIVED",
    ]


def test_admin_status_archived_is_terminal_and_idempotent(client, monkeypatch):
    _use_portal(monkeypatch)
    env = Env()
    env.repo.seed(make_dokument(id=1, status="ARCHIVED"))
    _wire_services(env)
    for target in ("DRAFT", "PUBLISHED"):
        resp = client.patch(f"{ADMIN}/1/status", headers=_h(), json={"status": target})
        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "ONBOARDING_DOCUMENT_ARCHIVED"
    same = client.patch(f"{ADMIN}/1/status", headers=_h(), json={"status": "ARCHIVED"})
    assert same.status_code == 200 and env.audit.entries == []


def test_admin_status_unknown_value_and_missing_document(client, monkeypatch):
    _use_portal(monkeypatch)
    env = Env()
    env.repo.seed(make_dokument(id=1))
    _wire_services(env)
    bad = client.patch(f"{ADMIN}/1/status", headers=_h(), json={"status": "DELETED"})
    missing = client.patch(f"{ADMIN}/77/status", headers=_h(), json={"status": "PUBLISHED"})
    no_body = client.patch(f"{ADMIN}/1/status", headers=_h(), json={})
    assert bad.status_code == 422
    assert bad.json()["error"]["code"] == "INVALID_ONBOARDING_DOCUMENT_STATUS"
    assert missing.status_code == 404
    assert no_body.status_code == 422 and no_body.json()["error"]["code"] == "VALIDATION_ERROR"


# ===================================================== ADMIN list / detail
def _seed_list(env: Env):
    env.repo.seed(make_dokument(id=1, naziv="Alfa pravilnik", status="DRAFT", redosled=2))
    env.repo.seed(make_dokument(id=2, naziv="Beta uputstvo", status="PUBLISHED", redosled=1))
    env.repo.seed(make_dokument(id=3, naziv="Gama pravilnik", status="ARCHIVED", redosled=1))


def test_admin_list_filter_search_and_pagination(client, monkeypatch):
    _use_portal(monkeypatch)
    env = Env()
    _seed_list(env)
    _wire_services(env)

    everything = client.get(ADMIN, headers=_h()).json()
    assert [i["id"] for i in everything["items"]] == [2, 3, 1]
    assert everything["total"] == 3 and everything["page"] == 1 and everything["page_size"] == 20
    assert "sadrzaj" not in client.get(ADMIN, headers=_h()).text

    by_status = client.get(ADMIN, headers=_h(), params={"status": "ARCHIVED"}).json()
    assert [i["id"] for i in by_status["items"]] == [3]

    searched = client.get(ADMIN, headers=_h(), params={"search": "PRAVILNIK"}).json()
    assert [i["id"] for i in searched["items"]] == [3, 1]

    page = client.get(ADMIN, headers=_h(), params={"page": 2, "page_size": 2}).json()
    assert [i["id"] for i in page["items"]] == [1] and page["total"] == 3


@pytest.mark.parametrize(
    "params",
    [{"page": 0}, {"page_size": 0}, {"page_size": 101}],
)
def test_admin_list_pagination_bounds(client, monkeypatch, params):
    _use_portal(monkeypatch)
    _wire_services(Env())
    resp = client.get(ADMIN, headers=_h(), params=params)
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"


def test_admin_list_page_size_100_allowed_and_bad_status_is_422(client, monkeypatch):
    _use_portal(monkeypatch)
    _wire_services(Env())
    assert client.get(ADMIN, headers=_h(), params={"page_size": 100}).status_code == 200
    bad = client.get(ADMIN, headers=_h(), params={"status": "NEPOZNAT"})
    assert bad.status_code == 422
    assert bad.json()["error"]["code"] == "INVALID_ONBOARDING_DOCUMENT_STATUS"


def test_admin_detail_includes_hash_and_actors(client, monkeypatch):
    _use_portal(monkeypatch)
    env = Env()
    dok = env.repo.seed(make_dokument(id=1, status="DRAFT"))
    _wire_services(env)
    body = client.get(f"{ADMIN}/1", headers=_h()).json()
    assert body["sha256"] == dok.sha256 and body["status"] == "DRAFT"
    assert body["kreirao_platni_broj"] == "admin1" and "sadrzaj" not in body
    assert client.get(f"{ADMIN}/404", headers=_h()).status_code == 404


def test_admin_content_preview_in_any_status(client, monkeypatch):
    _use_portal(monkeypatch)
    env = Env()
    drafts = [env.repo.seed(make_dokument(id=i, status=s)) for i, s in ((1, "DRAFT"), (2, "ARCHIVED"))]
    _wire_services(env)
    for dok in drafts:
        resp = client.get(f"{ADMIN}/{int(dok.id)}/content", headers=_h())
        assert resp.status_code == 200 and resp.content == dok.sadrzaj
        assert resp.headers["content-type"] == "application/pdf"
        assert resp.headers["cache-control"] == "private, no-store"
        assert resp.headers["x-content-type-options"] == "nosniff"
        assert resp.headers["etag"] == f'"{dok.sha256}"'


def test_no_delete_endpoint_exists(client, monkeypatch):
    _use_portal(monkeypatch)
    env = Env()
    env.repo.seed(make_dokument(id=1))
    _wire_services(env)
    assert client.delete(f"{ADMIN}/1", headers=_h()).status_code == 405
    assert 1 in env.repo.docs


# ================================================================ OpenAPI
def test_openapi_contains_all_routes_and_binary_pdf():
    spec = app.openapi()
    paths = spec["paths"]
    assert set(paths[BASE]) == {"get"}
    assert set(paths[f"{BASE}/{{document_id}}"]) == {"get"}
    assert set(paths[f"{BASE}/{{document_id}}/content"]) == {"get"}
    assert set(paths[ADMIN]) == {"get", "post"}
    assert set(paths[f"{ADMIN}/{{document_id}}"]) == {"get", "put"}
    assert set(paths[f"{ADMIN}/{{document_id}}/content"]) == {"get", "put"}
    assert set(paths[f"{ADMIN}/{{document_id}}/status"]) == {"patch"}
    assert "delete" not in str(paths[f"{ADMIN}/{{document_id}}"])

    for url in (f"{BASE}/{{document_id}}/content", f"{ADMIN}/{{document_id}}/content"):
        ok = paths[url]["get"]["responses"]["200"]["content"]
        assert ok["application/pdf"]["schema"] == {"type": "string", "format": "binary"}

    for operation in (paths[ADMIN]["post"], paths[f"{ADMIN}/{{document_id}}/content"]["put"]):
        assert "multipart/form-data" in operation["requestBody"]["content"]

    schemas = spec["components"]["schemas"]
    create_form = next(v for k, v in schemas.items() if k.startswith("Body_create_document"))
    assert {"naziv", "opis", "redosled", "file"} <= set(create_form["properties"])
    # OpenAPI 3.1: binarno polje se opisuje sa contentMediaType (ne vise format: binary).
    assert create_form["properties"]["file"]["contentMediaType"] == "application/octet-stream"
    replace_form = next(v for k, v in schemas.items() if k.startswith("Body_replace_document_content"))
    assert "file" in replace_form["properties"]


# ============================================== granice REDOSLED / trim / OpenAPI
REDOSLED_MAX = 9_999_999_999


def test_admin_post_redosled_maximum_passes_and_above_is_422(client, monkeypatch):
    _use_portal(monkeypatch)
    env = Env()
    _wire_services(env)

    ok = client.post(
        ADMIN, headers=_h(), data={"naziv": "N", "redosled": str(REDOSLED_MAX)}, files=_upload()
    )
    assert ok.status_code == 201 and ok.json()["redosled"] == REDOSLED_MAX
    committed = env.db.committed

    too_big = client.post(
        ADMIN, headers=_h(), data={"naziv": "N", "redosled": str(REDOSLED_MAX + 1)}, files=_upload()
    )
    assert too_big.status_code == 422
    assert too_big.json()["error"]["code"] == "VALIDATION_ERROR"
    assert env.db.committed == committed and len(env.repo.added) == 1  # nista upisano


def test_admin_put_redosled_maximum_passes_and_above_is_422(client, monkeypatch):
    _use_portal(monkeypatch)
    env = Env()
    env.repo.seed(make_dokument(id=1, redosled=2))
    _wire_services(env)

    ok = client.put(f"{ADMIN}/1", headers=_h(), json={"naziv": "N", "redosled": REDOSLED_MAX})
    assert ok.status_code == 200 and ok.json()["redosled"] == REDOSLED_MAX
    committed = env.db.committed

    too_big = client.put(
        f"{ADMIN}/1", headers=_h(), json={"naziv": "N", "redosled": REDOSLED_MAX + 1}
    )
    assert too_big.status_code == 422
    assert too_big.json()["error"]["code"] == "VALIDATION_ERROR"
    assert env.db.committed == committed
    assert int(env.repo.docs[1].redosled) == REDOSLED_MAX


def test_admin_post_and_put_length_limits_apply_after_trim(client, monkeypatch):
    _use_portal(monkeypatch)
    env = Env()
    env.repo.seed(make_dokument(id=1))
    _wire_services(env)
    padded_name = "  " + "a" * 200 + "  "
    padded_opis = "  " + "b" * 4000 + "  "

    created = client.post(
        ADMIN, headers=_h(), data={"naziv": padded_name, "opis": padded_opis}, files=_upload()
    )
    assert created.status_code == 201
    assert len(created.json()["naziv"]) == 200 and len(created.json()["opis"]) == 4000

    updated = client.put(
        f"{ADMIN}/1", headers=_h(), json={"naziv": padded_name, "opis": padded_opis, "redosled": 1}
    )
    assert updated.status_code == 200
    assert len(updated.json()["naziv"]) == 200 and len(updated.json()["opis"]) == 4000

    for naziv, opis in (("a" * 201, None), ("N", "b" * 4001)):
        form = {"naziv": naziv}
        if opis:
            form["opis"] = opis
        post = client.post(ADMIN, headers=_h(), data=form, files=_upload())
        put = client.put(
            f"{ADMIN}/1", headers=_h(), json={"naziv": naziv, "opis": opis, "redosled": 1}
        )
        for resp in (post, put):
            assert resp.status_code == 422
            assert resp.json()["error"]["code"] == "VALIDATION_ERROR"


def test_admin_blank_name_rejected_and_blank_opis_becomes_null(client, monkeypatch):
    _use_portal(monkeypatch)
    env = Env()
    env.repo.seed(make_dokument(id=1, opis="stari opis"))
    _wire_services(env)

    for blank in ("", "   "):
        post = client.post(ADMIN, headers=_h(), data={"naziv": blank}, files=_upload())
        put = client.put(f"{ADMIN}/1", headers=_h(), json={"naziv": blank, "redosled": 1})
        assert post.status_code == 422 and put.status_code == 422

    created = client.post(ADMIN, headers=_h(), data={"naziv": "N", "opis": "   "}, files=_upload())
    assert created.status_code == 201 and created.json()["opis"] is None
    updated = client.put(
        f"{ADMIN}/1", headers=_h(), json={"naziv": "N", "opis": "   ", "redosled": 1}
    )
    assert updated.status_code == 200 and updated.json()["opis"] is None


def test_openapi_constraints_match_real_validation():
    schemas = app.openapi()["components"]["schemas"]
    create_form = next(v for k, v in schemas.items() if k.startswith("Body_create_document"))
    update_req = schemas["AdminOnboardingDocumentUpdateRequest"]

    def opis_max_length(props):
        # opis je `string | null`: ogranicenje je na string grani anyOf
        branches = [b for b in props["opis"]["anyOf"] if b.get("type") == "string"]
        assert len(branches) == 1
        return branches[0]["maxLength"]

    for props in (create_form["properties"], update_req["properties"]):
        assert props["naziv"]["minLength"] == 1
        assert props["naziv"]["maxLength"] == 200
        assert opis_max_length(props) == 4000
        assert props["redosled"]["minimum"] == 1
        assert props["redosled"]["maximum"] == REDOSLED_MAX

    # nema vestackih granica 400 / 8000 iz prethodne verzije
    limits = set()
    for props in (create_form["properties"], update_req["properties"]):
        limits.add(props["naziv"]["maxLength"])
        limits.add(opis_max_length(props))
    assert limits == {200, 4000}
