import datetime

import pytest
from sqlalchemy.exc import IntegrityError

from app.core.exceptions import (
    InvalidNotificationStatusTransitionError,
    NotificationCategoryAlreadyExistsError,
    NotificationCategoryNotFoundError,
    NotificationEditNotAllowedError,
    NotificationNotFoundError,
    ValidationBusinessError,
)
from app.models.obavestenje import ObavestenjeCilj
from app.schemas.notification import NotificationDraftInput
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


def _actor():
    return make_korisnik(id=7, platni_broj="admin7")


def _admin(repo=None, targeting=None, config=None):
    repo = repo or FakeNotificationRepo()
    # Podrazumevanu OPSTE kategoriju dodaj samo za prazan repo (draft testovi je koriste);
    # testovi liste kategorija prosledjuju svoj repo i ne smeju dobiti dodatnu kategoriju.
    if not repo.categories:
        repo.add_category(make_kategorija())
    audit = FakeAuditService()
    # Admin i publishing dele JEDNU sesiju (kao u produkciji) -> jedna transakcija.
    db = FakeNotifDb()
    pub = NotificationPublishingService(
        db=db,
        repository=repo,
        targeting_repository=targeting or FakeNotificationTargetingRepo(all_ids={1, 2, 3}),
        audit_service=audit,
        configuration_service=config or FakeConfigService(),
        push_delivery_repository=FakePushDeliveryRepo(),
        now_fn=lambda: FIXED_NOW,
    )
    admin = NotificationAdminService(
        db=db, repository=repo, publishing_service=pub, audit_service=audit
    )
    return admin, repo, audit


def _draft(**ov):
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


# ================================================================= KATEGORIJE
def test_list_categories_sort_nulls_last():
    repo = FakeNotificationRepo()
    repo.add_category(make_kategorija(sifra="B", naziv="B"))  # redosled 10
    no_order = make_kategorija(sifra="A", naziv="A")
    no_order.redosled = None
    repo.add_category(no_order)
    repo.add_category(make_kategorija(sifra="C", naziv="C"))  # redosled 10
    admin, _, _ = _admin(repo=repo)
    sifre = [k.sifra for k in admin.list_categories(None)]
    # redosled 10 (B, C) po sifri, pa NULL (A) poslednje
    assert sifre == ["B", "C", "A"]


def test_list_categories_filter_active():
    repo = FakeNotificationRepo()
    repo.add_category(make_kategorija(sifra="AKT", aktivna="D"))
    repo.add_category(make_kategorija(sifra="NEAK", aktivna="N"))
    admin, _, _ = _admin(repo=repo)
    assert {k.sifra for k in admin.list_categories(True)} == {"AKT"}
    assert {k.sifra for k in admin.list_categories(False)} == {"NEAK"}
    assert {k.sifra for k in admin.list_categories(None)} == {"AKT", "NEAK"}


def test_create_category_audits_and_returns():
    admin, repo, audit = _admin()
    kat = admin.create_category(_actor(), "BENEFITI", "Benefiti", True, 60)
    assert kat.sifra == "BENEFITI" and kat.aktivna == "D"
    assert any(e["sifra_akcije"] == AuditAction.NOTIFICATION_CATEGORY_CREATED for e in audit.entries)


def test_create_category_duplicate_returns_409():
    admin, repo, _ = _admin()

    def _boom(_kat):
        raise IntegrityError("stmt", {}, Exception("ORA-00001 PK_PULS_OBAV_KATEGORIJE"))

    repo.add_category = _boom
    with pytest.raises(NotificationCategoryAlreadyExistsError):
        admin.create_category(_actor(), "OPSTE", "Opšte", True, 1)


def test_create_category_unrelated_integrity_error_propagates():
    admin, repo, _ = _admin()

    def _boom(_kat):
        raise IntegrityError("stmt", {}, Exception("ORA-02290 NEKI_DRUGI_CHECK"))

    repo.add_category = _boom
    with pytest.raises(IntegrityError):
        admin.create_category(_actor(), "X", "X", True, 1)


