import datetime

import pytest

from app.core.exceptions import (
    AdminSelfActionNotAllowedError,
    SmsDeliveryFailedError,
    UserNotFoundError,
    ValidationBusinessError,
)
from app.services.admin_users_service import AdminUsersService
from app.services.audit_service import AuditAction
from tests.admin_users_fakes import FakeAdminUsersRepository
from tests.fakes import (
    FakeAuditService,
    FakeDb,
    FakePushTokenRepository,
    FakeSessionRepository,
    FakeSmsProvider,
    make_korisnik,
)
from tests.survey_results_fakes import make_raspored


def _service(korisnici=None, roles=None, rasporedi=None, sms_success=True):
    repo = FakeAdminUsersRepository(korisnici=korisnici, roles=roles, rasporedi=rasporedi)
    session_repo = FakeSessionRepository()
    push_repo = FakePushTokenRepository()
    audit = FakeAuditService()
    sms = FakeSmsProvider(should_succeed=sms_success)
    db = FakeDb()
    service = AdminUsersService(
        db=db,
        sms_provider=sms,
        repository=repo,
        session_repository=session_repo,
        push_token_repository=push_repo,
        audit_service=audit,
    )
    return service, repo, session_repo, push_repo, audit, sms, db


def _actor():
    return make_korisnik(id=1, platni_broj="admin1")


# ================================================================ LISTA / DETALJ
def test_list_users_filters_search_status_zakljucan_uloga():
    korisnici = [
        make_korisnik(id=2, platni_broj="AAA", ime="Petar", prezime="Petrović", status_zaposlenja="AKTIVAN"),
        make_korisnik(id=3, platni_broj="BBB", ime="Marko", prezime="Marković", status_zaposlenja="NEAKTIVAN"),
        make_korisnik(id=4, platni_broj="CCC", ime="Ana", prezime="Anić", zakljucan="D"),
    ]
    roles = {2: ["ADMIN"], 3: [], 4: ["HR"]}
    service, *_ = _service(korisnici=korisnici, roles=roles)

    by_search = service.list_users(1, 20, "petar", None, None, None, None)
    assert [u["id"] for u in by_search["items"]] == [2]

    by_status = service.list_users(1, 20, None, "NEAKTIVAN", None, None, None)
    assert [u["id"] for u in by_status["items"]] == [3]

    by_locked = service.list_users(1, 20, None, None, None, True, None)
    assert [u["id"] for u in by_locked["items"]] == [4]

    by_role = service.list_users(1, 20, None, None, None, None, "HR")
    assert [u["id"] for u in by_role["items"]] == [4]


def test_list_users_pagination():
    korisnici = [make_korisnik(id=i, platni_broj=str(i)) for i in range(2, 7)]
    service, *_ = _service(korisnici=korisnici)
    page1 = service.list_users(1, 2, None, None, None, None, None)
    assert page1["total"] == 5 and len(page1["items"]) == 2 and page1["has_more"] is True
    page3 = service.list_users(3, 2, None, None, None, None, None)
    assert len(page3["items"]) == 1 and page3["has_more"] is False


def test_response_never_contains_secrets():
    k = make_korisnik(id=2, platni_broj="AAA", lozinka_hash="argon2$secrethash")
    service, *_ = _service(korisnici=[k])
    view = service.get_user(2)
    assert "lozinka_hash" not in view
    assert "argon2$secrethash" not in str(view)


def test_primary_active_raspored_picks_d():
    k = make_korisnik(id=2, platni_broj="AAA")
    rasporedi = {
        2: [
            make_raspored(2, orgjed_sifra="N-org", radno_mesto_sifra="X", primarni="N"),
            make_raspored(2, orgjed_sifra="D-org", radno_mesto_sifra="Y", primarni="D"),
        ]
    }
    service, *_ = _service(korisnici=[k], rasporedi=rasporedi)
    view = service.get_user(2)
    assert view["orgjed_sifra"] == "D-org"
    assert view["radno_mesto_sifra"] == "Y"


def test_get_user_not_found():
    service, *_ = _service()
    with pytest.raises(UserNotFoundError):
        service.get_user(999)


# ==================================================================== SELF-ACTION
def test_self_action_rejected_for_all_mutations():
    actor = make_korisnik(id=1, platni_broj="admin1")
    service, *_ = _service(korisnici=[actor])
    for fn in (service.lock, service.unlock, service.deactivate, service.reset_password):
        with pytest.raises(AdminSelfActionNotAllowedError):
            fn(actor, actor.id)


