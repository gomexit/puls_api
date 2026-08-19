"""Publish kreira PENDING push redove u ISTOJ transakciji; FCM se NE poziva u publish-u."""

import datetime

import pytest

from app.schemas.notification import NotificationDraftInput
from app.services.notification_publishing_service import NotificationPublishingService
from tests.fakes import FakeAuditService, make_korisnik
from tests.notification_fakes import (
    FakeConfigService,
    FakeNotifDb,
    FakeNotificationRepo,
    FakeNotificationTargetingRepo,
    FakePushDeliveryRepo,
    make_kategorija,
)

FIXED_NOW = datetime.datetime(2026, 8, 19, 10, 0, 0)


def _service(all_ids=None, push=None):
    repo = FakeNotificationRepo()
    repo.add_category(make_kategorija())
    push = push or FakePushDeliveryRepo()
    svc = NotificationPublishingService(
        db=FakeNotifDb(),
        repository=repo,
        targeting_repository=FakeNotificationTargetingRepo(all_ids=all_ids or {1, 2, 3}),
        audit_service=FakeAuditService(),
        configuration_service=FakeConfigService(),
        push_delivery_repository=push,
        now_fn=lambda: FIXED_NOW,
    )
    return svc, repo, push


def _draft(**ov):
    base = dict(kategorija_sifra="OPSTE", naslov="N", kratak_tekst="K", sadrzaj="S",
                akcija_tip="NONE", ciljevi=[{"tip_cilja": "SVI"}])
    base.update(ov)
    return NotificationDraftInput(**base)


def _actor():
    return make_korisnik(id=9, platni_broj="admin9")


def test_publish_creates_pending_delivery_per_recipient():
    svc, repo, push = _service(all_ids={1, 2, 3})
    obav = svc.create_draft(_actor(), _draft())
    svc.publish(_actor(), obav.id)
    rows = [r for r in push.rows if r.obavestenje_id == obav.id]
    assert {r.korisnik_id for r in rows} == {1, 2, 3}
    # Nijedan nije SENT: FCM se NE poziva u publish-u (worker to radi kasnije).
    assert all(r.status == "PENDING" for r in rows)


def test_publish_rolls_back_if_delivery_fails():
    svc, repo, push = _service(all_ids={1, 2})
    obav = svc.create_draft(_actor(), _draft())

    def _boom(*a, **k):
        raise RuntimeError("outbox pukao")

    push.create_pending_for_recipients = _boom
    with pytest.raises(RuntimeError):
        svc.publish(_actor(), obav.id)
    # Publish nije commitovan; status ostaje DRAFT u bazi (nije PUBLISHED).
    assert repo.get_notification(obav.id).status != "PUBLISHED"


def test_publish_idempotent_no_duplicate_delivery_rows():
    push = FakePushDeliveryRepo()
    push.create_pending_for_recipients(5, {1, 2}, FIXED_NOW)
    push.create_pending_for_recipients(5, {1, 2, 3}, FIXED_NOW)  # ponovljeno + jedan nov
    rows = [r for r in push.rows if r.obavestenje_id == 5]
    assert sorted(r.korisnik_id for r in rows) == [1, 2, 3]  # bez duplikata


def test_publish_works_for_system_actor_none():
    svc, repo, push = _service(all_ids={1})
    obav = svc.create_draft(None, _draft())
    svc.publish(None, obav.id)
    assert [r.korisnik_id for r in push.rows if r.obavestenje_id == obav.id] == [1]
