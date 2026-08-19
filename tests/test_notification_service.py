import datetime

import pytest

from app.core.exceptions import NotificationNotFoundError
from app.services.audit_service import AuditAction
from app.services.notification_service import NotificationService
from tests.fakes import FakeAuditService, make_korisnik
from tests.notification_fakes import (
    FakeNotifDb,
    FakeNotificationRepo,
    make_kategorija,
    make_obavestenje,
    make_primalac,
)

FIXED_NOW = datetime.datetime(2026, 8, 18, 10, 0, 0)


def _service(repo):
    audit = FakeAuditService()
    return (
        NotificationService(
            db=FakeNotifDb(),
            repository=repo,
            audit_service=audit,
            now_fn=lambda: FIXED_NOW,
        ),
        audit,
    )


def _repo_with(*notifs_and_recips):
    repo = FakeNotificationRepo()
    repo.add_category(make_kategorija())
    return repo


def _korisnik(id=1):
    return make_korisnik(id=id, platni_broj=f"p{id}")


# ------------------------------------------------------------------ visibility
def test_only_own_recipients_visible():
    repo = _repo_with()
    o1 = repo.seed_notification(make_obavestenje(naslov="Moje"))
    o2 = repo.seed_notification(make_obavestenje(naslov="Tudje"))
    repo.seed_recipient(make_primalac(o1.id, korisnik_id=1))
    repo.seed_recipient(make_primalac(o2.id, korisnik_id=2))
    service, _ = _service(repo)
    result = service.list_inbox(_korisnik(1), 1, 20, "ALL", None)
    assert [it["naslov"] for it in result["items"]] == ["Moje"]


def test_draft_future_expired_archived_hidden():
    repo = _repo_with()
    draft = repo.seed_notification(make_obavestenje(status="DRAFT", datum_objave=None, datum_isteka=None))
    archived = repo.seed_notification(make_obavestenje(status="ARCHIVED"))
    future = repo.seed_notification(
        make_obavestenje(datum_objave=FIXED_NOW + datetime.timedelta(days=1))
    )
    expired = repo.seed_notification(
        make_obavestenje(
            datum_objave=FIXED_NOW - datetime.timedelta(days=2),
            datum_isteka=FIXED_NOW - datetime.timedelta(days=1),
        )
    )
    for o in (draft, archived, future, expired):
        repo.seed_recipient(make_primalac(o.id, korisnik_id=1))
    service, _ = _service(repo)
    result = service.list_inbox(_korisnik(1), 1, 20, "ALL", None)
    assert result["total"] == 0


def test_sorting_datum_objave_desc_then_id_desc():
    repo = _repo_with()
    same = FIXED_NOW - datetime.timedelta(days=1)
    older = FIXED_NOW - datetime.timedelta(days=5)
    a = repo.seed_notification(make_obavestenje(datum_objave=older))
    b = repo.seed_notification(make_obavestenje(datum_objave=same))
    c = repo.seed_notification(make_obavestenje(datum_objave=same))
    for o in (a, b, c):
        repo.seed_recipient(make_primalac(o.id, korisnik_id=1))
    service, _ = _service(repo)
    ids = [it["id"] for it in service.list_inbox(_korisnik(1), 1, 20, "ALL", None)["items"]]
    # Isti datum -> veci ID prvi; stariji datum poslednji.
    assert ids == [max(b.id, c.id), min(b.id, c.id), a.id]


def test_pagination_total_and_has_more():
    repo = _repo_with()
    for i in range(3):
        o = repo.seed_notification(
            make_obavestenje(datum_objave=FIXED_NOW - datetime.timedelta(days=i + 1))
        )
        repo.seed_recipient(make_primalac(o.id, korisnik_id=1))
    service, _ = _service(repo)
    page1 = service.list_inbox(_korisnik(1), 1, 2, "ALL", None)
    assert page1["total"] == 3 and page1["has_more"] is True and len(page1["items"]) == 2
    page2 = service.list_inbox(_korisnik(1), 2, 2, "ALL", None)
    assert page2["has_more"] is False and len(page2["items"]) == 1


def test_read_status_filter():
    repo = _repo_with()
    read = repo.seed_notification(make_obavestenje())
    unread = repo.seed_notification(make_obavestenje())
    repo.seed_recipient(make_primalac(read.id, 1, procitano="D", datum_citanja=FIXED_NOW))
    repo.seed_recipient(make_primalac(unread.id, 1, procitano="N"))
    service, _ = _service(repo)
    assert service.list_inbox(_korisnik(1), 1, 20, "READ", None)["total"] == 1
    assert service.list_inbox(_korisnik(1), 1, 20, "UNREAD", None)["total"] == 1
    assert service.list_inbox(_korisnik(1), 1, 20, "ALL", None)["total"] == 2


def test_category_filter():
    repo = FakeNotificationRepo()
    repo.add_category(make_kategorija(sifra="OPSTE"))
    repo.add_category(make_kategorija(sifra="ANKETA", naziv="Ankete"))
    o1 = repo.seed_notification(make_obavestenje(kategorija_sifra="OPSTE"))
    o2 = repo.seed_notification(make_obavestenje(kategorija_sifra="ANKETA"))
    repo.seed_recipient(make_primalac(o1.id, 1))
    repo.seed_recipient(make_primalac(o2.id, 1))
    service, _ = _service(repo)
    res = service.list_inbox(_korisnik(1), 1, 20, "ALL", "ANKETA")
    assert res["total"] == 1 and res["items"][0]["kategorija"]["sifra"] == "ANKETA"