def test_missing_target_returns_404():
    actor = _actor()
    service, *_ = _service(korisnici=[actor])
    with pytest.raises(UserNotFoundError):
        service.lock(actor, 999)


# ========================================================================= LOCK
def test_lock_revokes_sessions_and_deactivates_fcm():
    actor = _actor()
    target = make_korisnik(id=2, platni_broj="target")
    service, repo, session_repo, push_repo, audit, _, db = _service(korisnici=[actor, target])
    session_repo.sesije.append(
        type("S", (), {"korisnik_id": 2, "aktivna": "D", "datum_ponistavanja": None, "razlog_ponistavanja": None})()
    )
    push_repo.tokens[(2, "dev-1")] = {"token": "t", "hash": "h", "aktivan": "D", "app_version": None}

    result = service.lock(actor, 2)

    assert result["zakljucan"] is True
    assert target.zakljucan == "D" and target.datum_zakljucavanja is not None
    assert session_repo.sesije[0].aktivna == "N"
    assert push_repo.tokens[(2, "dev-1")]["aktivan"] == "N"
    assert any(e["sifra_akcije"] == AuditAction.ADMIN_USER_LOCKED for e in audit.entries)
    assert db.committed == 1


def test_lock_idempotent_no_duplicate_audit():
    actor = _actor()
    target = make_korisnik(id=2, platni_broj="target", zakljucan="D", datum_zakljucavanja=datetime.datetime(2026, 1, 1))
    service, repo, session_repo, push_repo, audit, _, db = _service(korisnici=[actor, target])

    result = service.lock(actor, 2)

    assert result["zakljucan"] is True
    assert target.datum_zakljucavanja == datetime.datetime(2026, 1, 1)  # nepromenjeno
    assert not any(e["sifra_akcije"] == AuditAction.ADMIN_USER_LOCKED for e in audit.entries)
    assert db.committed == 1  # i dalje se commituje (FOR UPDATE lock se oslobadja)


def test_lock_already_locked_still_revokes_session_and_token_without_new_audit():
    # Sesija/token su mogli nastati POSLE prethodnog lock-a - i dalje moraju biti
    # ukinuti, ali bez ponovnog audit zapisa jer se glavno stanje ne menja.
    actor = _actor()
    target = make_korisnik(id=2, platni_broj="target", zakljucan="D", datum_zakljucavanja=datetime.datetime(2026, 1, 1))
    service, repo, session_repo, push_repo, audit, _, db = _service(korisnici=[actor, target])
    session_repo.sesije.append(
        type("S", (), {"korisnik_id": 2, "aktivna": "D", "datum_ponistavanja": None, "razlog_ponistavanja": None})()
    )
    push_repo.tokens[(2, "dev-1")] = {"token": "t", "hash": "h", "aktivan": "D", "app_version": None}

    service.lock(actor, 2)

    assert session_repo.sesije[0].aktivna == "N"
    assert push_repo.tokens[(2, "dev-1")]["aktivan"] == "N"
    assert not any(e["sifra_akcije"] == AuditAction.ADMIN_USER_LOCKED for e in audit.entries)


# ======================================================================= UNLOCK
def test_unlock_resets_failed_attempts():
    actor = _actor()
    target = make_korisnik(
        id=2, platni_broj="target", zakljucan="D", datum_zakljucavanja=datetime.datetime(2026, 1, 1),
        broj_neuspesnih_prijava=3,
    )
    service, repo, _, _, audit, _, db = _service(korisnici=[actor, target])

    result = service.unlock(actor, 2)

    assert result["zakljucan"] is False
    assert target.datum_zakljucavanja is None
    assert target.broj_neuspesnih_prijava == 0
    assert any(e["sifra_akcije"] == AuditAction.ADMIN_USER_UNLOCKED for e in audit.entries)


def test_unlock_idempotent():
    actor = _actor()
    target = make_korisnik(id=2, platni_broj="target", zakljucan="N", broj_neuspesnih_prijava=0)
    service, _repo, _sess, _push, audit, _sms, _db = _service(korisnici=[actor, target])
    service.unlock(actor, 2)
    assert not any(e["sifra_akcije"] == AuditAction.ADMIN_USER_UNLOCKED for e in audit.entries)


