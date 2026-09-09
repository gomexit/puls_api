"""Servisni testovi za SystemNotificationService (fake repozitorijumi, bez DB)."""

import datetime

from types import SimpleNamespace

from app.models.sistemski_dogadjaj import DOGADJAJ_TIP_ONBOARDING_SURVEY_AVAILABLE
from app.services.notification_publishing_service import NotificationPublishingService
from app.services.system_notification_service import SystemNotificationService
from tests.fakes import FakeAuditService
from tests.notification_fakes import (
    FakeConfigService,
    FakeNotifDb,
    FakeNotificationRepo,
    FakeNotificationTargetingRepo,
    FakePushDeliveryRepo,
    make_kategorija,
)
from tests.system_notification_fakes import (
    FakeAutomationRepo,
    FakeOnboardingAssignmentService,
    FakeSystemEventRepo,
    make_anketa,
    make_ciklus,
    make_ideja,
    make_korisnik,
)

FIXED_NOW = datetime.datetime(2026, 8, 18, 10, 0, 0)


def _service(
    all_active_ids=None, max_attempts=5, config_values=None, now=FIXED_NOW, automation_repo=None
):
    event_repo = FakeSystemEventRepo()
    notif_repo = FakeNotificationRepo()
    notif_repo.add_category(make_kategorija(sifra="SISTEM", naziv="Sistemsko"))
    targeting = FakeNotificationTargetingRepo(all_ids=all_active_ids or set())
    push = FakePushDeliveryRepo()
    config = FakeConfigService(config_values)
    publishing = NotificationPublishingService(
        db=FakeNotifDb(),
        repository=notif_repo,
        targeting_repository=targeting,
        audit_service=FakeAuditService(),
        configuration_service=config,
        push_delivery_repository=push,
        now_fn=lambda: now,
    )
    db = FakeNotifDb()
    service = SystemNotificationService(
        db=db,
        event_repository=event_repo,
        targeting_repository=targeting,
        publishing_service=publishing,
        configuration_service=config,
        onboarding_assignment_service=FakeOnboardingAssignmentService(),
        automation_repository=automation_repo or FakeAutomationRepo(),
        max_attempts=max_attempts,
        now_fn=lambda: now,
    )
    return service, event_repo, notif_repo, push, targeting, db


# ============================================================= enqueue idempotencija
def test_enqueue_survey_activated_is_idempotent():
    service, event_repo, *_ = _service()
    assert service.enqueue_survey_activated(1) is True
    assert service.enqueue_survey_activated(1) is False
    assert len(event_repo.events) == 1


def test_enqueue_app_version_changed_idempotent():
    service, event_repo, *_ = _service()
    assert service.enqueue_app_version_changed("1.5") is True
    assert service.enqueue_app_version_changed("1.5") is False
    assert len(event_repo.events) == 1


def test_process_batch_no_duplicate_notification_for_same_event():
    """Dvaput obradjen (vec PROCESSED) dogadjaj se preskace - nema drugog obavestenja."""
    service, event_repo, notif_repo, *_ = _service(all_active_ids={1, 2})
    ciklus = make_ciklus(status="AKTIVAN")
    event_repo.seed_cycle(ciklus)
    service.enqueue_idea_cycle_activated(ciklus.id)
    summary1 = service.process_batch(10)
    assert summary1["published"] == 1
    assert len(notif_repo.notifications) == 1

    # Isti dogadjaj vise nije PENDING -> process_batch ga vise ne bira uopste.
    summary2 = service.process_batch(10)
    assert summary2["processed"] == 0
    assert len(notif_repo.notifications) == 1


# ============================================================= SURVEY_EXPIRING
def test_survey_expiring_filters_out_submitted_users():
    service, event_repo, notif_repo, push, *_ = _service()
    anketa = make_anketa(status="ACTIVE")
    event_repo.seed_survey(anketa, participants=[(1, "SUBMITTED"), (2, "NOT_STARTED"), (3, "IN_PROGRESS")])
    service.enqueue_survey_expiring(anketa.id, anketa.datum_zavrsetka)

    summary = service.process_batch(10)
    assert summary["published"] == 1
    obav = next(iter(notif_repo.notifications.values()))
    assert notif_repo.existing_recipient_ids(obav.id) == {2, 3}
    assert push.existing_user_ids(obav.id) == {2, 3}


def test_survey_activated_sends_to_all_participants_incl_submitted():
    service, event_repo, notif_repo, *_ = _service()
    anketa = make_anketa(status="ACTIVE")
    event_repo.seed_survey(anketa, participants=[(1, "SUBMITTED"), (2, "NOT_STARTED")])
    service.enqueue_survey_activated(anketa.id)

    service.process_batch(10)
    obav = next(iter(notif_repo.notifications.values()))
    assert notif_repo.existing_recipient_ids(obav.id) == {1, 2}
    assert obav.akcija_tip == "SURVEY"
    assert obav.resurs_id == anketa.id
    assert obav.datum_isteka == anketa.datum_zavrsetka