def test_update_category_ok():
    admin, repo, audit = _admin()
    repo.add_category(make_kategorija(sifra="HR", naziv="Staro", aktivna="D"))
    kat = admin.update_category(_actor(), "HR", "Novo", False, 70)
    assert kat.naziv == "Novo" and kat.aktivna == "N" and kat.datum_izmene is not None
    assert any(e["sifra_akcije"] == AuditAction.NOTIFICATION_CATEGORY_UPDATED for e in audit.entries)


def test_update_missing_category_404():
    admin, _, _ = _admin()
    with pytest.raises(NotificationCategoryNotFoundError):
        admin.update_category(_actor(), "NEMA", "X", True, 1)


def test_deactivated_category_cannot_publish():
    repo = FakeNotificationRepo()
    repo.add_category(make_kategorija(sifra="OPSTE", aktivna="N"))
    admin, repo, _ = _admin(repo=repo)
    detail = admin.create(_actor(), _draft())
    with pytest.raises(ValidationBusinessError):
        admin.change_status(_actor(), detail["id"], "PUBLISHED", None)


# ============================================================ LISTA / DETALJ
def test_admin_list_pagination_and_counts():
    repo = FakeNotificationRepo()
    repo.add_category(make_kategorija())
    for i in range(3):
        o = repo.seed_notification(
            make_obavestenje(datum_kreiranja=FIXED_NOW - datetime.timedelta(days=i))
        )
        repo.seed_recipient(make_primalac(o.id, 1, procitano="D", datum_citanja=FIXED_NOW))
        repo.seed_recipient(make_primalac(o.id, 2, procitano="N"))
    admin, _, _ = _admin(repo=repo)
    res = admin.list_notifications(None, None, None, None, 1, 2)
    assert res["total"] == 3 and len(res["items"]) == 2
    item = res["items"][0]
    assert item["broj_primalaca"] == 2 and item["broj_procitanih"] == 1 and item["broj_neprocitanih"] == 1
    assert "sadrzaj" not in item


def test_admin_list_status_and_category_filter():
    repo = FakeNotificationRepo()
    repo.add_category(make_kategorija(sifra="OPSTE"))
    repo.add_category(make_kategorija(sifra="HR", naziv="HR"))
    repo.seed_notification(make_obavestenje(status="DRAFT", kategorija_sifra="OPSTE"))
    repo.seed_notification(make_obavestenje(status="PUBLISHED", kategorija_sifra="HR"))
    admin, _, _ = _admin(repo=repo)
    assert admin.list_notifications("DRAFT", None, None, None, 1, 50)["total"] == 1
    assert admin.list_notifications(None, "HR", None, None, 1, 50)["total"] == 1


def test_admin_detail_has_sadrzaj_and_targets():
    repo = FakeNotificationRepo()
    repo.add_category(make_kategorija())
    admin, repo, _ = _admin(repo=repo)
    detail = admin.create(_actor(), _draft(sadrzaj="Pun tekst"))
    got = admin.get_detail(detail["id"])
    assert got["sadrzaj"] == "Pun tekst"
    assert got["ciljevi"] == [{"tip_cilja": "SVI", "vrednost": None}]
    assert got["status"] == "DRAFT"


def test_admin_detail_all_statuses_visible():
    repo = FakeNotificationRepo()
    repo.add_category(make_kategorija())
    for st in ("DRAFT", "PUBLISHED", "ARCHIVED"):
        o = repo.seed_notification(make_obavestenje(status=st))
        admin, _, _ = _admin(repo=repo)
        assert admin.get_detail(o.id)["status"] == st


def test_admin_detail_missing_404():
    admin, _, _ = _admin()
    with pytest.raises(NotificationNotFoundError):
        admin.get_detail(99999)


