"""FCM token deaktivacija integrisana u login/logout/reset - u istoj transakciji."""

import pytest

from app.core.security import generate_reset_code, hash_password, hash_reset_code
from app.services.auth_service import AuthService
from tests.fakes import (
    FakeAuditService,
    FakeConfigurationService,
    FakeDb,
    FakeKorisnikRepository,
    FakePushTokenRepository,
    FakeResetPasswordRepository,
    FakeSessionRepository,
    FakeSmsProvider,
    make_korisnik,
)


def _build(korisnici):
    db = FakeDb()
    push_repo = FakePushTokenRepository()
    service = AuthService(
        db=db,
        sms_provider=FakeSmsProvider(),
        korisnik_repository=FakeKorisnikRepository(korisnici),
        session_repository=FakeSessionRepository(),
        reset_repository=FakeResetPasswordRepository(),
        configuration_service=FakeConfigurationService(),
        audit_service=FakeAuditService(),
        push_token_repository=push_repo,
    )
    return service, db, push_repo


def _user(**ov):
    return make_korisnik(
        lozinka_hash=hash_password("Password123"),
        obavezna_promena_lozinke="N",
        telefon_potvrdjen="D",
        **ov,
    )


def test_login_deactivates_all_previous_tokens():
    k = _user()
    service, db, push_repo = _build([k])
    push_repo.upsert(k.id, "old-dev", "old-tok", None)
    service.login(k.platni_broj, "Password123", "new-dev", None, None, None)
    assert push_repo.tokens[(k.id, "old-dev")]["aktivan"] == "N"
    assert db.committed >= 1


def test_logout_deactivates_current_device_in_one_tx():
    k = _user()
    service, db, push_repo = _build([k])
    push_repo.upsert(k.id, "dev-1", "tok-1", None)
    sesija = service.session_repository.create_session(
        k.id, "hash", "dev-1", None, 30, None, None
    )
    committed_before = db.committed
    service.logout(k, sesija)
    assert push_repo.tokens[(k.id, "dev-1")]["aktivan"] == "N"
    assert sesija.aktivna == "N"
    assert db.committed == committed_before + 1  # jedan commit (jedna transakcija)


def test_reset_deactivates_all_tokens():
    k = _user(zakljucan="D")
    service, db, push_repo = _build([k])
    push_repo.upsert(k.id, "dev-1", "tok-1", None)
    code = generate_reset_code()
    service.reset_repository.create(k.id, hash_reset_code(code), ttl_minutes=15, ip_adresa=None)
    service.reset_password(k.platni_broj, code, "NewPassword1", "NewPassword1", None)
    assert push_repo.tokens[(k.id, "dev-1")]["aktivan"] == "N"


def test_logout_rolls_back_if_token_op_fails():
    k = _user()
    service, db, push_repo = _build([k])
    sesija = service.session_repository.create_session(
        k.id, "hash", "dev-1", None, 30, None, None
    )

    def _boom(*a, **k_):
        raise RuntimeError("token op pukla")

    push_repo.deactivate_user_device = _boom
    with pytest.raises(RuntimeError):
        service.logout(k, sesija)
    assert db.rolled_back >= 1