# ========================================================= IDEA_CYCLE_EXPIRING
def test_idea_cycle_expiring_only_users_without_idea():
    service, event_repo, notif_repo, *_ = _service(all_active_ids={1, 2, 3})
    ciklus = make_ciklus(status="AKTIVAN")
    event_repo.seed_cycle(ciklus, idea_authors={1})
    service.enqueue_idea_cycle_expiring(ciklus.id, ciklus.datum_zavrsetka)

    service.process_batch(10)
    obav = next(iter(notif_repo.notifications.values()))
    assert notif_repo.existing_recipient_ids(obav.id) == {2, 3}
    assert obav.akcija_tip == "IDEA_CYCLE"
    assert obav.resurs_id == ciklus.id


def test_idea_cycle_activated_sends_to_all_active():
    service, event_repo, notif_repo, *_ = _service(all_active_ids={1, 2, 3})
    ciklus = make_ciklus(status="AKTIVAN")
    event_repo.seed_cycle(ciklus, idea_authors={1})
    service.enqueue_idea_cycle_activated(ciklus.id)

    service.process_batch(10)
    obav = next(iter(notif_repo.notifications.values()))
    assert notif_repo.existing_recipient_ids(obav.id) == {1, 2, 3}


# ==================================================================== 24h granica
def test_discover_events_survey_expiring_within_24h_included():
    service, event_repo, *_ = _service(now=FIXED_NOW)
    anketa = make_anketa(
        status="ACTIVE",
        datum_pocetka=FIXED_NOW - datetime.timedelta(days=1),
        datum_zavrsetka=FIXED_NOW + datetime.timedelta(hours=23),
    )
    event_repo.seed_survey(anketa)
    result = service.discover_events()
    assert result["discovered"] == 1
    assert len(event_repo.events) == 1


def test_discover_events_survey_expiring_beyond_24h_excluded():
    service, event_repo, *_ = _service(now=FIXED_NOW)
    anketa = make_anketa(
        status="ACTIVE",
        datum_pocetka=FIXED_NOW - datetime.timedelta(days=1),
        datum_zavrsetka=FIXED_NOW + datetime.timedelta(hours=25),
    )
    event_repo.seed_survey(anketa)
    result = service.discover_events()
    assert result["discovered"] == 0
    assert len(event_repo.events) == 0


# ============================================================= produzen rok
def test_extended_deadline_produces_new_reminder_key():
    service, event_repo, *_ = _service()
    d1 = datetime.datetime(2026, 3, 1, 10, 0, 0)
    d2 = datetime.datetime(2026, 3, 5, 10, 0, 0)
    assert service.enqueue_survey_expiring(1, d1) is True
    assert service.enqueue_survey_expiring(1, d1) is False  # isti rok -> isti kljuc
    assert service.enqueue_survey_expiring(1, d2) is True  # produzen rok -> nov kljuc
    assert len(event_repo.events) == 2


# ==================================================== SCHEDULED anketa -> aktivacija
def test_scheduled_survey_gets_activation_event_on_discovery():
    service, event_repo, *_ = _service(now=FIXED_NOW)
    anketa = make_anketa(
        status="SCHEDULED",
        datum_pocetka=FIXED_NOW - datetime.timedelta(hours=1),
        datum_zavrsetka=FIXED_NOW + datetime.timedelta(days=5),
    )
    event_repo.seed_survey(anketa)
    result = service.discover_events()
    assert result["discovered"] == 1
    event = next(iter(event_repo.events.values()))
    assert event.tip_dogadjaja == "SURVEY_ACTIVATED"
    assert event.resurs_id == anketa.id
    assert anketa.status == "ACTIVE"


def test_active_survey_past_deadline_closed_on_discovery():
    service, event_repo, *_ = _service(now=FIXED_NOW)
    anketa = make_anketa(
        status="ACTIVE",
        datum_pocetka=FIXED_NOW - datetime.timedelta(days=5),
        datum_zavrsetka=FIXED_NOW - datetime.timedelta(minutes=1),
    )
    event_repo.seed_survey(anketa)
    service.discover_events()
    assert anketa.status == "CLOSED"


def test_active_survey_still_within_period_not_closed():
    service, event_repo, *_ = _service(now=FIXED_NOW)
    anketa = make_anketa(
        status="ACTIVE",
        datum_pocetka=FIXED_NOW - datetime.timedelta(days=1),
        datum_zavrsetka=FIXED_NOW + datetime.timedelta(days=1),
    )
    event_repo.seed_survey(anketa)
    service.discover_events()
    assert anketa.status == "ACTIVE"


def test_not_yet_started_scheduled_survey_not_discovered():
    service, event_repo, *_ = _service(now=FIXED_NOW)
    anketa = make_anketa(
        status="SCHEDULED",
        datum_pocetka=FIXED_NOW + datetime.timedelta(hours=1),
        datum_zavrsetka=FIXED_NOW + datetime.timedelta(days=5),
    )
    event_repo.seed_survey(anketa)
    result = service.discover_events()
    assert result["discovered"] == 0


