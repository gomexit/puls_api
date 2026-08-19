import datetime

import pytest

from app.core.exceptions import (
    InvalidNotificationStatusTransitionError,
    NotificationNotFoundError,
    ValidationBusinessError,
)
from app.models.obavestenje import OBAVESTENJE_STATUS_PUBLISHED
from app.schemas.notification import NotificationDraftInput
from app.services.notification_publishing_service import NotificationPublishingService
from tests.fakes import FakeAuditService, make_korisnik
from tests.notification_fakes import (
    FakeConfigService,
    FakeNotifDb,
    FakeNotificationRepo,
    FakeNotificationTargetingRepo,
    make_kategorija,
)

FIXED_NOW = datetime.datetime(2026, 8, 18, 10, 0, 0)


def _service(repo=None, targeting=None, config=None):
    repo = repo or FakeNotificationRepo()
    if "OPSTE" not in repo.categories:
        repo.add_category(make_kategorija())
    targeting = targeting or FakeNotificationTargetingRepo(all_ids={1, 2, 3})
    return (
        NotificationPublishingService(
            db=FakeNotifDb(),
            repository=repo,
            targeting_repository=targeting,
            audit_service=FakeAuditService(),
            configuration_service=config or FakeConfigService(),
            now_fn=lambda: FIXED_NOW,
        ),
        repo,
    )


def _actor():
    return make_korisnik(id=9, platni_broj="admin9")


def _draft_input(**ov):
    base = dict(
        kategorija_sifra="OPSTE",
        naslov="Naslov",
        kratak_tekst="Kratak",
        sadrzaj="Sadržaj",
        akcija_tip="NONE",
        ciljevi=[{"tip_cilja": "SVI"}],
    )
    base.update(ov)
    return NotificationDraftInput(**base)


def _create_and_publish(service, repo, **draft_ov):
    obav = service.create_draft(_actor(), _draft_input(**draft_ov))
    return service.publish(_actor(), obav.id)


# ------------------------------------------------------------------ targeting
def test_svi_materializes_active_users():
    service, repo = _service(targeting=FakeNotificationTargetingRepo(all_ids={1, 2, 3}))
    obav = _create_and_publish(service, repo)
    assert obav.status == OBAVESTENJE_STATUS_PUBLISHED
    assert repo.existing_recipient_ids(obav.id) == {1, 2, 3}


def test_orgjed_uses_active_rasporedi():
    service, repo = _service(
        targeting=FakeNotificationTargetingRepo(by_orgjed={"409": {2, 5}})
    )
    obav = _create_and_publish(service, repo, ciljevi=[{"tip_cilja": "ORGJED", "vrednost": "409"}])
    assert repo.existing_recipient_ids(obav.id) == {2, 5}


def test_platni_broj_picks_single_user():
    service, repo = _service(
        targeting=FakeNotificationTargetingRepo(by_platni={"12345": 7})
    )
    obav = _create_and_publish(
        service, repo, ciljevi=[{"tip_cilja": "PLATNI_BROJ", "vrednost": "12345"}]
    )
    assert repo.existing_recipient_ids(obav.id) == {7}


def test_overlapping_targets_no_duplicates():
    service, repo = _service(
        targeting=FakeNotificationTargetingRepo(
            all_ids={1, 2}, by_orgjed={"409": {2, 3}}, by_platni={"p": 3}
        )
    )
    obav = _create_and_publish(
        service,
        repo,
        ciljevi=[
            {"tip_cilja": "SVI"},
            {"tip_cilja": "ORGJED", "vrednost": "409"},
            {"tip_cilja": "PLATNI_BROJ", "vrednost": "p"},
        ],
    )
    assert repo.existing_recipient_ids(obav.id) == {1, 2, 3}
    assert len(repo.recipients) == 3


def test_centrala_rejected():
    service, repo = _service()
    with pytest.raises(ValidationBusinessError):
        _create_and_publish(service, repo, ciljevi=[{"tip_cilja": "CENTRALA"}])


def test_maloprodaja_rejected():
    service, repo = _service()
    with pytest.raises(ValidationBusinessError):
        _create_and_publish(service, repo, ciljevi=[{"tip_cilja": "MALOPRODAJA"}])


def test_no_recipients_no_partial_commit():
    service, repo = _service(targeting=FakeNotificationTargetingRepo(all_ids=set()))
    obav = service.create_draft(_actor(), _draft_input())
    with pytest.raises(ValidationBusinessError):
        service.publish(_actor(), obav.id)
    # Nista objavljeno, nema primalaca.
    assert repo.get_notification(obav.id).status != OBAVESTENJE_STATUS_PUBLISHED
    assert repo.existing_recipient_ids(obav.id) == set()


# ------------------------------------------------------------------ expiry
def test_default_expiry_30_days():
    service, repo = _service(config=FakeConfigService())
    obav = _create_and_publish(service, repo)
    assert obav.datum_objave == FIXED_NOW
    assert obav.datum_isteka == FIXED_NOW + datetime.timedelta(days=30)