# =============================================================== CREATE/UPDATE
def test_create_author_from_actor_only():
    admin, repo, _ = _admin()
    detail = admin.create(_actor(), _draft())
    assert detail["kreirao_platni_broj"] == "admin7"
    assert detail["status"] == "DRAFT"


def test_update_only_draft():
    admin, repo, _ = _admin()
    detail = admin.create(_actor(), _draft(naslov="Staro"))
    updated = admin.update(_actor(), detail["id"], _draft(naslov="Novo", ciljevi=[{"tip_cilja": "SVI"}]))
    assert updated["naslov"] == "Novo"


def test_update_published_not_allowed():
    repo = FakeNotificationRepo()
    repo.add_category(make_kategorija())
    o = repo.seed_notification(make_obavestenje(status="PUBLISHED"))
    admin, _, _ = _admin(repo=repo)
    with pytest.raises(NotificationEditNotAllowedError):
        admin.update(_actor(), o.id, _draft())


def test_update_replaces_targets_atomically():
    admin, repo, _ = _admin(targeting=FakeNotificationTargetingRepo(all_ids={1}, by_orgjed={"409": {2}}))
    detail = admin.create(_actor(), _draft(ciljevi=[{"tip_cilja": "SVI"}]))
    admin.update(_actor(), detail["id"], _draft(ciljevi=[{"tip_cilja": "ORGJED", "vrednost": "409"}]))
    targets = repo.get_targets(detail["id"])
    assert [(t.tip_cilja, t.vrednost) for t in targets] == [("ORGJED", "409")]


def test_update_failure_keeps_old_targets():
    admin, repo, _ = _admin()
    detail = admin.create(_actor(), _draft(ciljevi=[{"tip_cilja": "SVI"}]))

    def _boom(_nid):
        raise RuntimeError("delete pukao")

    repo.delete_targets = _boom
    with pytest.raises(RuntimeError):
        admin.update(_actor(), detail["id"], _draft(ciljevi=[{"tip_cilja": "ORGJED", "vrednost": "9"}]))
    # Stari cilj netaknut.
    assert [(t.tip_cilja, t.vrednost) for t in repo.get_targets(detail["id"])] == [("SVI", None)]


def test_centrala_rejected_at_create():
    admin, _, _ = _admin()
    with pytest.raises(ValidationBusinessError):
        admin.create(_actor(), _draft(ciljevi=[{"tip_cilja": "CENTRALA"}]))


def test_survey_resource_existing_and_missing():
    repo = FakeNotificationRepo()
    repo.add_category(make_kategorija())
    repo.survey_ids = {25}
    admin, repo, _ = _admin(repo=repo)
    ok = admin.create(_actor(), _draft(akcija_tip="SURVEY", resurs_id=25))
    assert ok["akcija"] == {"tip": "SURVEY", "resurs_id": 25, "url": None}
    with pytest.raises(ValidationBusinessError):
        admin.create(_actor(), _draft(akcija_tip="SURVEY", resurs_id=999))


def test_idea_resource_existing_and_missing():
    repo = FakeNotificationRepo()
    repo.add_category(make_kategorija())
    repo.idea_ids = {5}
    admin, repo, _ = _admin(repo=repo)
    assert admin.create(_actor(), _draft(akcija_tip="IDEA", resurs_id=5))["akcija"]["resurs_id"] == 5
    with pytest.raises(ValidationBusinessError):
        admin.create(_actor(), _draft(akcija_tip="IDEA", resurs_id=1))


# ==================================================================== STATUS
def test_status_draft_to_published():
    admin, repo, _ = _admin()
    detail = admin.create(_actor(), _draft())
    published = admin.change_status(_actor(), detail["id"], "PUBLISHED", None)
    assert published["status"] == "PUBLISHED"
    assert published["broj_primalaca"] == 3
    assert published["datum_isteka"] == FIXED_NOW + datetime.timedelta(days=30)


