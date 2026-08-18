"""HTTP-level tests for the login endpoint using dependency overrides, so no real
Oracle connection is required."""

import pytest
from fastapi.testclient import TestClient

from app.core.exceptions import InvalidCredentialsError
from app.dependencies.auth import get_auth_service
from app.main import app


class _StubAuthService:
    """Always rejects credentials; never touches the database."""

    def login(self, *args, **kwargs):
        raise InvalidCredentialsError()


@pytest.fixture
def client():
    app.dependency_overrides[get_auth_service] = lambda: _StubAuthService()
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _login(client, platni_broj="12345"):
    return client.post(
        "/api/v1/auth/login",
        json={"platni_broj": platni_broj, "lozinka": "x", "uredjaj_id": "dev-1"},
    )


def test_login_returns_401_on_bad_credentials(client):
    resp = _login(client)
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "INVALID_CREDENTIALS"


def test_login_validation_error_shape(client):
    resp = client.post("/api/v1/auth/login", json={"platni_broj": "", "lozinka": "x", "uredjaj_id": "d"})
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"


def test_oversized_user_agent_does_not_500(client):
    resp = client.post(
        "/api/v1/auth/login",
        json={"platni_broj": "777", "lozinka": "x", "uredjaj_id": "dev-1"},
        headers={"User-Agent": "U" * 5000},
    )
    # Stub raises invalid-credentials; the point is the long header is accepted (no 500).
    assert resp.status_code == 401