def test_unlock_already_unlocked_but_dirty_state_still_resets_and_audits():
    # ZAKLJUCAN je vec 'N', ali postoje zaostali neuspesni pokusaji/datum zakljucavanja
    # (npr. iz stanja pre nekog ranijeg rucnog popravka) - krajnje stanje mora biti
    # cisto, i posto se NESTO stvarno promenilo, audit se upisuje.
    actor = _actor()
    target = make_korisnik(
        id=2, platni_broj="target", zakljucan="N",
        datum_zakljucavanja=datetime.datetime(2026, 1, 1), broj_neuspesnih_prijava=2,
    )
    service, _repo, _sess, _push, audit, _sms, _db = _service(korisnici=[actor, target])

    result = service.unlock(actor, 2)

    assert result["zakljucan"] is False
    assert target.datum_zakljucavanja is None
    assert target.broj_neuspesnih_prijava == 0
    assert any(e["sifra_akcije"] == AuditAction.ADMIN_USER_UNLOCKED for e in audit.entries)


# ==================================================================== DEACTIVATE
def test_deactivate_does_not_change_status_zaposlenja():
    actor = _actor()
    target = make_korisnik(id=2, platni_broj="target", status_zaposlenja="AKTIVAN", status_naloga="OMOGUCEN")
    service, repo, session_repo, push_repo, audit, _, db = _service(korisnici=[actor, target])

    result = service.deactivate(actor, 2)

    assert result["status_naloga"] == "ONEMOGUCEN"
    assert target.status_naloga == "ONEMOGUCEN"
    assert target.status_zaposlenja == "AKTIVAN"  # NIKAD dirano - Oracle HR procedura upravlja time
    assert any(e["sifra_akcije"] == AuditAction.ADMIN_USER_DEACTIVATED for e in audit.entries)


def test_deactivate_idempotent():
    actor = _actor()
    target = make_korisnik(id=2, platni_broj="target", status_naloga="ONEMOGUCEN")
    service, _repo, _sess, _push, audit, _sms, _db = _service(korisnici=[actor, target])
    service.deactivate(actor, 2)
    assert not any(e["sifra_akcije"] == AuditAction.ADMIN_USER_DEACTIVATED for e in audit.entries)


def test_deactivate_already_deactivated_still_revokes_session_and_token_without_new_audit():
    actor = _actor()
    target = make_korisnik(id=2, platni_broj="target", status_naloga="ONEMOGUCEN")
    service, repo, session_repo, push_repo, audit, _, db = _service(korisnici=[actor, target])
    session_repo.sesije.append(
        type("S", (), {"korisnik_id": 2, "aktivna": "D", "datum_ponistavanja": None, "razlog_ponistavanja": None})()
    )
    push_repo.tokens[(2, "dev-1")] = {"token": "t", "hash": "h", "aktivan": "D", "app_version": None}

    service.deactivate(actor, 2)

    assert session_repo.sesije[0].aktivna == "N"
    assert push_repo.tokens[(2, "dev-1")]["aktivan"] == "N"
    assert not any(e["sifra_akcije"] == AuditAction.ADMIN_USER_DEACTIVATED for e in audit.entries)


# ============================================================== RESET PASSWORD
def test_reset_password_success():
    actor = _actor()
    target = make_korisnik(
        id=2, platni_broj="target", status_zaposlenja="AKTIVAN", status_naloga="OMOGUCEN",
        broj_telefona="060123456", lozinka_hash="stari-hash", zakljucan="D",
        datum_zakljucavanja=datetime.datetime(2026, 1, 1), broj_neuspesnih_prijava=2,
    )
    service, repo, session_repo, push_repo, audit, sms, db = _service(korisnici=[actor, target], sms_success=True)

    result = service.reset_password(actor, 2)

    assert result == {"message": "Nova privremena lozinka je poslata korisniku SMS porukom."}
    assert target.lozinka_hash != "stari-hash"
    assert target.obavezna_promena_lozinke == "D"
    assert target.broj_neuspesnih_prijava == 0
    assert target.zakljucan == "N"
    assert target.datum_zakljucavanja is None
    assert any(e["sifra_akcije"] == AuditAction.ADMIN_USER_PASSWORD_RESET for e in audit.entries)
    # lozinka/SMS sadrzaj se nikad ne pojavljuje u audit zapisu
    assert not any("lozinka" in str(v).lower() and len(str(v)) > 30 for e in audit.entries for v in e.values())