# ============================================== automatska (onboarding) anketa - discovery
def test_automatska_anketa_scheduled_to_active_status_changes_but_no_global_event():
    """Status prelaz SCHEDULED->ACTIVE se i dalje desava za automatsku anketu, ali
    SURVEY_ACTIVATED se NE enqueue-uje globalno (korisnici se obavestavaju iskljucivo
    kroz ONBOARDING_SURVEY_AVAILABLE po korisniku)."""
    automation_repo = FakeAutomationRepo()
    service, event_repo, *_ = _service(now=FIXED_NOW, automation_repo=automation_repo)
    anketa = make_anketa(
        status="SCHEDULED",
        datum_pocetka=FIXED_NOW - datetime.timedelta(hours=1),
        datum_zavrsetka=FIXED_NOW + datetime.timedelta(days=5),
    )
    event_repo.seed_survey(anketa)
    automation_repo.mark_automatska(anketa.id)

    result = service.discover_events()

    assert anketa.status == "ACTIVE"
    assert result["discovered"] == 0
    assert len(event_repo.events) == 0


def test_automatska_anketa_expiring_within_24h_gets_no_global_reminder():
    """Automatska anketa nema jedinstven globalni rok - svaki korisnik ima svoj
    individualni DATUM_ISTEKA na ucescu - zato SURVEY_EXPIRING se ne salje globalno."""
    automation_repo = FakeAutomationRepo()
    service, event_repo, *_ = _service(now=FIXED_NOW, automation_repo=automation_repo)
    anketa = make_anketa(
        status="ACTIVE",
        datum_pocetka=FIXED_NOW - datetime.timedelta(days=1),
        datum_zavrsetka=FIXED_NOW + datetime.timedelta(hours=23),
    )
    event_repo.seed_survey(anketa)
    automation_repo.mark_automatska(anketa.id)

    result = service.discover_events()

    assert result["discovered"] == 0
    assert len(event_repo.events) == 0


def test_discover_events_reports_onboarding_assigned_separately():
    """discovered i onboarding_assigned su odvojena polja - onboarding_assigned NE sme
    uticati na znacenje discovered (SCHEDULED/EXPIRING dogadjaji)."""

    class _StubAssignment:
        def assign_due_surveys(self, now):
            return {"assigned": 4}

    service, event_repo, *_ = _service(now=FIXED_NOW)
    service.onboarding_assignment = _StubAssignment()

    result = service.discover_events()

    assert result["onboarding_assigned"] == 4
    assert result["discovered"] == 0


# ==================================================================== TOP_10 / NAGRAĐENA
def test_idea_top10_sent_only_to_author():
    service, event_repo, notif_repo, *_ = _service()
    ideja = make_ideja(korisnik_id=42, status="TOP_10")
    event_repo.seed_idea(ideja)
    service.enqueue_idea_top_10(ideja.id)

    service.process_batch(10)
    obav = next(iter(notif_repo.notifications.values()))
    assert notif_repo.existing_recipient_ids(obav.id) == {42}
    assert obav.akcija_tip == "IDEA"
    assert obav.resurs_id == ideja.id


def test_idea_nagradjena_sent_only_to_author():
    service, event_repo, notif_repo, *_ = _service()
    ideja = make_ideja(korisnik_id=7, status="NAGRAĐENA")
    event_repo.seed_idea(ideja)
    service.enqueue_idea_nagradjena(ideja.id)

    service.process_batch(10)
    obav = next(iter(notif_repo.notifications.values()))
    assert notif_repo.existing_recipient_ids(obav.id) == {7}


def test_idea_top10_published_even_if_idea_already_nagradjena():
    """IDEA_TOP_10 je istorijski dogadjaj stvarnog prelaska - salje se i ako je ideja
    u medjuvremenu vec presla u NAGRADJENA (oba obavestenja moraju stici korisniku
    i kad oba prelaza nastupe pre sledeceg worker intervala)."""
    service, event_repo, notif_repo, *_ = _service()
    ideja = make_ideja(korisnik_id=7, status="NAGRAĐENA")
    event_repo.seed_idea(ideja)
    service.enqueue_idea_top_10(ideja.id)

    summary = service.process_batch(10)
    assert summary["published"] == 1
    obav = next(iter(notif_repo.notifications.values()))
    assert notif_repo.existing_recipient_ids(obav.id) == {7}


def test_idea_top10_skipped_if_idea_rejected_after():
    """TOP_10 dogadjaj se preskace ako status VISE NIJE ni TOP_10 ni NAGRADJENA."""
    service, event_repo, notif_repo, *_ = _service()
    ideja = make_ideja(korisnik_id=7, status="ODBIJENA")
    event_repo.seed_idea(ideja)
    service.enqueue_idea_top_10(ideja.id)

    summary = service.process_batch(10)
    assert summary["skipped"] == 1
    assert len(notif_repo.notifications) == 0