def test_unread_count_only_available():
    repo = _repo_with()
    avail = repo.seed_notification(make_obavestenje())
    expired = repo.seed_notification(
        make_obavestenje(datum_isteka=FIXED_NOW - datetime.timedelta(days=1))
    )
    repo.seed_recipient(make_primalac(avail.id, 1, procitano="N"))
    repo.seed_recipient(make_primalac(expired.id, 1, procitano="N"))
    service, _ = _service(repo)
    assert service.unread_count(_korisnik(1)) == 1


# ------------------------------------------------------------------ detalj
def test_detail_includes_sadrzaj_and_no_state_change():
    repo = _repo_with()
    o = repo.seed_notification(make_obavestenje(sadrzaj="Pun tekst"))
    p = repo.seed_recipient(make_primalac(o.id, 1, procitano="N"))
    service, _ = _service(repo)
    detail = service.get_detail(_korisnik(1), o.id)
    assert detail["sadrzaj"] == "Pun tekst"
    assert detail["procitano"] is False
    # Detalj ne menja read stanje.
    assert p.procitano == "N" and p.datum_citanja is None


def test_detail_foreign_notification_not_found():
    repo = _repo_with()
    o = repo.seed_notification(make_obavestenje())
    repo.seed_recipient(make_primalac(o.id, korisnik_id=2))
    service, _ = _service(repo)
    with pytest.raises(NotificationNotFoundError):
        service.get_detail(_korisnik(1), o.id)


# ------------------------------------------------------------------ read/unread
def test_mark_read_sets_date_and_audits():
    repo = _repo_with()
    o = repo.seed_notification(make_obavestenje())
    repo.seed_recipient(make_primalac(o.id, 1, procitano="N"))
    service, audit = _service(repo)
    primalac, unread = service.mark_read(_korisnik(1), o.id)
    assert primalac.procitano == "D" and primalac.datum_citanja == FIXED_NOW
    assert unread == 0
    assert any(e["sifra_akcije"] == AuditAction.NOTIFICATION_READ for e in audit.entries)


def test_repeated_read_keeps_original_date():
    repo = _repo_with()
    o = repo.seed_notification(make_obavestenje())
    earlier = FIXED_NOW - datetime.timedelta(hours=2)
    repo.seed_recipient(make_primalac(o.id, 1, procitano="D", datum_citanja=earlier))
    service, audit = _service(repo)
    primalac, _ = service.mark_read(_korisnik(1), o.id)
    # Originalni datum se ne menja; nema novog audit zapisa.
    assert primalac.datum_citanja == earlier
    assert not any(e["sifra_akcije"] == AuditAction.NOTIFICATION_READ for e in audit.entries)


def test_mark_unread_clears_date():
    repo = _repo_with()
    o = repo.seed_notification(make_obavestenje())
    repo.seed_recipient(make_primalac(o.id, 1, procitano="D", datum_citanja=FIXED_NOW))
    service, audit = _service(repo)
    primalac, unread = service.mark_unread(_korisnik(1), o.id)
    assert primalac.procitano == "N" and primalac.datum_citanja is None
    assert unread == 1
    assert any(e["sifra_akcije"] == AuditAction.NOTIFICATION_MARKED_UNREAD for e in audit.entries)


def test_repeated_unread_safe():
    repo = _repo_with()
    o = repo.seed_notification(make_obavestenje())
    repo.seed_recipient(make_primalac(o.id, 1, procitano="N"))
    service, _ = _service(repo)
    primalac, _ = service.mark_unread(_korisnik(1), o.id)
    primalac, _ = service.mark_unread(_korisnik(1), o.id)
    assert primalac.procitano == "N" and primalac.datum_citanja is None


def test_mark_read_foreign_not_found():
    repo = _repo_with()
    o = repo.seed_notification(make_obavestenje())
    repo.seed_recipient(make_primalac(o.id, korisnik_id=2))
    service, _ = _service(repo)
    with pytest.raises(NotificationNotFoundError):
        service.mark_read(_korisnik(1), o.id)


def test_mark_read_expired_not_found():
    repo = _repo_with()
    o = repo.seed_notification(
        make_obavestenje(datum_isteka=FIXED_NOW - datetime.timedelta(days=1))
    )
    repo.seed_recipient(make_primalac(o.id, 1))
    service, _ = _service(repo)
    with pytest.raises(NotificationNotFoundError):
        service.mark_read(_korisnik(1), o.id)


def test_published_without_expiry_not_available():
    # DDL ugovor: PUBLISHED bez DATUM_ISTEKA se tretira kao nedostupno.
    repo = _repo_with()
    o = repo.seed_notification(make_obavestenje(datum_isteka=None))
    repo.seed_recipient(make_primalac(o.id, 1))
    service, _ = _service(repo)
    assert service.list_inbox(_korisnik(1), 1, 20, "ALL", None)["total"] == 0
    with pytest.raises(NotificationNotFoundError):
        service.get_detail(_korisnik(1), o.id)


def test_mark_read_rolls_back_without_commit_on_count_failure():
    # count_unread se racuna PRE commit-a; ako padne, rollback i BEZ commit-a.
    repo = _repo_with()
    o = repo.seed_notification(make_obavestenje())
    repo.seed_recipient(make_primalac(o.id, 1, procitano="N"))
    service, _ = _service(repo)

    def _boom(*a, **k):
        raise RuntimeError("count pukao")

    repo.count_unread = _boom
    with pytest.raises(RuntimeError):
        service.mark_read(_korisnik(1), o.id)
    assert service.db.committed == 0
    assert service.db.rolled_back == 1
