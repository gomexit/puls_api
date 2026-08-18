import datetime

import pytest

from app.core.exceptions import (
    AccountDisabledError,
    AccountInactiveError,
    AccountLockedError,
    InvalidCredentialsError,
    InvalidResetCodeError,
    InvalidSessionError,
    ResetCodeExpiredError,
)
from app.core.security import generate_reset_code, hash_password, hash_reset_code
from app.services.auth_service import AuthService
from tests.fakes import (
    FakeAuditService,
    FakeConfigurationService,
    FakeDb,
    FakeKorisnikRepository,
    FakeResetPasswordRepository,
    FakeSessionRepository,
    FakeSmsProvider,
    make_korisnik,
)


def build_auth_service(korisnici=None, config_values=None, sms_should_succeed=True):
    db = FakeDb()
    korisnik_repository = FakeKorisnikRepository(korisnici)
    session_repository = FakeSessionRepository()
    reset_repository = FakeResetPasswordRepository()
    configuration_service = FakeConfigurationService(config_values)
    audit_service = FakeAuditService()
    sms_provider = FakeSmsProvider(should_succeed=sms_should_succeed)

    service = AuthService(
        db=db,
        sms_provider=sms_provider,
        korisnik_repository=korisnik_repository,
        session_repository=session_repository,
        reset_repository=reset_repository,
        configuration_service=configuration_service,
        audit_service=audit_service,
    )
    return service, db, korisnik_repository, session_repository, reset_repository, audit_service, sms_provider


def active_login_ready_user(**overrides):
    defaults = dict(
        lozinka_hash=hash_password("Password123"),
        obavezna_promena_lozinke="N",
        telefon_potvrdjen="D",
    )
    defaults.update(overrides)
    return make_korisnik(**defaults)


class TestLogin:
    def test_successful_login_creates_session(self):
        korisnik = active_login_ready_user()
        service, db, _, session_repo, _, audit, _ = build_auth_service([korisnik])

        result = service.login(
            korisnik.platni_broj, "Password123", "device-1", "Xiaomi 13 Pro", "1.2.3.4", "agent"
        )

        assert result.token
        assert result.sesija.aktivna == "D"
        assert korisnik.broj_neuspesnih_prijava == 0
        assert korisnik.datum_poslednje_prijave is not None
        assert db.committed >= 1
        assert any(e["sifra_akcije"] == "LOGIN_USPESAN" for e in audit.entries)

    def test_wrong_password_increments_failed_attempts(self):
        korisnik = active_login_ready_user()
        service, *_ = build_auth_service([korisnik])

        with pytest.raises(InvalidCredentialsError):
            service.login(korisnik.platni_broj, "wrong-password", "device-1", None, None, None)

        assert korisnik.broj_neuspesnih_prijava == 1

    def test_account_locks_after_max_attempts(self):
        korisnik = active_login_ready_user()
        service, *_ = build_auth_service([korisnik], config_values={"MAX_NEUSPESNIH_PRIJAVA": "3"})

        for _ in range(3):
            with pytest.raises(InvalidCredentialsError):
                service.login(korisnik.platni_broj, "wrong-password", "device-1", None, None, None)

        assert korisnik.zakljucan == "D"
        assert korisnik.datum_zakljucavanja is not None

    def test_login_rejected_for_inactive_employee(self):
        korisnik = active_login_ready_user(status_zaposlenja="NEAKTIVAN")
        service, *_ = build_auth_service([korisnik])

        with pytest.raises(AccountInactiveError):
            service.login(korisnik.platni_broj, "Password123", "device-1", None, None, None)

    def test_login_rejected_for_disabled_account(self):
        korisnik = active_login_ready_user(status_naloga="ONEMOGUCEN")
        service, *_ = build_auth_service([korisnik])

        with pytest.raises(AccountDisabledError):
            service.login(korisnik.platni_broj, "Password123", "device-1", None, None, None)

    def test_login_rejected_for_locked_account(self):
        korisnik = active_login_ready_user(zakljucan="D")
        service, *_ = build_auth_service([korisnik])

        with pytest.raises(AccountLockedError):
            service.login(korisnik.platni_broj, "Password123", "device-1", None, None, None)

    def test_successful_first_login_returns_flags(self):
        korisnik = make_korisnik(lozinka_hash=hash_password("TempPass1"))
        service, *_ = build_auth_service([korisnik])

        result = service.login(korisnik.platni_broj, "TempPass1", "device-1", None, None, None)

        assert result.korisnik.obavezna_promena_lozinke == "D"
        assert result.korisnik.telefon_potvrdjen == "N"

    def test_one_active_device_revokes_previous_session(self):
        korisnik = active_login_ready_user()
        service, *_ = build_auth_service([korisnik])

        first = service.login(korisnik.platni_broj, "Password123", "xiaomi-device", None, None, None)
        second = service.login(korisnik.platni_broj, "Password123", "samsung-device", None, None, None)

        assert first.sesija.aktivna == "N"
        assert first.sesija.razlog_ponistavanja == "NOVA_PRIJAVA"
        assert second.sesija.aktivna == "D"