def test_idea_nagradjena_skipped_if_status_moved_on():
    """NAGRADJENA dogadjaj SAMO za status NAGRADJENA - TOP_10 nije dovoljno."""
    service, event_repo, notif_repo, *_ = _service()
    ideja = make_ideja(korisnik_id=7, status="TOP_10")
    event_repo.seed_idea(ideja)
    service.enqueue_idea_nagradjena(ideja.id)

    summary = service.process_batch(10)
    assert summary["skipped"] == 1
    assert len(notif_repo.notifications) == 0


def test_idea_status_event_skipped_if_idea_missing():
    service, event_repo, notif_repo, *_ = _service()
    service.event_repo.enqueue_if_absent("IDEA_TOP_10:999", "IDEA_TOP_10", 999, None, FIXED_NOW)
    summary = service.process_batch(10)
    assert summary["skipped"] == 1
    assert len(notif_repo.notifications) == 0


# ==================================================================== APP_VERSION_CHANGED
def test_app_version_changed_sent_to_all_active_users():
    service, event_repo, notif_repo, *_ = _service(
        all_active_ids={1, 2}, config_values={"CURRENT_VERSION": "2.0"}
    )
    service.enqueue_app_version_changed("2.0")
    service.process_batch(10)
    obav = next(iter(notif_repo.notifications.values()))
    assert notif_repo.existing_recipient_ids(obav.id) == {1, 2}


def test_app_version_changed_uses_url_action_when_download_url_valid():
    service, event_repo, notif_repo, *_ = _service(
        all_active_ids={1},
        config_values={"CURRENT_VERSION": "2.0", "DOWNLOAD_URL": "https://cdn.example.com/app.apk"},
    )
    service.enqueue_app_version_changed("2.0")
    service.process_batch(10)
    obav = next(iter(notif_repo.notifications.values()))
    assert obav.akcija_tip == "URL"
    assert obav.akcija_url == "https://cdn.example.com/app.apk"


def test_app_version_changed_none_action_when_no_download_url():
    service, event_repo, notif_repo, *_ = _service(
        all_active_ids={1}, config_values={"CURRENT_VERSION": "2.0"}
    )
    service.enqueue_app_version_changed("2.0")
    service.process_batch(10)
    obav = next(iter(notif_repo.notifications.values()))
    assert obav.akcija_tip == "NONE"
    assert obav.akcija_url is None


def test_app_version_changed_invalid_download_url_falls_back_to_none():
    service, event_repo, notif_repo, *_ = _service(
        all_active_ids={1},
        config_values={"CURRENT_VERSION": "2.0", "DOWNLOAD_URL": "http://not-https.example.com"},
    )
    service.enqueue_app_version_changed("2.0")
    service.process_batch(10)
    obav = next(iter(notif_repo.notifications.values()))
    assert obav.akcija_tip == "NONE"
    assert obav.akcija_url is None


def test_app_version_changed_stale_event_for_previous_version_skipped():
    """Stari dogadjaj za PRETHODNU verziju (CURRENT_VERSION je otad promenjena opet) -
    SKIPPED, ne objavljuje se sa zastarelom verzijom u sadrzaju."""
    service, event_repo, notif_repo, *_ = _service(
        all_active_ids={1}, config_values={"CURRENT_VERSION": "3.0"}
    )
    service.enqueue_app_version_changed("2.0")  # zastareo dogadjaj
    summary = service.process_batch(10)
    assert summary["skipped"] == 1
    assert len(notif_repo.notifications) == 0


def test_app_version_changed_current_version_published_after_stale_skip():
    service, event_repo, notif_repo, *_ = _service(
        all_active_ids={1}, config_values={"CURRENT_VERSION": "3.0"}
    )
    service.enqueue_app_version_changed("2.0")  # stari, bice SKIPPED
    service.enqueue_app_version_changed("3.0")  # trenutna verzija, bice objavljen
    summary = service.process_batch(10)
    assert summary["skipped"] == 1
    assert summary["published"] == 1
    assert len(notif_repo.notifications) == 1
    obav = next(iter(notif_repo.notifications.values()))
    assert "3.0" in obav.sadrzaj


# ==================================================================== nema primalaca
def test_no_recipients_marks_event_skipped_without_notification():
    service, event_repo, notif_repo, *_ = _service(all_active_ids=set())
    ciklus = make_ciklus(status="AKTIVAN")
    event_repo.seed_cycle(ciklus)
    service.enqueue_idea_cycle_activated(ciklus.id)

    summary = service.process_batch(10)
    assert summary["skipped"] == 1
    assert len(notif_repo.notifications) == 0
    event = next(iter(event_repo.events.values()))
    assert event.status == "SKIPPED"
    assert event.obavestenje_id is None


