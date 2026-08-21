import datetime
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from app.core.exceptions import (
    ActiveIdeaCycleAlreadyExistsError,
    InvalidIdeaStatusTransitionError,
    ValidationBusinessError,
)
from app.services.idea_admin_service import IdeaAdminService
from tests.fakes import (
    FakeAuditService,
    FakeDb,
    FakeIdeaCycleRepository,
    FakeIdeaRepository,
    FakeSystemNotificationService,
    make_ciklus,
    make_ideja,
    make_korisnik,
)


def make_admin_service(cycles=None, ideje=None):
    db = FakeDb()
    cycle_repo = FakeIdeaCycleRepository(cycles)
    idea_repo = FakeIdeaRepository(ideje)
    audit = FakeAuditService()
    service = IdeaAdminService(
        db=db,
        idea_repository=idea_repo,
        cycle_repository=cycle_repo,
        audit_service=audit,
        system_notification_service=FakeSystemNotificationService(),
    )
    return service, db, cycle_repo, idea_repo, audit


def _actor():
    return make_korisnik(id=1, platni_broj="admin1")


def test_create_planiran_cycle():
    service, db, _, _, audit = make_admin_service()
    now = datetime.datetime.now()

    ciklus = service.create_cycle(
        _actor(), "Ciklus 1", now, now + datetime.timedelta(days=5)
    )

    assert ciklus.status == "PLANIRAN"
    assert db.committed == 1
    assert any(e["sifra_akcije"] == "IDEA_CYCLE_CREATED" for e in audit.entries)


def test_create_cycle_end_before_start_rejected():
    service, _, _, _, _ = make_admin_service()
    now = datetime.datetime.now()

    with pytest.raises(ValidationBusinessError):
        service.create_cycle(_actor(), "Ciklus", now, now - datetime.timedelta(days=1))


def test_cannot_have_two_active_cycles():
    aktivan = make_ciklus(id=1, status="AKTIVAN")
    planiran = make_ciklus(id=2, status="PLANIRAN")
    service, db, _, _, _ = make_admin_service(cycles=[aktivan, planiran])

    with pytest.raises(ActiveIdeaCycleAlreadyExistsError):
        service.change_cycle_status(_actor(), planiran.id, "AKTIVAN")
    assert db.rolled_back == 1


def test_activate_planiran_cycle_succeeds():
    planiran = make_ciklus(id=2, status="PLANIRAN")
    service, db, _, _, audit = make_admin_service(cycles=[planiran])

    ciklus = service.change_cycle_status(_actor(), planiran.id, "AKTIVAN")

    assert ciklus.status == "AKTIVAN"
    assert db.committed == 1
    assert any(e["sifra_akcije"] == "IDEA_CYCLE_STATUS_CHANGED" for e in audit.entries)


class _CommitRaisesDb(FakeDb):
    """FakeDb ciji commit baca zadati IntegrityError (simulira DB unique konflikt)."""

    def __init__(self, error: IntegrityError):
        super().__init__()
        self._error = error

    def commit(self) -> None:
        raise self._error


def _integrity_error(message: str) -> IntegrityError:
    return IntegrityError("UPDATE ...", {}, Exception(message))


def test_concurrent_activation_maps_unique_index_to_business_error():
    # Pre-provera prolazi (0 aktivnih), ali DB commit odbija zbog unique indeksa.
    planiran = make_ciklus(id=2, status="PLANIRAN")
    err = _integrity_error(
        "ORA-00001: unique constraint (PORTAL.UX_IDEA_CIKLUS_JEDAN_AKTIVAN) violated"
    )
    db = _CommitRaisesDb(err)
    cycle_repo = FakeIdeaCycleRepository([planiran])
    service = IdeaAdminService(
        db=db, idea_repository=FakeIdeaRepository(), cycle_repository=cycle_repo,
        audit_service=FakeAuditService(),
        system_notification_service=FakeSystemNotificationService(),
    )

    with pytest.raises(ActiveIdeaCycleAlreadyExistsError):
        service.change_cycle_status(_actor(), planiran.id, "AKTIVAN")
    assert db.rolled_back == 1