def test_status_explicit_expiry():
    admin, repo, _ = _admin()
    detail = admin.create(_actor(), _draft())
    explicit = FIXED_NOW + datetime.timedelta(days=3)
    published = admin.change_status(_actor(), detail["id"], "PUBLISHED", explicit)
    assert published["datum_isteka"] == explicit


def test_status_published_to_archived_keeps_recipients():
    admin, repo, _ = _admin()
    detail = admin.create(_actor(), _draft())
    admin.change_status(_actor(), detail["id"], "PUBLISHED", None)
    before = repo.recipient_counts(detail["id"])[0]
    archived = admin.change_status(_actor(), detail["id"], "ARCHIVED", None)
    assert archived["status"] == "ARCHIVED"
    assert repo.recipient_counts(detail["id"])[0] == before  # primaoci ostaju


def test_status_illegal_transitions_409():
    admin, repo, _ = _admin()
    detail = admin.create(_actor(), _draft())
    # DRAFT -> ARCHIVED zabranjeno
    with pytest.raises(InvalidNotificationStatusTransitionError):
        admin.change_status(_actor(), detail["id"], "ARCHIVED", None)
    # DRAFT -> DRAFT zabranjeno
    with pytest.raises(InvalidNotificationStatusTransitionError):
        admin.change_status(_actor(), detail["id"], "DRAFT", None)


def test_status_republish_conflict():
    admin, repo, _ = _admin()
    detail = admin.create(_actor(), _draft())
    admin.change_status(_actor(), detail["id"], "PUBLISHED", None)
    with pytest.raises(InvalidNotificationStatusTransitionError):
        admin.change_status(_actor(), detail["id"], "PUBLISHED", None)


# ================================================================= STATISTIKA
def test_stats_zero_recipients():
    admin, repo, _ = _admin()
    detail = admin.create(_actor(), _draft())
    stats = admin.get_stats(detail["id"])
    assert stats == {
        "notification_id": detail["id"],
        "broj_primalaca": 0,
        "broj_procitanih": 0,
        "broj_neprocitanih": 0,
        "procenat_procitanih": 0.0,
        "push_pending": 0,
        "push_sent": 0,
        "push_failed": 0,
        "push_skipped": 0,
    }


def test_stats_counts_and_rounding():
    repo = FakeNotificationRepo()
    repo.add_category(make_kategorija())
    o = repo.seed_notification(make_obavestenje())
    # 1 od 3 procitano -> 33.33%
    repo.seed_recipient(make_primalac(o.id, 1, procitano="D", datum_citanja=FIXED_NOW))
    repo.seed_recipient(make_primalac(o.id, 2, procitano="N"))
    repo.seed_recipient(make_primalac(o.id, 3, procitano="N"))
    admin, _, _ = _admin(repo=repo)
    stats = admin.get_stats(o.id)
    assert stats["broj_primalaca"] == 3 and stats["broj_procitanih"] == 1
    assert stats["broj_neprocitanih"] == 2 and stats["procenat_procitanih"] == 33.33


def test_stats_missing_404():
    admin, _, _ = _admin()
    with pytest.raises(NotificationNotFoundError):
        admin.get_stats(1234)


# ======================================================== TRANSAKCIONE GRANICE
def _boom_counts(*_a, **_k):
    raise RuntimeError("detail/count pukao")


def test_create_detail_failure_rolls_back():
    admin, repo, _ = _admin()
    repo.recipient_counts = _boom_counts
    with pytest.raises(RuntimeError):
        admin.create(_actor(), _draft())
    assert admin.db.committed == 0
    assert admin.db.rolled_back == 1


def test_update_detail_failure_rolls_back():
    admin, repo, _ = _admin()
    detail = admin.create(_actor(), _draft())
    committed_before = admin.db.committed
    repo.recipient_counts = _boom_counts
    with pytest.raises(RuntimeError):
        admin.update(_actor(), detail["id"], _draft(naslov="Novo"))
    assert admin.db.committed == committed_before  # nema novog commit-a
    assert admin.db.rolled_back == 1