def test_config_expiry_override_from_konfiguracija():
    service, repo = _service(
        config=FakeConfigService({"NOTIFICATION_DEFAULT_EXPIRY_DAYS": 7})
    )
    obav = _create_and_publish(service, repo)
    assert obav.datum_isteka == FIXED_NOW + datetime.timedelta(days=7)


def test_explicit_expiry_from_input():
    service, repo = _service()
    explicit = FIXED_NOW + datetime.timedelta(days=3)
    obav = _create_and_publish(service, repo, datum_isteka=explicit)
    assert obav.datum_isteka == explicit


# ------------------------------------------------------------------ validation
def test_inactive_category_rejected_at_publish():
    repo = FakeNotificationRepo()
    repo.add_category(make_kategorija(sifra="OPSTE", aktivna="N"))
    service, repo = _service(repo=repo)
    obav = service.create_draft(_actor(), _draft_input())
    with pytest.raises(ValidationBusinessError):
        service.publish(_actor(), obav.id)


def test_missing_category_rejected_at_draft():
    repo = FakeNotificationRepo()  # bez kategorija
    service = NotificationPublishingService(
        db=FakeNotifDb(),
        repository=repo,
        targeting_repository=FakeNotificationTargetingRepo(all_ids={1}),
        audit_service=FakeAuditService(),
        configuration_service=FakeConfigService(),
        now_fn=lambda: FIXED_NOW,
    )
    with pytest.raises(ValidationBusinessError):
        service.create_draft(_actor(), _draft_input())


def test_invalid_action_rejected():
    # SURVEY bez resurs_id -> pydantic ValidationError na nivou ulaza.
    with pytest.raises(ValueError):
        _draft_input(akcija_tip="SURVEY")


def test_https_url_accepted_dangerous_rejected():
    ok = _draft_input(akcija_tip="URL", akcija_url="https://gomex.rs/promo")
    assert ok.akcija_url == "https://gomex.rs/promo"
    for bad in ("javascript:alert(1)", "file:///etc/passwd", "http://x.rs", "ftp://x"):
        with pytest.raises(ValueError):
            _draft_input(akcija_tip="URL", akcija_url=bad)


def test_timezone_aware_expiry_rejected():
    aware = datetime.datetime(2026, 8, 20, tzinfo=datetime.timezone.utc)
    with pytest.raises(ValueError):
        _draft_input(datum_isteka=aware)


def test_publish_with_aware_datum_isteka_rejected_no_type_error():
    # Direktno prosledjen aware datum_isteka -> ValidationBusinessError (ne TypeError/500).
    service, repo = _service()
    obav = service.create_draft(_actor(), _draft_input())
    aware = datetime.datetime(2026, 9, 1, tzinfo=datetime.timezone.utc)
    with pytest.raises(ValidationBusinessError):
        service.publish(_actor(), obav.id, datum_isteka=aware)
    assert repo.get_notification(obav.id).status != OBAVESTENJE_STATUS_PUBLISHED


def test_resurs_id_zero_and_negative_rejected():
    for bad in (0, -1):
        with pytest.raises(ValueError):
            _draft_input(akcija_tip="SURVEY", resurs_id=bad)


def test_valid_positive_resurs_id_accepted():
    inp = _draft_input(akcija_tip="IDEA", resurs_id=5)
    assert inp.resurs_id == 5


# ------------------------------------------------------------------ autor (identitet)
def test_payload_cannot_fake_author():
    # Nepoznato polje 'kreirao_platni_broj' u payload-u se odbija (extra='forbid').
    with pytest.raises(ValueError):
        _draft_input(kreirao_platni_broj="9999")


def test_author_taken_from_actor():
    service, repo = _service()
    obav = service.create_draft(_actor(), _draft_input())
    assert repo.get_notification(obav.id).kreirao_platni_broj == "admin9"


def test_author_null_for_system_event():
    service, repo = _service()
    obav = service.create_draft(None, _draft_input())
    assert repo.get_notification(obav.id).kreirao_platni_broj is None


def test_republish_conflict_no_duplicate_recipients():
    service, repo = _service(targeting=FakeNotificationTargetingRepo(all_ids={1, 2}))
    obav = _create_and_publish(service, repo)
    assert repo.existing_recipient_ids(obav.id) == {1, 2}
    with pytest.raises(InvalidNotificationStatusTransitionError):
        service.publish(_actor(), obav.id)
    assert len(repo.recipients) == 2  # bez duplikata


def test_publish_missing_notification():
    service, repo = _service()
    with pytest.raises(NotificationNotFoundError):
        service.publish(_actor(), 99999)


def test_unrelated_integrity_error_not_masked():
    from sqlalchemy.exc import IntegrityError

    service, repo = _service()
    obav = service.create_draft(_actor(), _draft_input())

    def _boom(_id):
        raise IntegrityError("stmt", {}, Exception("ORA-nesto nepovezano"))

    repo.get_targets = _boom
    with pytest.raises(IntegrityError):
        service.publish(_actor(), obav.id)
