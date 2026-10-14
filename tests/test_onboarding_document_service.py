"""OnboardingDocumentService: statusi, verzije, idempotentnost, transakcije i audit."""

import pytest

from app.core.config import Settings
from app.core.exceptions import (
    InvalidOnboardingDocumentStatusError,
    OnboardingDocumentArchivedError,
    OnboardingDocumentNotDraftError,
    OnboardingDocumentNotFoundError,
    ValidationBusinessError,
)
from app.services.audit_service import AuditAction
from app.services.onboarding_document_service import OnboardingDocumentService
from tests.fakes import FakeAuditService, make_korisnik
from tests.onboarding_document_fakes import (
    FIXED_NOW,
    FakeOnbDb,
    FakeOnboardingDocumentRepo,
    make_dokument,
    make_validated_pdf,
)

LATER = FIXED_NOW.replace(hour=12)


def _service(*docs, audit=None):
    db = FakeOnbDb()
    repo = FakeOnboardingDocumentRepo(db)
    for d in docs:
        repo.seed(d)
    audit = audit or FakeAuditService()
    service = OnboardingDocumentService(
        db=db,
        repository=repo,
        audit_service=audit,
        settings=Settings(_env_file=None),
        now_fn=lambda: LATER,
    )
    return service, db, repo, audit


def _actor(pb="hr1"):
    return make_korisnik(id=7, platni_broj=pb)


def _actions(audit):
    return [e["sifra_akcije"] for e in audit.entries]


# ---------------------------------------------------------------- employee
def test_employee_sees_only_published_sorted_by_redosled_then_id():
    d_draft = make_dokument(id=1, status="DRAFT", redosled=1)
    d_pub_b = make_dokument(id=3, status="PUBLISHED", redosled=2)
    d_pub_a = make_dokument(id=5, status="PUBLISHED", redosled=1)
    d_pub_c = make_dokument(id=4, status="PUBLISHED", redosled=2)
    d_arch = make_dokument(id=2, status="ARCHIVED", redosled=1)
    service, *_ = _service(d_draft, d_pub_b, d_pub_a, d_pub_c, d_arch)
    ids = [d["id"] for d in service.list_published()]
    assert ids == [5, 3, 4]  # redosled ASC, pa ID ASC; dupli redosled dozvoljen


def test_employee_view_has_no_blob_or_sha_and_expected_fields():
    service, *_ = _service(make_dokument(id=1, status="PUBLISHED"))
    view = service.list_published()[0]
    assert set(view) == {
        "id", "naziv", "opis", "originalni_naziv_fajla",
        "velicina_bajtova", "redosled", "verzija", "datum_objave",
    }
    assert "sadrzaj" not in view and "sha256" not in view


@pytest.mark.parametrize("status", ["DRAFT", "ARCHIVED"])
def test_employee_cannot_get_unpublished_detail_or_content(status):
    service, *_ = _service(make_dokument(id=1, status=status))
    with pytest.raises(OnboardingDocumentNotFoundError):
        service.get_published(1)
    with pytest.raises(OnboardingDocumentNotFoundError):
        service.get_published_content(1)


def test_employee_missing_document_not_found():
    service, *_ = _service()
    with pytest.raises(OnboardingDocumentNotFoundError):
        service.get_published(99)


def test_employee_content_returns_bytes_and_hash():
    dok = make_dokument(id=1, status="PUBLISHED")
    service, *_ = _service(dok)
    content = service.get_published_content(1)
    assert content.content == dok.sadrzaj and content.sha256 == dok.sha256
    assert content.size == dok.velicina_bajtova and content.mime_type == "application/pdf"


# ------------------------------------------------------------------ create
def test_create_makes_draft_with_actor_from_context_and_one_commit():
    service, db, repo, audit = _service()
    pdf = make_validated_pdf("Politika.pdf")
    view = service.create(_actor("hr1"), "  Politika  ", "Opis", 2, pdf)

    assert view["status"] == "DRAFT" and view["verzija"] == 1 and view["datum_objave"] is None
    assert view["naziv"] == "Politika" and view["redosled"] == 2
    assert view["kreirao_platni_broj"] == "hr1" and view["izmenio_platni_broj"] == "hr1"
    assert view["datum_kreiranja"] == LATER
    assert view["sha256"] == pdf.sha256
    assert db.committed == 1 and db.rolled_back == 0 and db.flushed >= 1
    assert repo.queries_after_commit == 0
    assert _actions(audit) == [AuditAction.ADMIN_ONBOARDING_DOCUMENT_CREATED]