def test_missing_resource_marks_event_skipped():
    service, event_repo, notif_repo, *_ = _service()
    service.event_repo.enqueue_if_absent(
        "SURVEY_ACTIVATED:999", "SURVEY_ACTIVATED", 999, None, FIXED_NOW
    )
    summary = service.process_batch(10)
    assert summary["skipped"] == 1
    assert len(notif_repo.notifications) == 0


# ==================================================================== rollback/retry
def test_process_one_failure_never_calls_commit_and_leaves_no_notification():
    """Ako obrada padne (npr. neocekivan izuzetak u resolveru), transakcija se NIKAD
    ne commituje (Oracle rollback semantika) - nema parcijalnog obavestenja jer
    apply_publish_system uopste nije pozvan."""
    service, event_repo, notif_repo, *_ = _service(all_active_ids={1, 2})
    ciklus = make_ciklus(status="AKTIVAN")
    event_repo.seed_cycle(ciklus)
    service.enqueue_idea_cycle_activated(ciklus.id)

    def _boom(*a, **kw):
        raise RuntimeError("neocekivana greska")

    event_repo.get_cycle = _boom  # simulira gresku pri resolveru

    summary = service.process_batch(10)
    assert len(notif_repo.notifications) == 0
    assert summary["retry"] == 1
    event = next(iter(event_repo.events.values()))
    assert event.status == "PENDING"
    assert event.broj_pokusaja == 1
    assert event.poslednji_error_code == "RuntimeError"


def test_retry_backoff_then_failed_after_max_attempts():
    service, event_repo, notif_repo, *_ = _service(all_active_ids={1}, max_attempts=2)
    ciklus = make_ciklus(status="AKTIVAN")
    event_repo.seed_cycle(ciklus)
    service.enqueue_idea_cycle_activated(ciklus.id)

    def _boom(*a, **kw):
        raise RuntimeError("boom")

    event_repo.get_cycle = _boom

    summary1 = service.process_batch(10)
    assert summary1["retry"] == 1
    event = next(iter(event_repo.events.values()))
    assert event.status == "PENDING"
    assert event.broj_pokusaja == 1
    assert event.datum_sledeceg_pokusaja is not None

    # Drugi pokusaj - dostignut max_attempts=2 -> FAILED.
    event.datum_sledeceg_pokusaja = FIXED_NOW  # simulira da je backoff prosao
    summary2 = service.process_batch(10)
    assert summary2["failed"] == 1
    assert event.status == "FAILED"
    assert event.broj_pokusaja == 2
    assert event.datum_sledeceg_pokusaja is None


def test_error_code_never_contains_exception_message():
    """POSLEDNJI_ERROR_CODE je samo naziv tipa izuzetka - nikad puna poruka."""
    service, event_repo, notif_repo, *_ = _service(all_active_ids={1})
    ciklus = make_ciklus(status="AKTIVAN")
    event_repo.seed_cycle(ciklus)
    service.enqueue_idea_cycle_activated(ciklus.id)

    def _boom(*a, **kw):
        raise ValueError("tajna-vrednost-koja-ne-sme-u-log")

    event_repo.get_cycle = _boom
    service.process_batch(10)
    event = next(iter(event_repo.events.values()))
    assert event.poslednji_error_code == "ValueError"
    assert "tajna-vrednost" not in (event.poslednji_error_code or "")


# ==================================================================== ostali ugovori
def test_survey_activated_uses_survey_expiry_as_notification_expiry():
    service, event_repo, notif_repo, *_ = _service()
    anketa = make_anketa(status="ACTIVE", datum_zavrsetka=FIXED_NOW + datetime.timedelta(days=3))
    event_repo.seed_survey(anketa, participants=[(1, "NOT_STARTED")])
    service.enqueue_survey_activated(anketa.id)
    service.process_batch(10)
    obav = next(iter(notif_repo.notifications.values()))
    assert obav.datum_isteka == anketa.datum_zavrsetka


def test_idea_top10_uses_default_expiry_days():
    service, event_repo, notif_repo, *_ = _service(config_values={"NOTIFICATION_DEFAULT_EXPIRY_DAYS": "7"})
    ideja = make_ideja(korisnik_id=1, status="TOP_10")
    event_repo.seed_idea(ideja)
    service.enqueue_idea_top_10(ideja.id)
    service.process_batch(10)
    obav = next(iter(notif_repo.notifications.values()))
    assert obav.datum_isteka == FIXED_NOW + datetime.timedelta(days=7)


# ==================================================== minimalne korekcije (rubni slucajevi)
def test_extended_deadline_old_reminder_skipped_new_one_published():
    """Produzen rok: stari SURVEY_EXPIRING dogadjaj (za stari rok) je SKIPPED, novi
    (za produzeni rok) se moze objaviti."""
    service, event_repo, notif_repo, *_ = _service()
    anketa = make_anketa(status="ACTIVE", datum_zavrsetka=FIXED_NOW + datetime.timedelta(hours=5))
    event_repo.seed_survey(anketa, participants=[(1, "NOT_STARTED")])
    old_deadline = FIXED_NOW - datetime.timedelta(hours=1)  # stari (vec neaktuelan) rok
    service.enqueue_survey_expiring(anketa.id, old_deadline)  # stari kljuc/dogadjaj
    service.enqueue_survey_expiring(anketa.id, anketa.datum_zavrsetka)  # novi (produzeni) rok

    summary = service.process_batch(10)
    assert summary["skipped"] == 1
    assert summary["published"] == 1
    assert len(notif_repo.notifications) == 1


