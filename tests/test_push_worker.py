"""Push worker: ishodi slanja. Ne kontaktira Firebase; token/tajne se ne loguju."""

import datetime

import pytest

from app.services.fcm_provider import (
    SEND_ERROR,
    SEND_INVALID_TOKEN,
    SEND_OK,
    SEND_TRANSIENT,
    FakeFcmProvider,
    FcmSendResult,
    NullFcmProvider,
    classify_fcm_exception,
    get_fcm_provider,
)
from app.services.push_service import FCM_MAX_TTL_SECONDS, PushDeliveryWorker
from tests.fakes import (
    FakeKorisnikRepository,
    FakePushTokenRepository,
    FakeSessionRepository,
    make_korisnik,
)
from tests.notification_fakes import (
    FakeNotifDb,
    FakeNotificationRepo,
    FakePushDeliveryRepo,
    make_kategorija,
    make_obavestenje,
    make_primalac,
)

FIXED_NOW = datetime.datetime(2026, 8, 19, 10, 0, 0)


def _active_session(korisnik_id=1, uredjaj_id="dev-1", datum_isteka=None):
    from types import SimpleNamespace

    return SimpleNamespace(
        korisnik_id=korisnik_id,
        uredjaj_id=uredjaj_id,
        aktivna="D",
        datum_isteka=datum_isteka if datum_isteka is not None else FIXED_NOW + datetime.timedelta(days=1),
    )


def _setup(
    fcm_result=None,
    user_active=True,
    user_locked=False,
    notif_available=True,
    with_token=True,
    with_session=True,
    max_attempts=5,
    datum_isteka=None,
):
    notif_repo = FakeNotificationRepo()
    notif_repo.add_category(make_kategorija())
    if notif_available:
        obav = notif_repo.seed_notification(
            make_obavestenje(
                naslov="Naslov", kratak_tekst="Kratak",
                datum_isteka=datum_isteka if datum_isteka is not None
                else FIXED_NOW + datetime.timedelta(days=29),
            )
        )
    else:
        obav = notif_repo.seed_notification(
            make_obavestenje(datum_isteka=FIXED_NOW - datetime.timedelta(days=1))
        )
    notif_repo.seed_recipient(make_primalac(obav.id, korisnik_id=1))

    push = FakePushDeliveryRepo()
    red = push.add_pending(obav.id, 1, FIXED_NOW)

    token_repo = FakePushTokenRepository()
    if with_token:
        token_repo.upsert(1, "dev-1", "tok-1", None)

    session_repo = FakeSessionRepository()
    if with_session:
        session_repo.sesije.append(_active_session())

    user = make_korisnik(
        id=1,
        status_zaposlenja="AKTIVAN" if user_active else "NEAKTIVAN",
        status_naloga="OMOGUCEN",
        zakljucan="D" if user_locked else "N",
    )
    korisnik_repo = FakeKorisnikRepository([user])

    fcm = FakeFcmProvider(result=fcm_result or FcmSendResult(status=SEND_OK))
    worker = PushDeliveryWorker(
        db=FakeNotifDb(),
        fcm_provider=fcm,
        max_attempts=max_attempts,
        delivery_repository=push,
        token_repository=token_repo,
        notification_repository=notif_repo,
        korisnik_repository=korisnik_repo,
        session_repository=session_repo,
        now_fn=lambda: FIXED_NOW,
    )
    return worker, push, token_repo, fcm, red


def test_success_marks_sent_and_safe_payload():
    worker, push, _, fcm, red = _setup(FcmSendResult(status=SEND_OK))
    worker.process_batch(10)
    assert red.status == "SENT" and red.datum_slanja == FIXED_NOW
    # payload: samo dozvoljena polja, sve stringovi, bez tokena
    sent = fcm.sent[0]["data"]
    assert set(sent.keys()) == {
        "notification_id", "title", "body", "category", "akcija_tip", "resurs_id", "akcija_url",
    }
    assert all(isinstance(v, str) for v in sent.values())
    assert "tok-1" not in str(fcm.sent)


def test_transient_error_retries():
    worker, push, _, _, red = _setup(FcmSendResult(status=SEND_TRANSIENT, error_code="UNAVAILABLE"))
    worker.process_batch(10)
    assert red.status == "PENDING"
    assert red.broj_pokusaja == 1
    assert red.datum_sledeceg_pokusaja > FIXED_NOW


def test_invalid_token_deactivates_token():
    worker, push, token_repo, _, red = _setup(
        FcmSendResult(status=SEND_INVALID_TOKEN, error_code="UNREGISTERED")
    )
    worker.process_batch(10)
    assert token_repo.tokens[(1, "dev-1")]["aktivan"] == "N"
    # isporuka ostaje PENDING (moze posle re-registracije)
    assert red.status == "PENDING"