def test_create_audit_has_no_pdf_content_or_full_hash():
    service, _, _, audit = _service()
    pdf = make_validated_pdf()
    service.create(_actor(), "N", None, 1, pdf)
    entry = audit.entries[0]
    detalji = entry["detalji"]
    assert pdf.sha256 not in detalji
    assert pdf.sha256[:16] not in detalji
    assert "document_id=" in detalji and "status=DRAFT" in detalji and "verzija=1" in detalji
    assert entry["tip_entiteta"] == "ONBOARDING_DOKUMENT"
    assert entry["korisnik_id"] == 7 and entry["platni_broj"] == "hr1"


def test_create_invalid_metadata_rejected_before_db_and_without_commit():
    service, db, repo, audit = _service()
    with pytest.raises(ValidationBusinessError):
        service.create(_actor(), "   ", None, 1, make_validated_pdf())
    assert db.committed == 0 and repo.added == [] and audit.entries == []


def test_create_rolls_back_when_flush_fails_and_leaves_no_partial_state():
    service, db, repo, audit = _service()
    db.fail_flush = True
    with pytest.raises(RuntimeError):
        service.create(_actor(), "N", None, 1, make_validated_pdf())
    assert db.committed == 0 and db.rolled_back == 1
    assert audit.entries == []  # audit se pise tek posle uspesnog flush-a


def test_create_rolls_back_when_audit_fails():
    class ExplodingAudit(FakeAuditService):
        def log(self, *a, **k):
            raise RuntimeError("audit pukao")

    service, db, _, _ = _service(audit=ExplodingAudit())
    with pytest.raises(RuntimeError):
        service.create(_actor(), "N", None, 1, make_validated_pdf())
    assert db.committed == 0 and db.rolled_back == 1


# ------------------------------------------------------------------ update
def test_update_metadata_changes_fields_and_audits_once():
    dok = make_dokument(id=1, status="DRAFT")
    service, db, repo, audit = _service(dok)
    view = service.update(_actor("hr2"), 1, "Novi naziv", "Novi opis", 5)
    assert (view["naziv"], view["opis"], view["redosled"]) == ("Novi naziv", "Novi opis", 5)
    assert view["izmenio_platni_broj"] == "hr2" and view["kreirao_platni_broj"] == "admin1"
    assert view["datum_izmene"] == LATER
    assert view["verzija"] == 1  # verzija se menja samo zamenom sadrzaja
    assert db.committed == 1 and repo.queries_after_commit == 0 and repo.for_update_calls == 1
    assert _actions(audit) == [AuditAction.ADMIN_ONBOARDING_DOCUMENT_UPDATED]


def test_update_works_for_published_document():
    service, _, _, audit = _service(make_dokument(id=1, status="PUBLISHED"))
    view = service.update(_actor(), 1, "Izmenjen", None, 1)
    assert view["status"] == "PUBLISHED" and view["opis"] is None
    assert len(audit.entries) == 1


def test_update_identical_metadata_creates_no_audit_and_no_change():
    dok = make_dokument(id=1, naziv="Naziv", opis="Opis", redosled=2)
    service, db, _, audit = _service(dok)
    view = service.update(_actor("hr9"), 1, " Naziv ", " Opis ", 2)
    assert audit.entries == []
    assert view["izmenio_platni_broj"] == "admin1" and view["datum_izmene"] == dok.datum_izmene
    assert db.committed == 1 and db.rolled_back == 0


def test_update_archived_is_rejected():
    service, db, _, audit = _service(make_dokument(id=1, status="ARCHIVED"))
    with pytest.raises(OnboardingDocumentArchivedError):
        service.update(_actor(), 1, "N", None, 1)
    assert db.committed == 0 and db.rolled_back == 1 and audit.entries == []


def test_update_not_found():
    service, db, _, _ = _service()
    with pytest.raises(OnboardingDocumentNotFoundError):
        service.update(_actor(), 404, "N", None, 1)
    assert db.committed == 0 and db.rolled_back == 1