def test_reset_password_sms_failure_does_not_change_password_sessions_tokens():
    actor = _actor()
    target = make_korisnik(
        id=2, platni_broj="target", status_zaposlenja="AKTIVAN", status_naloga="OMOGUCEN",
        broj_telefona="060123456", lozinka_hash="stari-hash",
    )
    service, repo, session_repo, push_repo, audit, sms, db = _service(korisnici=[actor, target], sms_success=False)
    session_repo.sesije.append(
        type("S", (), {"korisnik_id": 2, "aktivna": "D", "datum_ponistavanja": None, "razlog_ponistavanja": None})()
    )
    push_repo.tokens[(2, "dev-1")] = {"token": "t", "hash": "h", "aktivan": "D", "app_version": None}

    with pytest.raises(SmsDeliveryFailedError):
        service.reset_password(actor, 2)

    assert target.lozinka_hash == "stari-hash"
    assert session_repo.sesije[0].aktivna == "D"
    assert push_repo.tokens[(2, "dev-1")]["aktivan"] == "D"
    assert any(e["sifra_akcije"] == AuditAction.ADMIN_USER_PASSWORD_RESET_FAILED for e in audit.entries)
    assert not any(e["sifra_akcije"] == AuditAction.ADMIN_USER_PASSWORD_RESET for e in audit.entries)


def test_reset_password_rejected_for_inactive_employee():
    actor = _actor()
    target = make_korisnik(id=2, platni_broj="target", status_zaposlenja="NEAKTIVAN", broj_telefona="060123456")
    service, *_ = _service(korisnici=[actor, target])
    with pytest.raises(ValidationBusinessError):
        service.reset_password(actor, 2)


def test_reset_password_rejected_without_valid_phone():
    actor = _actor()
    target = make_korisnik(
        id=2, platni_broj="target", status_zaposlenja="AKTIVAN", status_naloga="OMOGUCEN", broj_telefona=None
    )
    service, *_ = _service(korisnici=[actor, target])
    with pytest.raises(ValidationBusinessError):
        service.reset_password(actor, 2)


def test_reset_password_validation_error_rolls_back():
    actor = _actor()
    target = make_korisnik(
        id=2, platni_broj="target", status_zaposlenja="NEAKTIVAN", broj_telefona="060123456"
    )
    service, _repo, _sess, _push, _audit, sms, db = _service(korisnici=[actor, target])
    with pytest.raises(ValidationBusinessError):
        service.reset_password(actor, 2)
    assert db.committed == 0
    assert db.rolled_back == 1
    assert sms.sent == []  # SMS se nikad ne pokusava kad validacija ne prodje


def test_reset_password_sms_provider_exception_rolls_back():
    actor = _actor()
    target = make_korisnik(
        id=2, platni_broj="target", status_zaposlenja="AKTIVAN", status_naloga="OMOGUCEN",
        broj_telefona="060123456", lozinka_hash="stari-hash",
    )
    service, _repo, session_repo, push_repo, audit, sms, db = _service(korisnici=[actor, target])

    def _boom(phone, message):
        raise RuntimeError("SMS provider je pukao")

    sms.send_sms = _boom
    with pytest.raises(RuntimeError):
        service.reset_password(actor, 2)

    assert db.committed == 0
    assert db.rolled_back == 1
    assert target.lozinka_hash == "stari-hash"
    assert not any(
        e["sifra_akcije"] in (AuditAction.ADMIN_USER_PASSWORD_RESET, AuditAction.ADMIN_USER_PASSWORD_RESET_FAILED)
        for e in audit.entries
    )


# ==================================================================== ROLLBACK
def test_lock_rolls_back_on_audit_failure():
    actor = _actor()
    target = make_korisnik(id=2, platni_broj="target")
    service, repo, session_repo, push_repo, audit, _, db = _service(korisnici=[actor, target])

    def _boom(*a, **k):
        raise RuntimeError("audit pukao")

    audit.log = _boom
    with pytest.raises(RuntimeError):
        service.lock(actor, 2)
    assert db.committed == 0
    assert db.rolled_back == 1
    # Iako je izuzetak nastao POSLE mutacije objekta u memoriji, transakcija nije
    # commitovana - FakeDb ne vraca objekat, ali rollback je pozvan umesto commit-a.