def test_max_attempts_marks_failed():
    worker, push, _, _, red = _setup(FcmSendResult(status=SEND_ERROR, error_code="X"), max_attempts=3)
    red.broj_pokusaja = 2  # sledeci pokusaj je 3. = max
    worker.process_batch(10)
    assert red.status == "FAILED"


def test_expired_notification_skipped_no_send():
    worker, push, _, fcm, red = _setup(notif_available=False)
    worker.process_batch(10)
    assert red.status == "SKIPPED"
    assert fcm.sent == []  # FCM nije pozvan


def test_inactive_user_skipped():
    worker, push, _, fcm, red = _setup(user_active=False)
    worker.process_batch(10)
    assert red.status == "SKIPPED"
    assert fcm.sent == []


def test_no_token_stays_pending_without_attempt():
    worker, push, _, fcm, red = _setup(with_token=False)
    worker.process_batch(10)
    assert red.status == "PENDING"
    assert red.broj_pokusaja == 0  # nema trosenja pokusaja
    assert fcm.sent == []


def test_one_bad_row_does_not_stop_batch():
    worker, push, token_repo, fcm, red1 = _setup(FcmSendResult(status=SEND_OK))
    # Dodaj drugi red za istog primaoca drugog obavestenja koji ce baciti izuzetak.
    push.add_pending(9999, 1, FIXED_NOW)  # obavestenje 9999 ne postoji

    orig = worker.notif_repo.get_available_notification

    def flaky(nid, now):
        if nid == 9999:
            raise RuntimeError("neocekivano")
        return orig(nid, now)

    worker.notif_repo.get_available_notification = flaky
    summary = worker.process_batch(10)
    # Prvi red obradjen (SENT), drugi je pao ali nije zaustavio batch.
    assert red1.status == "SENT"
    assert summary["processed"] == 1


def test_null_provider_when_fcm_disabled():
    class S:
        fcm_enabled = False
        fcm_credentials_file = ""

    provider = get_fcm_provider(S())
    assert isinstance(provider, NullFcmProvider)
    # Poziv na Null provider je greska (worker ne salje kad je FCM off).
    with pytest.raises(RuntimeError):
        provider.send("t", {}, 60)


# ------------------------------------------------------------------ item 4: sesija uredjaja
def test_locked_user_does_not_get_push():
    worker, push, _, fcm, red = _setup(user_locked=True)
    worker.process_batch(10)
    assert red.status == "SKIPPED"
    assert fcm.sent == []


def test_missing_device_session_skips_and_deactivates_token():
    worker, push, token_repo, fcm, red = _setup(with_session=False)
    worker.process_batch(10)
    assert fcm.sent == []
    assert red.status == "PENDING"
    assert red.poslednji_error_code == "NO_ACTIVE_SESSION"
    assert token_repo.tokens[(1, "dev-1")]["aktivan"] == "N"
    assert red.broj_pokusaja == 0  # bez trosenja pokusaja


def test_expired_device_session_skips_and_deactivates_token():
    worker, push, token_repo, fcm, red = _setup(with_session=False)
    worker.session_repo.sesije.append(
        _active_session(datum_isteka=FIXED_NOW - datetime.timedelta(minutes=1))
    )
    worker.process_batch(10)
    assert fcm.sent == []
    assert token_repo.tokens[(1, "dev-1")]["aktivan"] == "N"
    assert red.status == "PENDING"


def test_valid_session_allows_send():
    worker, push, _, fcm, red = _setup(with_session=True)
    worker.process_batch(10)
    assert red.status == "SENT"
    assert len(fcm.sent) == 1


# ------------------------------------------------------------------ item 2: FCM TTL cap
def test_ttl_capped_at_28_days_for_30_day_expiry():
    worker, push, _, fcm, red = _setup(datum_isteka=FIXED_NOW + datetime.timedelta(days=30))
    worker.process_batch(10)
    assert red.status == "SENT"
    assert fcm.sent[0]["ttl"] == str(FCM_MAX_TTL_SECONDS)
    assert FCM_MAX_TTL_SECONDS == 28 * 24 * 60 * 60


def test_ttl_not_capped_when_remaining_below_max():
    worker, push, _, fcm, red = _setup(datum_isteka=FIXED_NOW + datetime.timedelta(days=1))
    worker.process_batch(10)
    assert red.status == "SENT"
    assert fcm.sent[0]["ttl"] == str(24 * 60 * 60)


# ------------------------------------------------------------------ item 3: ValueError klasifikacija
def test_value_error_is_not_invalid_token():
    result = classify_fcm_exception(ValueError("malformed data payload"))
    assert result.status == SEND_ERROR
    assert result.status != SEND_INVALID_TOKEN
    assert result.error_code == "INVALID_MESSAGE"


