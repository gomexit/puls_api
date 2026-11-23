"""Dokumentacija API-ja i /health ne smeju biti javni na produkciji."""

from fastapi.testclient import TestClient

from app import main
from app.main import app, docs_urls


def test_docs_disabled_by_default():
    with TestClient(app) as client:
        for path in ("/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect"):
            assert client.get(path).status_code == 404, path


def test_docs_urls_when_enabled():
    assert docs_urls(True) == {"docs_url": "/docs", "redoc_url": "/redoc", "openapi_url": "/openapi.json"}
    assert docs_urls(False) == {"docs_url": None, "redoc_url": None, "openapi_url": None}


def test_health_hidden_behind_proxy(monkeypatch):
    monkeypatch.setattr(main.settings, "health_public", False)
    with TestClient(app) as client:
        for header in ("X-Forwarded-For", "X-Forwarded-Prefix", "X-Real-IP", "Forwarded"):
            response = client.get("/health", headers={header: "1.2.3.4"})
            assert response.status_code == 404, header
            assert response.json() == {"detail": "Not Found"}


def test_health_direct_call_works(monkeypatch):
    monkeypatch.setattr(main.settings, "health_public", False)

    class FakeDb:
        def execute(self, _):
            return None

        def close(self):
            return None

    monkeypatch.setattr(main, "SessionLocal", FakeDb)
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_public_option(monkeypatch):
    monkeypatch.setattr(main.settings, "health_public", True)
    monkeypatch.setattr(main, "SessionLocal", lambda: (_ for _ in ()).throw(RuntimeError("no db")))
    with TestClient(app) as client:
        response = client.get("/health", headers={"X-Forwarded-For": "1.2.3.4"})
    assert response.status_code == 200
    assert response.json() == {"status": "degraded"}


def test_security_headers_on_every_response():
    with TestClient(app) as client:
        response = client.get("/api/v1/auth/me")
    assert response.headers["strict-transport-security"] == "max-age=31536000; includeSubDomains"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"
