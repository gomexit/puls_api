"""HTTP provera modula SLIKE: employee prikaz (Bearer, ETag/304), admin upload (OBO),
izmena naziva, arhiviranje, greske i OpenAPI."""

import pytest
from fastapi.testclient import TestClient

from app.api.v1 import admin_images as admin_mod
from app.api.v1 import images as employee_mod
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.dependencies import portal_auth
from app.dependencies.auth import get_current_ready_user
from app.main import app
from app.services.image_service import ImageService
from tests.fakes import FakeAuditService, make_korisnik
from tests.image_fakes import (
    FIXED_NOW,
    FakeImageDb,
    FakeImageRepo,
    make_image_bytes,
    make_slika,
)

VALID_KEY = "s" * 40
BASE = "/api/v1/images"
ADMIN = "/api/v1/admin/images"


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


class Env:
    def __init__(self, max_mb: int = 5):
        self.db = FakeImageDb()
        self.repo = FakeImageRepo(self.db)
        self.audit = FakeAuditService()
        self.settings = Settings(_env_file=None, image_max_size_mb=max_mb)

    def service(self) -> ImageService:
        return ImageService(
            db=self.db,
            repository=self.repo,
            audit_service=self.audit,
            settings=self.settings,
            now_fn=lambda: FIXED_NOW,
        )


def _wire(env: Env) -> None:
    app.dependency_overrides[employee_mod.get_image_service] = env.service
    app.dependency_overrides[admin_mod.get_image_service] = env.service


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


# ============================================================ EMPLOYEE
def test_employee_requires_bearer(client):
    resp = client.get(f"{BASE}/1")
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "INVALID_SESSION"


def test_employee_gets_active_image_with_cache_headers(client):
    env = Env()
    slika = env.repo.seed(make_slika(id=5))
    _wire(env)
    _as_employee()
    resp = client.get(f"{BASE}/5")
    assert resp.status_code == 200
    assert resp.content == slika.sadrzaj
    assert resp.headers["content-type"] == "image/jpeg"
    assert resp.headers["etag"] == f'"{slika.sha256}"'
    assert resp.headers["cache-control"] == "private, max-age=86400"
    assert resp.headers["x-content-type-options"] == "nosniff"


def test_employee_if_none_match_returns_304_without_reading_blob(client):
    env = Env()
    slika = env.repo.seed(make_slika(id=6))
    _wire(env)
    _as_employee()
    resp = client.get(f"{BASE}/6", headers={"If-None-Match": f'W/"{slika.sha256}"'})
    assert resp.status_code == 304
    assert resp.content == b""
    assert env.repo.content_reads == 0

    resp = client.get(f"{BASE}/6", headers={"If-None-Match": '"drugi"'})
    assert resp.status_code == 200
    assert env.repo.content_reads == 1


@pytest.mark.parametrize("headers", [{}, {"If-None-Match": '"x"'}])
def test_employee_archived_or_missing_is_404(client, headers):
    env = Env()
    env.repo.seed(make_slika(id=7, status="ARHIVIRANA"))
    _wire(env)
    _as_employee()
    for image_id in (7, 999):
        resp = client.get(f"{BASE}/{image_id}", headers=headers)
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "IMAGE_NOT_FOUND"


# =============================================================== ADMIN
def test_admin_requires_service_key(client, monkeypatch):
    _use_portal(monkeypatch)
    _wire(Env())
    assert client.get(ADMIN).status_code == 401


def test_admin_employee_role_forbidden(client, monkeypatch):
    _use_portal(monkeypatch, roles=("ZAPOSLENI",))
    _wire(Env())
    assert client.get(ADMIN, headers=_h()).status_code == 403