def test_closed_survey_activation_skipped():
    service, event_repo, notif_repo, *_ = _service()
    anketa = make_anketa(status="CLOSED")
    event_repo.seed_survey(anketa, participants=[(1, "NOT_STARTED")])
    service.enqueue_survey_activated(anketa.id)

    summary = service.process_batch(10)
    assert summary["skipped"] == 1
    assert len(notif_repo.notifications) == 0


def test_expired_survey_reminder_skipped():
    service, event_repo, notif_repo, *_ = _service()
    anketa = make_anketa(
        status="ACTIVE",
        datum_pocetka=FIXED_NOW - datetime.timedelta(days=10),
        datum_zavrsetka=FIXED_NOW - datetime.timedelta(hours=1),  # vec isteklo
    )
    event_repo.seed_survey(anketa, participants=[(1, "NOT_STARTED")])
    service.enqueue_survey_expiring(anketa.id, anketa.datum_zavrsetka)

    summary = service.process_batch(10)
    assert summary["skipped"] == 1
    assert len(notif_repo.notifications) == 0


def test_closed_idea_cycle_activation_skipped():
    service, event_repo, notif_repo, *_ = _service(all_active_ids={1})
    ciklus = make_ciklus(status="ZATVOREN")
    event_repo.seed_cycle(ciklus)
    service.enqueue_idea_cycle_activated(ciklus.id)

    summary = service.process_batch(10)
    assert summary["skipped"] == 1
    assert len(notif_repo.notifications) == 0


def test_expired_idea_cycle_reminder_skipped():
    service, event_repo, notif_repo, *_ = _service(all_active_ids={1, 2})
    ciklus = make_ciklus(
        status="AKTIVAN",
        datum_pocetka=FIXED_NOW - datetime.timedelta(days=10),
        datum_zavrsetka=FIXED_NOW - datetime.timedelta(hours=1),  # vec isteklo
    )
    event_repo.seed_cycle(ciklus)
    service.enqueue_idea_cycle_expiring(ciklus.id, ciklus.datum_zavrsetka)

    summary = service.process_batch(10)
    assert summary["skipped"] == 1
    assert len(notif_repo.notifications) == 0


def test_datum_isteka_le_now_never_causes_retry_or_failed():
    """Zavrsna zastita: ako je efektivni datum_isteka <= now, dogadjaj je SKIPPED,
    NIKAD retry/FAILED (nije greska obrade)."""
    service, event_repo, notif_repo, *_ = _service(all_active_ids={1})
    ciklus = make_ciklus(status="AKTIVAN")
    event_repo.seed_cycle(ciklus)
    service.enqueue_idea_cycle_activated(ciklus.id)

    original_resolve = service._resolve

    def _resolve_with_past_expiry(event, now):
        recipients, content = original_resolve(event, now)
        if content is not None:
            content = dict(content, datum_isteka=now - datetime.timedelta(minutes=1))
        return recipients, content

    service._resolve = _resolve_with_past_expiry

    summary = service.process_batch(10)
    assert summary["skipped"] == 1
    assert summary["retry"] == 0
    assert summary["failed"] == 0
    assert len(notif_repo.notifications) == 0
    event = next(iter(event_repo.events.values()))
    assert event.status == "SKIPPED"
    assert event.broj_pokusaja == 0


# ============================================================= ONBOARDING_SURVEY_AVAILABLE
def _make_ucesce(**ov):
    defaults = dict(
        id=1,
        anketa_id=100,
        korisnik_id=7,
        status="NOT_STARTED",
        automatika_id=1,
        datum_dostupnosti=FIXED_NOW - datetime.timedelta(days=1),
        datum_isteka=FIXED_NOW + datetime.timedelta(days=6),
    )
    defaults.update(ov)
    return SimpleNamespace(**defaults)


def _seed_onboarding_happy_path(event_repo, ucesce):
    """Seeduje anketu (ACTIVE/ne-anonimna) i korisnika (AKTIVAN/OMOGUCEN) tako da
    SVE fail-closed provere u _resolve_onboarding_survey_available prodju."""
    event_repo.seed_survey(make_anketa(id=ucesce.anketa_id, status="ACTIVE", anonimna="N"))
    event_repo.seed_korisnik(
        make_korisnik(id=ucesce.korisnik_id, status_zaposlenja="AKTIVAN", status_naloga="OMOGUCEN")
    )