# ----------------------------------------------------------- replace content
def test_replace_content_in_draft_increments_version_and_audits():
    dok = make_dokument(id=1, status="DRAFT")
    service, db, repo, audit = _service(dok)
    new_pdf = make_validated_pdf("novi.pdf", pages=3)
    view = service.replace_content(_actor("hr3"), 1, new_pdf)
    assert view["verzija"] == 2
    assert view["sha256"] == new_pdf.sha256 and view["velicina_bajtova"] == new_pdf.size
    assert view["originalni_naziv_fajla"] == "novi.pdf" and view["mime_tip"] == "application/pdf"
    assert view["izmenio_platni_broj"] == "hr3"
    assert dok.sadrzaj == new_pdf.content
    assert db.committed == 1 and repo.queries_after_commit == 0
    assert _actions(audit) == [AuditAction.ADMIN_ONBOARDING_DOCUMENT_CONTENT_REPLACED]


def test_replace_with_identical_pdf_is_noop_no_version_no_audit():
    dok = make_dokument(id=1, status="DRAFT")
    service, db, _, audit = _service(dok)
    same = make_validated_pdf()
    assert same.sha256 == dok.sha256
    view = service.replace_content(_actor(), 1, same)
    assert view["verzija"] == 1 and audit.entries == []
    assert db.committed == 1


def test_two_replacements_increment_version_twice():
    dok = make_dokument(id=1, status="DRAFT")
    service, *_ = _service(dok)
    service.replace_content(_actor(), 1, make_validated_pdf(pages=2))
    view = service.replace_content(_actor(), 1, make_validated_pdf(pages=3))
    assert view["verzija"] == 3


def test_replace_content_rejected_when_published_or_archived():
    for status, exc in (("PUBLISHED", OnboardingDocumentNotDraftError),
                        ("ARCHIVED", OnboardingDocumentArchivedError)):
        dok = make_dokument(id=1, status=status)
        service, db, _, audit = _service(dok)
        old = dok.sha256
        with pytest.raises(exc):
            service.replace_content(_actor(), 1, make_validated_pdf(pages=4))
        assert dok.sha256 == old and dok.verzija == 1
        assert db.committed == 0 and db.rolled_back == 1 and audit.entries == []


# ------------------------------------------------------------------ status
@pytest.mark.parametrize(
    "start, target, action, has_date",
    [
        ("DRAFT", "PUBLISHED", AuditAction.ADMIN_ONBOARDING_DOCUMENT_PUBLISHED, True),
        ("PUBLISHED", "DRAFT", AuditAction.ADMIN_ONBOARDING_DOCUMENT_UNPUBLISHED, False),
        ("DRAFT", "ARCHIVED", AuditAction.ADMIN_ONBOARDING_DOCUMENT_ARCHIVED, False),
        ("PUBLISHED", "ARCHIVED", AuditAction.ADMIN_ONBOARDING_DOCUMENT_ARCHIVED, True),
    ],
)
def test_allowed_status_transitions(start, target, action, has_date):
    dok = make_dokument(id=1, status=start)
    service, db, repo, audit = _service(dok)
    view = service.change_status(_actor("hr4"), 1, target)
    assert view["status"] == target and view["izmenio_platni_broj"] == "hr4"
    assert (view["datum_objave"] is not None) is has_date
    assert db.committed == 1 and repo.queries_after_commit == 0
    assert _actions(audit) == [action]


def test_publish_sets_datum_objave_to_now_and_unpublish_clears_it():
    dok = make_dokument(id=1, status="DRAFT")
    service, *_ = _service(dok)
    assert service.change_status(_actor(), 1, "PUBLISHED")["datum_objave"] == LATER
    assert service.change_status(_actor(), 1, "DRAFT")["datum_objave"] is None


def test_status_value_is_normalized():
    service, *_ = _service(make_dokument(id=1, status="DRAFT"))
    assert service.change_status(_actor(), 1, " published ")["status"] == "PUBLISHED"


def test_same_status_is_idempotent_without_audit():
    for status in ("DRAFT", "PUBLISHED", "ARCHIVED"):
        dok = make_dokument(id=1, status=status)
        service, db, _, audit = _service(dok)
        view = service.change_status(_actor(), 1, status)
        assert view["status"] == status and audit.entries == []
        assert db.committed == 1 and db.rolled_back == 0


@pytest.mark.parametrize("target", ["DRAFT", "PUBLISHED"])
def test_archived_is_terminal(target):
    service, db, _, audit = _service(make_dokument(id=1, status="ARCHIVED"))
    with pytest.raises(OnboardingDocumentArchivedError):
        service.change_status(_actor(), 1, target)
    assert db.committed == 0 and db.rolled_back == 1 and audit.entries == []