@pytest.mark.parametrize("role", ["ADMIN", "HR"])
def test_admin_upload_resizes_and_audits(client, monkeypatch, role):
    _use_portal(monkeypatch, roles=(role,))
    env = Env()
    _wire(env)
    resp = client.post(
        ADMIN,
        headers=_h(),
        data={"naziv": "  Logo teretane  "},
        files={"file": ("logo.png", make_image_bytes("PNG", (2400, 600)), "image/png")},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["naziv"] == "Logo teretane"
    assert (body["sirina"], body["visina"]) == (1200, 300)
    assert body["mime_tip"] == "image/png"
    assert body["status"] == "AKTIVNA"
    assert body["url"] == f"/api/v1/images/{body['id']}"
    assert "sha256" not in body and "sadrzaj" not in body
    assert env.db.committed == 1
    assert [e["sifra_akcije"] for e in env.audit.entries] == ["ADMIN_IMAGE_UPLOADED"]
    assert "sha" not in env.audit.entries[0]["detalji"].lower()


def test_admin_upload_rejects_too_large_and_invalid(client, monkeypatch):
    _use_portal(monkeypatch)
    env = Env(max_mb=1)
    _wire(env)
    big = b"\xff\xd8\xff" + b"0" * (1024 * 1024)
    resp = client.post(ADMIN, headers=_h(), data={"naziv": "x"}, files={"file": ("a.jpg", big, "image/jpeg")})
    assert resp.status_code == 413
    assert resp.json()["error"]["code"] == "IMAGE_TOO_LARGE"

    resp = client.post(
        ADMIN, headers=_h(), data={"naziv": "x"}, files={"file": ("a.jpg", b"GIF89a....", "image/jpeg")}
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "INVALID_IMAGE"

    resp = client.post(ADMIN, headers=_h(), data={"naziv": "   "}, files={"file": ("a.png", make_image_bytes("PNG"), "image/png")})
    assert resp.status_code == 422
    assert env.db.committed == 0


def test_admin_list_detail_and_content(client, monkeypatch):
    _use_portal(monkeypatch)
    env = Env()
    env.repo.seed(make_slika(id=1, naziv="Prva"))
    arch = env.repo.seed(make_slika(id=2, naziv="Druga", status="ARHIVIRANA"))
    _wire(env)
    body = client.get(ADMIN, headers=_h()).json()
    assert body["total"] == 2 and body["sort_by"] == "datum_kreiranja" and body["sort_dir"] == "desc"
    assert client.get(ADMIN, headers=_h(), params={"status": "aktivna"}).json()["total"] == 1
    assert client.get(ADMIN, headers=_h(), params={"status": "X"}).json()["error"]["code"] == "INVALID_IMAGE_STATUS"
    assert client.get(f"{ADMIN}/2", headers=_h()).json()["status"] == "ARHIVIRANA"
    content = client.get(f"{ADMIN}/2/content", headers=_h())
    assert content.status_code == 200 and content.content == arch.sadrzaj
    assert content.headers["cache-control"] == "private, no-store"
    assert client.get(f"{ADMIN}/99", headers=_h()).status_code == 404


def test_admin_rename_and_archive_rules(client, monkeypatch):
    _use_portal(monkeypatch)
    env = Env()
    env.repo.seed(make_slika(id=3, naziv="Staro"))
    _wire(env)

    assert client.put(f"{ADMIN}/3", headers=_h(), json={"naziv": "Staro"}).status_code == 200
    assert env.audit.entries == []  # identicna izmena je no-op
    assert client.put(f"{ADMIN}/3", headers=_h(), json={"naziv": "Novo"}).json()["naziv"] == "Novo"

    resp = client.patch(f"{ADMIN}/3/status", headers=_h(), json={"status": "arhivirana"})
    assert resp.json()["status"] == "ARHIVIRANA"
    assert client.patch(f"{ADMIN}/3/status", headers=_h(), json={"status": "ARHIVIRANA"}).status_code == 200
    resp = client.patch(f"{ADMIN}/3/status", headers=_h(), json={"status": "AKTIVNA"})
    assert resp.status_code == 409 and resp.json()["error"]["code"] == "IMAGE_ARCHIVED"
    assert client.put(f"{ADMIN}/3", headers=_h(), json={"naziv": "Jos"}).status_code == 409
    assert [e["sifra_akcije"] for e in env.audit.entries] == ["ADMIN_IMAGE_RENAMED", "ADMIN_IMAGE_ARCHIVED"]


def test_openapi_documents_image_routes(client):
    paths = client.get("/openapi.json").json()["paths"]
    assert "/api/v1/images/{image_id}" in paths
    assert "/api/v1/admin/images" in paths
    assert "/api/v1/admin/images/{image_id}/status" in paths
    assert "/api/v1/home/summary" in paths