def test_publish_stats_failure_not_committed():
    admin, repo, _ = _admin()
    detail = admin.create(_actor(), _draft())
    committed_before = admin.db.committed
    repo.recipient_counts = _boom_counts
    with pytest.raises(RuntimeError):
        admin.change_status(_actor(), detail["id"], "PUBLISHED", None)
    # Status i primaoci nisu commitovani (nije bilo commit-a posle apply_publish).
    assert admin.db.committed == committed_before


def test_archive_detail_failure_not_committed():
    admin, repo, _ = _admin()
    detail = admin.create(_actor(), _draft())
    admin.change_status(_actor(), detail["id"], "PUBLISHED", None)
    committed_before = admin.db.committed
    repo.recipient_counts = _boom_counts
    with pytest.raises(RuntimeError):
        admin.change_status(_actor(), detail["id"], "ARCHIVED", None)
    assert admin.db.committed == committed_before


def test_success_flows_do_exactly_one_commit_each():
    admin, repo, _ = _admin()
    d = admin.create(_actor(), _draft())
    assert admin.db.committed == 1
    admin.update(_actor(), d["id"], _draft(naslov="X"))
    assert admin.db.committed == 2
    admin.change_status(_actor(), d["id"], "PUBLISHED", None)
    assert admin.db.committed == 3
    admin.change_status(_actor(), d["id"], "ARCHIVED", None)
    assert admin.db.committed == 4


def test_no_db_read_after_commit_on_create():
    admin, repo, _ = _admin()
    for name in ("recipient_counts", "get_targets", "get_category"):
        orig = getattr(repo, name)

        def guard(*a, _orig=orig, _name=name, **k):
            assert admin.db.committed == 0, f"{_name} pozvan posle commit-a"
            return _orig(*a, **k)

        setattr(repo, name, guard)
    admin.create(_actor(), _draft())
    assert admin.db.committed == 1


def test_no_db_read_after_commit_on_publish():
    # Seed DRAFT direktno (bez admin.create) da commit brojac krene od 0 za publish.
    repo = FakeNotificationRepo()
    repo.add_category(make_kategorija())
    o = repo.seed_notification(
        make_obavestenje(status="DRAFT", datum_objave=None, datum_isteka=None)
    )
    repo.targets.append(ObavestenjeCilj(obavestenje_id=o.id, tip_cilja="SVI", vrednost=None))
    admin, repo, _ = _admin(repo=repo, targeting=FakeNotificationTargetingRepo(all_ids={1, 2}))
    for name in ("recipient_counts", "get_targets", "get_category"):
        orig = getattr(repo, name)

        def guard(*a, _orig=orig, _name=name, **k):
            assert admin.db.committed == 0, f"{_name} pozvan posle commit-a"
            return _orig(*a, **k)

        setattr(repo, name, guard)
    admin.change_status(_actor(), o.id, "PUBLISHED", None)
    assert admin.db.committed == 1


def test_archived_hidden_from_employee_inbox():
    from app.services.notification_service import NotificationService

    repo = FakeNotificationRepo()
    repo.add_category(make_kategorija())
    admin, repo, _ = _admin(repo=repo, targeting=FakeNotificationTargetingRepo(all_ids={1}))
    detail = admin.create(_actor(), _draft())
    admin.change_status(_actor(), detail["id"], "PUBLISHED", None)

    emp = NotificationService(
        db=FakeNotifDb(), repository=repo, audit_service=FakeAuditService(), now_fn=lambda: FIXED_NOW
    )
    k = make_korisnik(id=1, platni_broj="p1")
    assert emp.list_inbox(k, 1, 20, "ALL", None)["total"] == 1

    admin.change_status(_actor(), detail["id"], "ARCHIVED", None)
    assert emp.list_inbox(k, 1, 20, "ALL", None)["total"] == 0
