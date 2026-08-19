"""Admin push: resend-unread i push statistika (aditivno)."""

import datetime

import pytest

from app.core.exceptions import (
    InvalidNotificationStatusTransitionError,
    ValidationBusinessError,
)
from app.services.audit_service import AuditAction
from app.services.notification_admin_service import NotificationAdminService
from app.services.notification_publishing_service import NotificationPublishingService
from tests.fakes import FakeAuditService, make_korisnik
from tests.notification_fakes import (
    FakeConfigService,
    FakeNotifDb,
    FakeNotificationRepo,
    FakeNotificationTargetingRepo,
    FakePushDeliveryRepo,
    make_kategorija,
    make_obavestenje,
    make_primalac,
)

FIXED_NOW = datetime.datetime(2026, 8, 19, 10, 0, 0)


def _admin(repo):
    audit = FakeAuditService()
    db = FakeNotifDb()
    push = FakePushDeliveryRepo()
    pub = NotificationPublishingService(
        db=db, repository=repo, targeting_repository=FakeNotificationTargetingRepo(all_ids={1}),
        audit_service=audit, configuration_service=FakeConfigService(),
        push_delivery_repository=push, now_fn=lambda: FIXED_NOW,
    )
    admin = NotificationAdminService(db=db, repository=repo, publishing_service=pub, audit_service=audit)
    return admin, push, audit


def _actor():
    return make_korisnik(id=7, platni_broj="admin7")


def _published_repo():
    repo = FakeNotificationRepo()
    repo.add_category(make_kategorija())
    obav = repo.seed_notification(make_obavestenje(status="PUBLISHED"))
    repo.seed_recipient(make_primalac(obav.id, 1, procitano="N"))  # nepr.
    repo.seed_recipient(make_primalac(obav.id, 2, procitano="D", datum_citanja=FIXED_NOW))  # proc.
    return repo, obav


def test_resend_only_unread_and_no_read_change():
    repo, obav = _published_repo()
    admin, push, audit = _admin(repo)
    # Vec postoje SENT redovi za oba primaoca.
    push.add_pending(obav.id, 1, FIXED_NOW).status = "SENT"
    push.add_pending(obav.id, 2, FIXED_NOW).status = "SENT"

    result = admin.resend_unread(_actor(), obav.id)
    assert result == {"notification_id": obav.id, "resent_count": 1}

    row1 = next(r for r in push.rows if r.korisnik_id == 1)
    row2 = next(r for r in push.rows if r.korisnik_id == 2)
    assert row1.status == "PENDING" and row1.broj_ponovnih_slanja == 1  # nepr. -> requeue
    assert row2.status == "SENT"  # proc. netaknut
    # read/unread se ne menja
    p1 = next(p for p in repo.recipients if p.korisnik_id == 1)
    p2 = next(p for p in repo.recipients if p.korisnik_id == 2)
    assert p1.procitano == "N" and p2.procitano == "D"
    assert any(e["sifra_akcije"] == AuditAction.NOTIFICATION_PUSH_RESEND for e in audit.entries)


def test_resend_no_duplicate_rows():
    repo, obav = _published_repo()
    admin, push, _ = _admin(repo)
    push.add_pending(obav.id, 1, FIXED_NOW).status = "SENT"
    admin.resend_unread(_actor(), obav.id)
    admin.resend_unread(_actor(), obav.id)
    rows_for_1 = [r for r in push.rows if r.korisnik_id == 1 and r.obavestenje_id == obav.id]
    assert len(rows_for_1) == 1  # bez duplikata
    assert rows_for_1[0].broj_ponovnih_slanja == 2


def test_resend_clears_stale_sent_state():
    # Item 5: SENT/FAILED red vracen u PENDING ne sme zadrzati stari DATUM_SLANJA
    # ni DATUM_POSLEDNJEG_POKUSAJA (curenje starog stanja kroz novi ciklus slanja).
    repo, obav = _published_repo()
    admin, push, _ = _admin(repo)
    row = push.add_pending(obav.id, 1, FIXED_NOW)
    row.status = "SENT"
    row.datum_slanja = FIXED_NOW - datetime.timedelta(days=1)
    row.datum_poslednjeg_pokusaja = FIXED_NOW - datetime.timedelta(days=1)
    row.poslednji_error_code = "NEKA_STARA_GRESKA"
    row.broj_pokusaja = 3

    admin.resend_unread(_actor(), obav.id)

    assert row.status == "PENDING"
    assert row.datum_slanja is None
    assert row.datum_poslednjeg_pokusaja is None
    assert row.poslednji_error_code is None
    assert row.broj_pokusaja == 0
    assert row.broj_ponovnih_slanja == 1


def test_resend_rejected_for_draft():
    repo = FakeNotificationRepo()
    repo.add_category(make_kategorija())
    obav = repo.seed_notification(make_obavestenje(status="DRAFT", datum_objave=None, datum_isteka=None))
    admin, _, _ = _admin(repo)
    with pytest.raises(InvalidNotificationStatusTransitionError):
        admin.resend_unread(_actor(), obav.id)


def test_resend_rejected_for_expired():
    repo = FakeNotificationRepo()
    repo.add_category(make_kategorija())
    obav = repo.seed_notification(
        make_obavestenje(status="PUBLISHED", datum_isteka=FIXED_NOW - datetime.timedelta(days=1))
    )
    admin, _, _ = _admin(repo)
    with pytest.raises(ValidationBusinessError):
        admin.resend_unread(_actor(), obav.id)


def test_stats_includes_push_fields():
    repo, obav = _published_repo()
    admin, push, _ = _admin(repo)
    push.add_pending(obav.id, 1, FIXED_NOW)  # PENDING
    push.add_pending(obav.id, 2, FIXED_NOW).status = "SENT"
    push.add_pending(obav.id, 3, FIXED_NOW).status = "FAILED"
    push.add_pending(obav.id, 4, FIXED_NOW).status = "SKIPPED"
    stats = admin.get_stats(obav.id)
    assert stats["push_pending"] == 1
    assert stats["push_sent"] == 1
    assert stats["push_failed"] == 1
    assert stats["push_skipped"] == 1