def test_onboarding_survey_available_sent_only_to_that_user():
    service, event_repo, notif_repo, *_ = _service()
    ucesce = _make_ucesce()
    event_repo.seed_ucesce(ucesce)
    _seed_onboarding_happy_path(event_repo, ucesce)
    event_repo.enqueue_if_absent(
        f"ONBOARDING_SURVEY_AVAILABLE:{ucesce.anketa_id}:{ucesce.korisnik_id}:x",
        DOGADJAJ_TIP_ONBOARDING_SURVEY_AVAILABLE,
        ucesce.id,
        None,
        FIXED_NOW,
    )

    summary = service.process_batch(10)
    assert summary["published"] == 1
    obav = next(iter(notif_repo.notifications.values()))
    assert notif_repo.existing_recipient_ids(obav.id) == {ucesce.korisnik_id}
    # ANKETA_ID ulazi u sadrzaj (resurs_id polja obavestenja), ne u sistemski dogadjaj.
    assert obav.resurs_id == ucesce.anketa_id
    assert obav.akcija_tip == "SURVEY"


def test_onboarding_survey_available_expired_skipped_not_failed():
    service, event_repo, notif_repo, *_ = _service()
    ucesce = _make_ucesce(datum_isteka=FIXED_NOW - datetime.timedelta(minutes=1))
    event_repo.seed_ucesce(ucesce)
    _seed_onboarding_happy_path(event_repo, ucesce)
    event_repo.enqueue_if_absent(
        "ONBOARDING_SURVEY_AVAILABLE:1", DOGADJAJ_TIP_ONBOARDING_SURVEY_AVAILABLE, ucesce.id, None, FIXED_NOW
    )

    summary = service.process_batch(10)
    assert summary["skipped"] == 1
    assert summary["failed"] == 0
    assert len(notif_repo.notifications) == 0
    event = next(iter(event_repo.events.values()))
    assert event.status == "SKIPPED"


def test_onboarding_survey_available_already_submitted_skipped():
    service, event_repo, notif_repo, *_ = _service()
    ucesce = _make_ucesce(status="SUBMITTED")
    event_repo.seed_ucesce(ucesce)
    _seed_onboarding_happy_path(event_repo, ucesce)
    event_repo.enqueue_if_absent(
        "ONBOARDING_SURVEY_AVAILABLE:1", DOGADJAJ_TIP_ONBOARDING_SURVEY_AVAILABLE, ucesce.id, None, FIXED_NOW
    )

    summary = service.process_batch(10)
    assert summary["skipped"] == 1
    assert len(notif_repo.notifications) == 0


def test_onboarding_survey_available_missing_ucesce_skipped():
    service, event_repo, notif_repo, *_ = _service()
    event_repo.enqueue_if_absent(
        "ONBOARDING_SURVEY_AVAILABLE:1", DOGADJAJ_TIP_ONBOARDING_SURVEY_AVAILABLE, 999, None, FIXED_NOW
    )

    summary = service.process_batch(10)
    assert summary["skipped"] == 1
    assert len(notif_repo.notifications) == 0


# ------------------------------------------------------- fail-closed provere (8 uslova)
def test_onboarding_survey_available_automatika_id_null_skipped():
    """Obicno (rucno dodeljeno) ucesce - AUTOMATIKA_ID NULL - nikad ne salje
    ONBOARDING_SURVEY_AVAILABLE (ovaj tip dogadjaja je iskljucivo za automatsku dodelu)."""
    service, event_repo, notif_repo, *_ = _service()
    ucesce = _make_ucesce(automatika_id=None)
    event_repo.seed_ucesce(ucesce)
    _seed_onboarding_happy_path(event_repo, ucesce)
    event_repo.enqueue_if_absent(
        "ONBOARDING_SURVEY_AVAILABLE:1", DOGADJAJ_TIP_ONBOARDING_SURVEY_AVAILABLE, ucesce.id, None, FIXED_NOW
    )

    summary = service.process_batch(10)
    assert summary["skipped"] == 1
    assert len(notif_repo.notifications) == 0


def test_onboarding_survey_available_before_dostupnost_skipped():
    service, event_repo, notif_repo, *_ = _service()
    ucesce = _make_ucesce(datum_dostupnosti=FIXED_NOW + datetime.timedelta(minutes=1))
    event_repo.seed_ucesce(ucesce)
    _seed_onboarding_happy_path(event_repo, ucesce)
    event_repo.enqueue_if_absent(
        "ONBOARDING_SURVEY_AVAILABLE:1", DOGADJAJ_TIP_ONBOARDING_SURVEY_AVAILABLE, ucesce.id, None, FIXED_NOW
    )

    summary = service.process_batch(10)
    assert summary["skipped"] == 1
    assert len(notif_repo.notifications) == 0