def test_worker_does_not_deactivate_token_on_value_error_result():
    # ValueError se klasifikuje kao SEND_ERROR (ne INVALID_TOKEN); worker na SEND_ERROR
    # ne sme deaktivirati token - samo retry/backoff.
    worker, push, token_repo, _, red = _setup(
        FcmSendResult(status=SEND_ERROR, error_code="INVALID_MESSAGE")
    )
    worker.process_batch(10)
    assert token_repo.tokens[(1, "dev-1")]["aktivan"] == "D"  # token NIJE deaktiviran
    assert red.status == "PENDING"
    assert red.broj_pokusaja == 1


def test_unregistered_is_invalid_token():
    result = classify_fcm_exception(type("UnregisteredError", (Exception,), {})())
    assert result.status == SEND_INVALID_TOKEN


def test_unavailable_is_transient():
    result = classify_fcm_exception(type("UnavailableError", (Exception,), {})())
    assert result.status == SEND_TRANSIENT


# ------------------------------------------------------------------ item 7: bezbedan exception handler
class _ExpiringRow:
    """Simulira SQLAlchemy ORM instancu koja se ekspajruje posle Session.rollback():
    citanje atributa PRE ekspajra je normalno, ali POSLE njega baca izuzetak (kao
    sto bi realan re-fetch iz baze mogao da padne/prekine ceo batch)."""

    def __init__(self, expired_flag: list, **data):
        object.__setattr__(self, "_expired_flag", expired_flag)
        object.__setattr__(self, "_data", data)

    def __getattr__(self, name):
        if object.__getattribute__(self, "_expired_flag")[0]:
            raise RuntimeError(f"'{name}' pristupljeno posle rollback-a (expired)")
        data = object.__getattribute__(self, "_data")
        if name in data:
            return data[name]
        raise AttributeError(name)

    def __setattr__(self, name, value):
        object.__getattribute__(self, "_data")[name] = value


class _ExpiringDb:
    def __init__(self, expired_flag: list):
        self._expired_flag = expired_flag
        self.committed = 0
        self.rolled_back = 0

    def commit(self):
        self.committed += 1

    def rollback(self):
        self.rolled_back += 1
        self._expired_flag[0] = True


def test_process_batch_does_not_access_expired_row_attrs_after_rollback():
    expired_flag = [False]
    bad_row = _ExpiringRow(
        expired_flag, id=1, obavestenje_id=999, korisnik_id=1, status="PENDING",
        broj_pokusaja=0, datum_sledeceg_pokusaja=FIXED_NOW, poslednji_error_code=None,
        datum_slanja=None, datum_poslednjeg_pokusaja=None, broj_ponovnih_slanja=0,
    )

    notif_repo = FakeNotificationRepo()
    notif_repo.add_category(make_kategorija())
    good_obav = notif_repo.seed_notification(
        make_obavestenje(datum_isteka=FIXED_NOW + datetime.timedelta(days=1))
    )
    notif_repo.seed_recipient(make_primalac(good_obav.id, korisnik_id=2))

    push = FakePushDeliveryRepo()
    good_row = push.add_pending(good_obav.id, 2, FIXED_NOW)
    push.rows = [bad_row, good_row]  # bad_row prvi -> pada, good_row mora ipak biti obradjen
    push.claim_ready_batch = lambda now, limit: [bad_row, good_row]

    token_repo = FakePushTokenRepository()
    token_repo.upsert(2, "dev-2", "tok-2", None)
    session_repo = FakeSessionRepository()
    session_repo.sesije.append(_active_session(korisnik_id=2, uredjaj_id="dev-2"))
    korisnik_repo = FakeKorisnikRepository([make_korisnik(id=2, status_zaposlenja="AKTIVAN", status_naloga="OMOGUCEN")])

    orig_get_available = notif_repo.get_available_notification

    def boom_for_bad_row(nid, now):
        if nid == 999:
            raise RuntimeError("neocekivano - obavestenje ne postoji")
        return orig_get_available(nid, now)

    worker = PushDeliveryWorker(
        db=_ExpiringDb(expired_flag),
        fcm_provider=FakeFcmProvider(FcmSendResult(status=SEND_OK)),
        max_attempts=5,
        delivery_repository=push,
        token_repository=token_repo,
        notification_repository=notif_repo,
        korisnik_repository=korisnik_repo,
        session_repository=session_repo,
        now_fn=lambda: FIXED_NOW,
    )
    worker.notif_repo.get_available_notification = boom_for_bad_row

    # Ako kod pristupa bad_row.id/obavestenje_id POSLE rollback-a (umesto sacuvanih
    # promenljivih), _ExpiringRow ce baciti RuntimeError koji NIJE uhvacen (jer je
    # vec unutar except bloka) i process_batch bi propagirao izuzetak, prekidajuci
    # obradu good_row-a. Ako fix radi, process_batch se normalno zavrsava.
    summary = worker.process_batch(10)
    assert summary["processed"] == 1  # samo good_row uspesno obradjen
    assert good_row.status == "SENT"