class TestChangePassword:
    def test_change_password_success(self):
        korisnik = active_login_ready_user(obavezna_promena_lozinke="D")
        service, *_ = build_auth_service([korisnik])

        service.change_password(korisnik, "Password123", "NewPassword1", "NewPassword1")

        assert korisnik.obavezna_promena_lozinke == "N"
        assert service.password_service.verify("NewPassword1", korisnik.lozinka_hash)

    def test_change_password_wrong_current_password(self):
        korisnik = active_login_ready_user()
        service, *_ = build_auth_service([korisnik])

        with pytest.raises(InvalidCredentialsError):
            service.change_password(korisnik, "WrongCurrent", "NewPassword1", "NewPassword1")


class TestConfirmPhone:
    def test_confirm_phone_updates_user(self):
        korisnik = active_login_ready_user(telefon_potvrdjen="N", broj_telefona="+38160000")
        service, *_ = build_auth_service([korisnik])

        service.confirm_phone(korisnik, "+38160000")

        assert korisnik.telefon_potvrdjen == "D"
        assert korisnik.datum_potvrde_telefona is not None


class TestLogout:
    def test_logout_revokes_session(self):
        korisnik = active_login_ready_user()
        service, *_ = build_auth_service([korisnik])
        result = service.login(korisnik.platni_broj, "Password123", "device-1", None, None, None)

        service.logout(korisnik, result.sesija)

        assert result.sesija.aktivna == "N"
        assert result.sesija.razlog_ponistavanja == "LOGOUT"

        with pytest.raises(InvalidSessionError):
            service.authenticate_token(result.token)


class TestForgotPassword:
    def test_forgot_password_sends_sms_for_valid_user(self):
        korisnik = active_login_ready_user()
        service, *_, sms = build_auth_service([korisnik])

        service.forgot_password(korisnik.platni_broj, ip_adresa=None)

        assert len(sms.sent) == 1
        assert sms.sent[0][0] == korisnik.broj_telefona

    def test_forgot_password_silent_for_unknown_user(self):
        service, *_, sms = build_auth_service([])

        service.forgot_password("nonexistent", ip_adresa=None)

        assert sms.sent == []


class TestResetPassword:
    def test_reset_password_wrong_code(self):
        korisnik = active_login_ready_user()
        service, db, _, _, reset_repo, _, _ = build_auth_service([korisnik])
        service.forgot_password(korisnik.platni_broj, ip_adresa=None)

        with pytest.raises(InvalidResetCodeError):
            service.reset_password(korisnik.platni_broj, "000000", "NewPassword1", "NewPassword1", None)

        reset = reset_repo.get_active_for_user(korisnik.id)
        assert reset.broj_pokusaja == 1

    def test_reset_password_expired_code(self):
        korisnik = active_login_ready_user()
        service, db, _, _, reset_repo, _, _ = build_auth_service([korisnik])
        code = generate_reset_code()
        reset = reset_repo.create(korisnik.id, hash_reset_code(code), ttl_minutes=15, ip_adresa=None)
        reset.datum_isteka = datetime.datetime.now() - datetime.timedelta(minutes=1)

        with pytest.raises(ResetCodeExpiredError):
            service.reset_password(korisnik.platni_broj, code, "NewPassword1", "NewPassword1", None)

    def test_reset_password_success_revokes_sessions_and_unlocks(self):
        korisnik = active_login_ready_user(zakljucan="D")
        service, db, _, session_repo, reset_repo, audit, _ = build_auth_service([korisnik])
        code = generate_reset_code()
        reset_repo.create(korisnik.id, hash_reset_code(code), ttl_minutes=15, ip_adresa=None)

        service.reset_password(korisnik.platni_broj, code, "NewPassword1", "NewPassword1", None)

        assert korisnik.zakljucan == "N"
        assert korisnik.obavezna_promena_lozinke == "N"
        assert service.password_service.verify("NewPassword1", korisnik.lozinka_hash)
        assert any(e["sifra_akcije"] == "RESET_LOZINKE" for e in audit.entries)