def test_onboarding_survey_available_missing_survey_skipped():
    service, event_repo, notif_repo, *_ = _service()
    ucesce = _make_ucesce()
    event_repo.seed_ucesce(ucesce)
    event_repo.seed_korisnik(
        make_korisnik(id=ucesce.korisnik_id, status_zaposlenja="AKTIVAN", status_naloga="OMOGUCEN")
    )
    # NAMERNO bez seed_survey - anketa ne postoji.
    event_repo.enqueue_if_absent(
        "ONBOARDING_SURVEY_AVAILABLE:1", DOGADJAJ_TIP_ONBOARDING_SURVEY_AVAILABLE, ucesce.id, None, FIXED_NOW
    )

    summary = service.process_batch(10)
    assert summary["skipped"] == 1
    assert len(notif_repo.notifications) == 0


def test_onboarding_survey_available_survey_not_active_skipped():
    service, event_repo, notif_repo, *_ = _service()
    ucesce = _make_ucesce()
    event_repo.seed_ucesce(ucesce)
    event_repo.seed_survey(make_anketa(id=ucesce.anketa_id, status="CLOSED", anonimna="N"))
    event_repo.seed_korisnik(
        make_korisnik(id=ucesce.korisnik_id, status_zaposlenja="AKTIVAN", status_naloga="OMOGUCEN")
    )
    event_repo.enqueue_if_absent(
        "ONBOARDING_SURVEY_AVAILABLE:1", DOGADJAJ_TIP_ONBOARDING_SURVEY_AVAILABLE, ucesce.id, None, FIXED_NOW
    )

    summary = service.process_batch(10)
    assert summary["skipped"] == 1
    assert len(notif_repo.notifications) == 0


def test_onboarding_survey_available_survey_anonymous_skipped():
    service, event_repo, notif_repo, *_ = _service()
    ucesce = _make_ucesce()
    event_repo.seed_ucesce(ucesce)
    event_repo.seed_survey(make_anketa(id=ucesce.anketa_id, status="ACTIVE", anonimna="D"))
    event_repo.seed_korisnik(
        make_korisnik(id=ucesce.korisnik_id, status_zaposlenja="AKTIVAN", status_naloga="OMOGUCEN")
    )
    event_repo.enqueue_if_absent(
        "ONBOARDING_SURVEY_AVAILABLE:1", DOGADJAJ_TIP_ONBOARDING_SURVEY_AVAILABLE, ucesce.id, None, FIXED_NOW
    )

    summary = service.process_batch(10)
    assert summary["skipped"] == 1
    assert len(notif_repo.notifications) == 0


def test_onboarding_survey_available_missing_korisnik_skipped():
    service, event_repo, notif_repo, *_ = _service()
    ucesce = _make_ucesce()
    event_repo.seed_ucesce(ucesce)
    event_repo.seed_survey(make_anketa(id=ucesce.anketa_id, status="ACTIVE", anonimna="N"))
    # NAMERNO bez seed_korisnik - korisnik ne postoji.
    event_repo.enqueue_if_absent(
        "ONBOARDING_SURVEY_AVAILABLE:1", DOGADJAJ_TIP_ONBOARDING_SURVEY_AVAILABLE, ucesce.id, None, FIXED_NOW
    )

    summary = service.process_batch(10)
    assert summary["skipped"] == 1
    assert len(notif_repo.notifications) == 0


def test_onboarding_survey_available_korisnik_zaposlenje_neaktivan_skipped():
    service, event_repo, notif_repo, *_ = _service()
    ucesce = _make_ucesce()
    event_repo.seed_ucesce(ucesce)
    event_repo.seed_survey(make_anketa(id=ucesce.anketa_id, status="ACTIVE", anonimna="N"))
    event_repo.seed_korisnik(
        make_korisnik(id=ucesce.korisnik_id, status_zaposlenja="NEAKTIVAN", status_naloga="OMOGUCEN")
    )
    event_repo.enqueue_if_absent(
        "ONBOARDING_SURVEY_AVAILABLE:1", DOGADJAJ_TIP_ONBOARDING_SURVEY_AVAILABLE, ucesce.id, None, FIXED_NOW
    )

    summary = service.process_batch(10)
    assert summary["skipped"] == 1
    assert len(notif_repo.notifications) == 0


def test_onboarding_survey_available_korisnik_nalog_onemogucen_skipped():
    service, event_repo, notif_repo, *_ = _service()
    ucesce = _make_ucesce()
    event_repo.seed_ucesce(ucesce)
    event_repo.seed_survey(make_anketa(id=ucesce.anketa_id, status="ACTIVE", anonimna="N"))
    event_repo.seed_korisnik(
        make_korisnik(id=ucesce.korisnik_id, status_zaposlenja="AKTIVAN", status_naloga="ONEMOGUCEN")
    )
    event_repo.enqueue_if_absent(
        "ONBOARDING_SURVEY_AVAILABLE:1", DOGADJAJ_TIP_ONBOARDING_SURVEY_AVAILABLE, ucesce.id, None, FIXED_NOW
    )

    summary = service.process_batch(10)
    assert summary["skipped"] == 1
    assert len(notif_repo.notifications) == 0