def test_unrelated_integrity_error_is_not_masked():
    planiran = make_ciklus(id=2, status="PLANIRAN")
    err = _integrity_error("ORA-02291: integrity constraint (PORTAL.FK_NESTO) violated")
    db = _CommitRaisesDb(err)
    cycle_repo = FakeIdeaCycleRepository([planiran])
    service = IdeaAdminService(
        db=db, idea_repository=FakeIdeaRepository(), cycle_repository=cycle_repo,
        audit_service=FakeAuditService(),
        system_notification_service=FakeSystemNotificationService(),
    )

    with pytest.raises(IntegrityError):
        service.change_cycle_status(_actor(), planiran.id, "AKTIVAN")


def test_valid_idea_status_transition():
    ideja = make_ideja(id=10, status="POSLATA")
    service, db, _, _, audit = make_admin_service(ideje=[ideja])

    updated = service.change_idea_status(_actor(), ideja.id, "U_OBRADI")

    assert updated.status == "U_OBRADI"
    assert any(e["sifra_akcije"] == "IDEA_STATUS_CHANGED" for e in audit.entries)


def test_invalid_idea_status_transition():
    ideja = make_ideja(id=10, status="POSLATA")
    service, db, _, _, _ = make_admin_service(ideje=[ideja])

    with pytest.raises(InvalidIdeaStatusTransitionError):
        service.change_idea_status(_actor(), ideja.id, "NAGRAĐENA")
    assert db.rolled_back == 1


def test_hr_score_out_of_range_rejected():
    ideja = make_ideja(id=10)
    service, _, _, _, _ = make_admin_service(ideje=[ideja])

    with pytest.raises(ValidationBusinessError):
        service.set_hr_score(_actor(), ideja.id, 0)
    with pytest.raises(ValidationBusinessError):
        service.set_hr_score(_actor(), ideja.id, 11)


def test_konacna_ocena_stays_null_without_ai_score():
    ideja = make_ideja(id=10, ai_ocena=None)
    service, _, _, _, _ = make_admin_service(ideje=[ideja])

    updated = service.set_hr_score(_actor(), ideja.id, 8)

    assert updated.hr_ocena == 8
    assert updated.konacna_ocena is None


def test_konacna_ocena_computed_70_30_with_both_scores():
    ideja = make_ideja(id=10, ai_ocena=Decimal("6"))
    service, _, _, _, _ = make_admin_service(ideje=[ideja])

    updated = service.set_hr_score(_actor(), ideja.id, 10)

    # 10 * 0.70 + 6 * 0.30 = 7.00 + 1.80 = 8.80
    assert updated.konacna_ocena == Decimal("8.80")

# ================================================== sistemska obavestenja (enqueue hook)
def test_cycle_activation_enqueues_idea_cycle_activated():
    planiran = make_ciklus(id=2, status="PLANIRAN")
    service, db, _, _, _ = make_admin_service(cycles=[planiran])

    service.change_cycle_status(_actor(), planiran.id, "AKTIVAN")

    calls = [c for c in service.system_notifications.calls if c[0] == "enqueue_idea_cycle_activated"]
    assert calls == [("enqueue_idea_cycle_activated", (planiran.id,))]


def test_idea_status_to_top10_enqueues_idea_top10():
    ideja = make_ideja(id=10, status="ODOBRENA")
    service, db, _, _, _ = make_admin_service(ideje=[ideja])

    service.change_idea_status(_actor(), ideja.id, "TOP_10")

    calls = [c for c in service.system_notifications.calls if c[0] == "enqueue_idea_top_10"]
    assert calls == [("enqueue_idea_top_10", (ideja.id,))]


def test_idea_status_to_nagradjena_enqueues_idea_nagradjena():
    ideja = make_ideja(id=11, status="TOP_10")
    service, db, _, _, _ = make_admin_service(ideje=[ideja])

    service.change_idea_status(_actor(), ideja.id, "NAGRAĐENA")

    calls = [c for c in service.system_notifications.calls if c[0] == "enqueue_idea_nagradjena"]
    assert calls == [("enqueue_idea_nagradjena", (ideja.id,))]


def test_idea_status_to_odbijena_does_not_enqueue():
    ideja = make_ideja(id=12, status="POSLATA")
    service, db, _, _, _ = make_admin_service(ideje=[ideja])

    service.change_idea_status(_actor(), ideja.id, "ODBIJENA")

    assert service.system_notifications.calls == []