class TestFailedLoginAudit:
    """Fix #2: every rejected login must be durably audited (committed), not rolled back."""

    def _run_and_assert(self, korisnici, platni_broj, expected_exc):
        service, db, _, _, _, audit, _ = build_auth_service(korisnici)
        with pytest.raises(expected_exc):
            service.login(platni_broj, "irrelevant", "dev-1", None, "1.2.3.4", "agent")
        failed = [e for e in audit.entries if e["sifra_akcije"] == "LOGIN_NEUSPESAN"]
        assert failed, "LOGIN_NEUSPESAN audit entry expected"
        assert failed[-1].get("ip_adresa") == "1.2.3.4"
        assert failed[-1].get("detalji")  # safe reason recorded
        assert db.committed >= 1

    def test_unknown_user_is_audited(self):
        self._run_and_assert([], "nepostojeci", InvalidCredentialsError)

    def test_inactive_employee_is_audited(self):
        k = active_login_ready_user(status_zaposlenja="NEAKTIVAN")
        self._run_and_assert([k], k.platni_broj, AccountInactiveError)

    def test_disabled_account_is_audited(self):
        k = active_login_ready_user(status_naloga="ONEMOGUCEN")
        self._run_and_assert([k], k.platni_broj, AccountDisabledError)

    def test_locked_account_is_audited(self):
        k = active_login_ready_user(zakljucan="D")
        self._run_and_assert([k], k.platni_broj, AccountLockedError)

    def test_bad_password_is_audited_and_committed(self):
        k = active_login_ready_user()
        service, db, _, _, _, audit, _ = build_auth_service([k])
        with pytest.raises(InvalidCredentialsError):
            service.login(k.platni_broj, "wrong", "dev-1", None, "1.2.3.4", None)
        assert any(e["sifra_akcije"] == "LOGIN_NEUSPESAN" for e in audit.entries)
        assert k.broj_neuspesnih_prijava == 1
        assert db.committed >= 1


class TestForgotPasswordSmsFailure:
    """Fix #3: a failed SMS must not present a new reset code as sent, nor drop the old one."""

    def test_failed_sms_does_not_create_reset(self):
        korisnik = active_login_ready_user()
        service, db, _, _, reset_repo, audit, sms = build_auth_service(
            [korisnik], sms_should_succeed=False
        )
        service.forgot_password(korisnik.platni_broj, ip_adresa="1.1.1.1")

        assert reset_repo.get_active_for_user(korisnik.id) is None
        assert any(e["sifra_akcije"] == "ZAHTEV_RESET_LOZINKE_GRESKA" for e in audit.entries)
        assert not any(e["sifra_akcije"] == "ZAHTEV_RESET_LOZINKE" for e in audit.entries)

    def test_failed_sms_keeps_previous_valid_code(self):
        korisnik = active_login_ready_user()
        service, db, _, _, reset_repo, audit, sms = build_auth_service(
            [korisnik], sms_should_succeed=False
        )
        reset_repo.create(korisnik.id, hash_reset_code("111111"), ttl_minutes=15, ip_adresa=None)

        service.forgot_password(korisnik.platni_broj, ip_adresa=None)

        active = reset_repo.get_active_for_user(korisnik.id)
        assert active is not None
        assert active.aktivan == "D"