@pytest.mark.parametrize("value", ["DELETED", "", "   ", None, "publish"])
def test_unknown_status_is_rejected_before_db(value):
    service, db, repo, _ = _service(make_dokument(id=1))
    with pytest.raises(InvalidOnboardingDocumentStatusError):
        service.change_status(_actor(), 1, value)
    assert repo.for_update_calls == 0 and db.committed == 0


def test_status_change_rolls_back_when_audit_fails():
    class ExplodingAudit(FakeAuditService):
        def log(self, *a, **k):
            raise RuntimeError("audit pukao")

    dok = make_dokument(id=1, status="DRAFT")
    service, db, _, _ = _service(dok, audit=ExplodingAudit())
    with pytest.raises(RuntimeError):
        service.change_status(_actor(), 1, "PUBLISHED")
    assert db.committed == 0 and db.rolled_back == 1


# ----------------------------------------------------------- admin read
def test_admin_sees_all_statuses_and_filters():
    docs = [
        make_dokument(id=1, status="DRAFT", naziv="Alfa pravilnik", redosled=2),
        make_dokument(id=2, status="PUBLISHED", naziv="Beta uputstvo", redosled=1),
        make_dokument(id=3, status="ARCHIVED", naziv="Gama pravilnik", redosled=1),
    ]
    service, *_ = _service(*docs)
    assert [d["id"] for d in service.list_admin(None, None, 1, 20)["items"]] == [2, 3, 1]
    assert [d["id"] for d in service.list_admin("archived", None, 1, 20)["items"]] == [3]
    assert [d["id"] for d in service.list_admin(None, " PRAVILNIK ", 1, 20)["items"]] == [3, 1]
    page2 = service.list_admin(None, None, 2, 2)
    assert page2["total"] == 3 and [d["id"] for d in page2["items"]] == [1]


def test_admin_list_validates_status_filter_and_search_length():
    service, *_ = _service()
    with pytest.raises(InvalidOnboardingDocumentStatusError):
        service.list_admin("NEPOZNAT", None, 1, 20)
    with pytest.raises(ValidationBusinessError):
        service.list_admin(None, "x" * 201, 1, 20)


def test_admin_detail_contains_sha_and_actors_but_no_blob():
    service, *_ = _service(make_dokument(id=1))
    view = service.get_admin(1)
    assert len(view["sha256"]) == 64 and "sadrzaj" not in view
    assert {"kreirao_platni_broj", "izmenio_platni_broj", "datum_kreiranja", "datum_izmene"} <= set(view)


def test_admin_content_available_in_any_status():
    for status in ("DRAFT", "PUBLISHED", "ARCHIVED"):
        service, *_ = _service(make_dokument(id=1, status=status))
        assert service.get_admin_content(1).content.startswith(b"%PDF-")


# ---------------------------------------------- granice REDOSLED (NUMBER(10,0))
REDOSLED_MAX = 9_999_999_999


def test_create_with_maximum_redosled_passes():
    service, db, _, _ = _service()
    view = service.create(_actor(), "N", None, REDOSLED_MAX, make_validated_pdf())
    assert view["redosled"] == REDOSLED_MAX and db.committed == 1


def test_create_with_redosled_above_maximum_is_rejected_before_any_db_write():
    service, db, repo, audit = _service()
    with pytest.raises(ValidationBusinessError):
        service.create(_actor(), "N", None, REDOSLED_MAX + 1, make_validated_pdf())
    assert repo.added == [] and db.flushed == 0 and db.committed == 0 and audit.entries == []


def test_update_with_maximum_redosled_passes():
    service, db, _, _ = _service(make_dokument(id=1))
    assert service.update(_actor(), 1, "N", None, REDOSLED_MAX)["redosled"] == REDOSLED_MAX
    assert db.committed == 1


def test_update_with_redosled_above_maximum_is_rejected_before_lock_and_write():
    dok = make_dokument(id=1, redosled=3)
    service, db, repo, audit = _service(dok)
    with pytest.raises(ValidationBusinessError):
        service.update(_actor(), 1, "N", None, REDOSLED_MAX + 1)
    assert repo.for_update_calls == 0 and db.committed == 0 and audit.entries == []
    assert int(dok.redosled) == 3
