"""Servisni testovi za AdminConfigurationService (fake repository/audit, bez DB)."""

import pytest

from app.core.configuration_definitions import ALLOWED_CONFIGURATION_KEYS
from app.core.exceptions import ConfigurationKeyNotAllowedError, ValidationBusinessError
from app.services.admin_configuration_service import AdminConfigurationService
from app.services.audit_service import AuditAction
from tests.admin_configuration_fakes import FakeAdminConfigurationRepository, FakeDb, FakeKonfiguracijaRow
from tests.fakes import FakeAuditService, FakeSystemNotificationService, make_korisnik


def _service(rows=None, audit=None):
    store: dict = {}
    repo = FakeAdminConfigurationRepository(rows, store=store)
    db = FakeDb(store=store)
    audit_service = audit or FakeAuditService()
    service = AdminConfigurationService(
        db,
        repository=repo,
        audit_service=audit_service,
        system_notification_service=FakeSystemNotificationService(),
    )
    return service, db, repo, audit_service


def _admin():
    return make_korisnik(id=1, platni_broj="admin1")


# =============================================================== GET / lista
def test_list_configuration_returns_exactly_9_keys_in_stable_order():
    service, *_ = _service()
    result = service.list_configuration()
    keys = [item["kljuc"] for item in result["items"]]
    assert keys == list(ALLOWED_CONFIGURATION_KEYS)
    assert len(keys) == 9


def test_list_configuration_missing_row_uses_default():
    service, *_ = _service()
    result = service.list_configuration()
    item = next(i for i in result["items"] if i["kljuc"] == "MAX_IDEJA_PO_CIKLUSU")
    assert item["vrednost"] == "3"
    assert item["koristi_podrazumevanu_vrednost"] is True
    assert item["izmenio_korisnik_id"] is None


def test_list_configuration_inactive_row_uses_default():
    rows = [FakeKonfiguracijaRow("TOP_IDEAS_COUNT", "99", "BROJ", "x", aktivna="N", izmenio_korisnik_id=5)]
    service, *_ = _service(rows)
    result = service.list_configuration()
    item = next(i for i in result["items"] if i["kljuc"] == "TOP_IDEAS_COUNT")
    assert item["vrednost"] == "10"
    assert item["koristi_podrazumevanu_vrednost"] is True


def test_list_configuration_existing_active_row():
    rows = [FakeKonfiguracijaRow("MAX_IDEJA_PO_CIKLUSU", "7", "BROJ", "opis", izmenio_korisnik_id=42)]
    service, *_ = _service(rows)
    result = service.list_configuration()
    item = next(i for i in result["items"] if i["kljuc"] == "MAX_IDEJA_PO_CIKLUSU")
    assert item["vrednost"] == "7"
    assert item["koristi_podrazumevanu_vrednost"] is False
    assert item["izmenio_korisnik_id"] == 42


def test_list_configuration_batch_read_single_call():
    """Batch citanje bez N+1: list_active_by_keys se poziva TACNO jednom."""
    rows = [FakeKonfiguracijaRow("MAX_IDEJA_PO_CIKLUSU", "7", "BROJ", "opis")]
    service, db, repo, _ = _service(rows)

    call_count = {"n": 0}
    original = repo.list_active_by_keys

    def counting(keys):
        call_count["n"] += 1
        return original(keys)

    repo.list_active_by_keys = counting
    service.list_configuration()
    assert call_count["n"] == 1


def test_list_configuration_never_exposes_secrets():
    service, *_ = _service()
    result = service.list_configuration()
    dumped = str(result)
    for forbidden in ("DB_PASSWORD", "PORTAL_SERVICE_KEY", "RESET_CODE_PEPPER", "FCM_CREDENTIALS"):
        assert forbidden not in dumped


# =============================================================== PUT / izmena
def test_update_unknown_key_404():
    service, *_ = _service()
    with pytest.raises(ConfigurationKeyNotAllowedError):
        service.update_configuration(_admin(), "NEPOSTOJECI_KLJUC", "1")


def test_update_key_normalized_trim_uppercase():
    service, db, repo, audit = _service()
    result = service.update_configuration(_admin(), "  max_ideja_po_ciklusu  ", "5")
    assert result["kljuc"] == "MAX_IDEJA_PO_CIKLUSU"
    assert result["vrednost"] == "5"
    assert db.committed == 1


@pytest.mark.parametrize(
    "kljuc,minimum,maximum",
    [
        ("MIN_DUZINA_LOZINKE", 8, 128),
        ("MAX_NEUSPESNIH_PRIJAVA", 1, 10),
        ("TRAJANJE_RESET_KODA_MIN", 1, 1440),
        ("MAX_IDEJA_PO_CIKLUSU", 1, 100),
        ("TOP_IDEAS_COUNT", 1, 100),
        ("NOTIFICATION_DEFAULT_EXPIRY_DAYS", 1, 365),
    ],
)
def test_update_numeric_range_boundaries(kljuc, minimum, maximum):
    service, *_ = _service()
    ok_min = service.update_configuration(_admin(), kljuc, str(minimum))
    assert ok_min["vrednost"] == str(minimum)
    ok_max = service.update_configuration(_admin(), kljuc, str(maximum))
    assert ok_max["vrednost"] == str(maximum)

    with pytest.raises(ValidationBusinessError):
        service.update_configuration(_admin(), kljuc, str(minimum - 1))
    with pytest.raises(ValidationBusinessError):
        service.update_configuration(_admin(), kljuc, str(maximum + 1))


@pytest.mark.parametrize("bad_value", ["3.5", "", "   ", "abc", "3,5", "1e2"])
def test_update_numeric_rejects_decimal_empty_non_numeric(bad_value):
    service, *_ = _service()
    with pytest.raises(ValidationBusinessError):
        service.update_configuration(_admin(), "MAX_IDEJA_PO_CIKLUSU", bad_value)


def test_update_numeric_key_null_rejected():
    service, *_ = _service()
    with pytest.raises(ValidationBusinessError):
        service.update_configuration(_admin(), "MAX_IDEJA_PO_CIKLUSU", None)


def test_update_creates_row_when_missing():
    service, db, repo, _ = _service()
    service.update_configuration(_admin(), "MAX_IDEJA_PO_CIKLUSU", "5")
    assert len(db.added) == 1
    created = db.added[0]
    assert created.kljuc == "MAX_IDEJA_PO_CIKLUSU"
    assert created.vrednost == "5"
    assert created.aktivna == "D"
    assert created.tip_podatka == "BROJ"


def test_update_reactivates_inactive_row_instead_of_inserting():
    rows = [FakeKonfiguracijaRow("MAX_IDEJA_PO_CIKLUSU", "9", "BROJ", "stari opis", aktivna="N")]
    service, db, repo, _ = _service(rows)
    result = service.update_configuration(_admin(), "MAX_IDEJA_PO_CIKLUSU", "5")
    assert result["vrednost"] == "5"
    assert db.added == []  # nema insert-a, postojeci red je reaktiviran
    assert repo.rows["MAX_IDEJA_PO_CIKLUSU"].aktivna == "D"


def test_update_uses_select_for_update():
    service, db, repo, _ = _service()
    service.update_configuration(_admin(), "MAX_IDEJA_PO_CIKLUSU", "5")
    assert repo.for_update_calls == ["MAX_IDEJA_PO_CIKLUSU"]


def test_update_sets_izmenio_korisnik_id_to_acting_admin():
    admin = _admin()
    service, *_ = _service()
    result = service.update_configuration(admin, "MAX_IDEJA_PO_CIKLUSU", "5")
    assert result["izmenio_korisnik_id"] == admin.id


def test_update_tip_podatka_and_opis_come_from_definition_not_request():
    service, db, repo, _ = _service()
    service.update_configuration(_admin(), "MAX_IDEJA_PO_CIKLUSU", "5")
    row = repo.rows["MAX_IDEJA_PO_CIKLUSU"]
    assert row.tip_podatka == "BROJ"
    assert "ciklusu" in row.opis.lower()


# ==================================================================== download_url
def test_download_url_valid_https_accepted():
    service, *_ = _service()
    result = service.update_configuration(_admin(), "DOWNLOAD_URL", "https://cdn.example.com/app.apk")
    assert result["vrednost"] == "https://cdn.example.com/app.apk"


def test_download_url_null_accepted():
    rows = [FakeKonfiguracijaRow("DOWNLOAD_URL", "https://old.example.com", "TEKST", "opis")]
    service, *_ = _service(rows)
    result = service.update_configuration(_admin(), "DOWNLOAD_URL", None)
    assert result["vrednost"] is None


@pytest.mark.parametrize(
    "bad_url",
    [
        "http://example.com/app.apk",
        "file:///etc/passwd",
        "content://provider/app.apk",
        "javascript:alert(1)",
        "ftp://example.com/app.apk",
        "https://",
        "not-a-url",
        "   ",
    ],
)
def test_download_url_rejects_non_https_schemes(bad_url):
    service, *_ = _service()
    with pytest.raises(ValidationBusinessError):
        service.update_configuration(_admin(), "DOWNLOAD_URL", bad_url)


def test_download_url_too_long_rejected():
    service, *_ = _service()
    too_long = "https://example.com/" + ("a" * 1000)
    with pytest.raises(ValidationBusinessError):
        service.update_configuration(_admin(), "DOWNLOAD_URL", too_long)


def test_only_download_url_may_be_null():
    service, *_ = _service()
    with pytest.raises(ValidationBusinessError):
        service.update_configuration(_admin(), "CURRENT_VERSION", None)


# ============================================================ download_url rubni slucajevi
def test_download_url_empty_host_with_port_only_rejected():
    service, *_ = _service()
    with pytest.raises(ValidationBusinessError):
        service.update_configuration(_admin(), "DOWNLOAD_URL", "https://:443/app.apk")


def test_download_url_malformed_ipv6_bracket_rejected():
    service, *_ = _service()
    with pytest.raises(ValidationBusinessError):
        service.update_configuration(_admin(), "DOWNLOAD_URL", "https://[::1")


def test_download_url_with_username_password_rejected():
    service, *_ = _service()
    with pytest.raises(ValidationBusinessError):
        service.update_configuration(_admin(), "DOWNLOAD_URL", "https://user:pass@example.com/app.apk")


def test_download_url_control_characters_rejected():
    service, *_ = _service()
    with pytest.raises(ValidationBusinessError):
        service.update_configuration(_admin(), "DOWNLOAD_URL", "https://example.com/app\x00.apk")


def test_download_url_valid_still_passes():
    service, *_ = _service()
    result = service.update_configuration(_admin(), "DOWNLOAD_URL", "https://cdn.example.com/app.apk")
    assert result["vrednost"] == "https://cdn.example.com/app.apk"


# ==================================================================== granice duzine
def test_version_value_over_50_chars_rejected():
    service, *_ = _service()
    too_long = "1." + "2" * 49  # 51 karaktera, i dalje "validan" oblik osim duzine
    with pytest.raises(ValidationBusinessError):
        service.update_configuration(_admin(), "CURRENT_VERSION", too_long)


def test_version_value_exactly_50_chars_accepted():
    service, *_ = _service()
    exactly_50 = "1." + "2" * 48  # ukupno 50 karaktera
    assert len(exactly_50) == 50
    result = service.update_configuration(_admin(), "CURRENT_VERSION", exactly_50)
    assert result["vrednost"] == exactly_50


def test_numeric_value_over_20_chars_rejected_without_500():
    service, *_ = _service()
    huge_number = "9" * 21
    with pytest.raises(ValidationBusinessError):
        service.update_configuration(_admin(), "MAX_IDEJA_PO_CIKLUSU", huge_number)


def test_numeric_value_extremely_huge_never_500():
    """Ogroman broj cifara (daleko iznad 20) ne sme izazvati 500/OverflowError - mora
    biti uhvacen pre bilo kakvog int() poziva."""
    service, *_ = _service()
    astronomically_huge = "1" * 5000
    with pytest.raises(ValidationBusinessError):
        service.update_configuration(_admin(), "MAX_IDEJA_PO_CIKLUSU", astronomically_huge)


# ==================================================================== verzije
@pytest.mark.parametrize(
    "value",
    ["1", "1.0", "1.2.3", "1.2.3.4", "1.10", "10.20.30.40"],
)
def test_version_format_accepted(value):
    service, *_ = _service()
    result = service.update_configuration(_admin(), "CURRENT_VERSION", value)
    assert result["vrednost"] == value


@pytest.mark.parametrize(
    "value",
    ["v1.0", "1.0 ", " 1.0", "1.0-beta", "1.a", "1.2.3.4.5", "", "abc", "1..2"],
)
def test_version_format_rejected(value):
    service, *_ = _service()
    with pytest.raises(ValidationBusinessError):
        service.update_configuration(_admin(), "CURRENT_VERSION", value)


def test_version_numeric_comparison_1_10_greater_than_1_9():
    rows = [FakeKonfiguracijaRow("MIN_SUPPORTED_VERSION", "1.9", "TEKST", "opis")]
    service, *_ = _service(rows)
    # 1.10 > 1.9 numerički - dozvoljeno da CURRENT_VERSION bude 1.10 kad je min 1.9.
    result = service.update_configuration(_admin(), "CURRENT_VERSION", "1.10")
    assert result["vrednost"] == "1.10"


def test_min_supported_version_greater_than_current_422():
    rows = [FakeKonfiguracijaRow("CURRENT_VERSION", "1.5", "TEKST", "opis")]
    service, *_ = _service(rows)
    with pytest.raises(ValidationBusinessError):
        service.update_configuration(_admin(), "MIN_SUPPORTED_VERSION", "1.6")


def test_current_version_dropped_below_minimum_422():
    rows = [FakeKonfiguracijaRow("MIN_SUPPORTED_VERSION", "1.5", "TEKST", "opis")]
    service, *_ = _service(rows)
    with pytest.raises(ValidationBusinessError):
        service.update_configuration(_admin(), "CURRENT_VERSION", "1.4")


def test_version_check_applies_when_sibling_row_missing_uses_default():
    # Nema MIN_SUPPORTED_VERSION reda -> default je "1.0". CURRENT_VERSION ne sme ispod toga.
    service, *_ = _service()
    with pytest.raises(ValidationBusinessError):
        service.update_configuration(_admin(), "CURRENT_VERSION", "0.9")


def test_version_equal_with_zero_padding_is_allowed():
    rows = [FakeKonfiguracijaRow("MIN_SUPPORTED_VERSION", "1.2", "TEKST", "opis")]
    service, *_ = _service(rows)
    result = service.update_configuration(_admin(), "CURRENT_VERSION", "1.2.0")
    assert result["vrednost"] == "1.2.0"


# ============================================================ zakljucavanje verzijskog para
def test_current_version_update_locks_both_keys_via_batch():
    rows = [FakeKonfiguracijaRow("MIN_SUPPORTED_VERSION", "1.0", "TEKST", "opis")]
    service, db, repo, _ = _service(rows)
    service.update_configuration(_admin(), "CURRENT_VERSION", "1.5")
    assert repo.for_update_batch_calls == [["CURRENT_VERSION", "MIN_SUPPORTED_VERSION"]]
    assert repo.for_update_calls == []  # single-key get_for_update se NE koristi za verzije


def test_min_supported_version_update_locks_both_keys_via_batch():
    rows = [FakeKonfiguracijaRow("CURRENT_VERSION", "1.5", "TEKST", "opis")]
    service, db, repo, _ = _service(rows)
    service.update_configuration(_admin(), "MIN_SUPPORTED_VERSION", "1.2")
    assert repo.for_update_batch_calls == [["CURRENT_VERSION", "MIN_SUPPORTED_VERSION"]]
    assert repo.for_update_calls == []


def test_non_version_key_still_uses_single_row_get_for_update():
    service, db, repo, _ = _service()
    service.update_configuration(_admin(), "MAX_IDEJA_PO_CIKLUSU", "5")
    assert repo.for_update_calls == ["MAX_IDEJA_PO_CIKLUSU"]
    assert repo.for_update_batch_calls == []


# ==================================================================== audit / idempotencija
def test_update_writes_audit_action():
    service, db, repo, audit = _service()
    service.update_configuration(_admin(), "MAX_IDEJA_PO_CIKLUSU", "5")
    assert len(audit.entries) == 1
    entry = audit.entries[0]
    assert entry["sifra_akcije"] == AuditAction.ADMIN_CONFIGURATION_UPDATED
    assert entry["tip_entiteta"] == "KONFIGURACIJA"
    assert entry["entitet_id"] == "MAX_IDEJA_PO_CIKLUSU"


def test_audit_detalji_never_contain_value():
    service, db, repo, audit = _service()
    service.update_configuration(_admin(), "DOWNLOAD_URL", "https://example.com/app.apk")
    entry = audit.entries[0]
    dumped = str(entry)
    assert "https://example.com/app.apk" not in dumped


def test_idempotent_put_same_value_no_duplicate_audit():
    service, db, repo, audit = _service()
    service.update_configuration(_admin(), "MAX_IDEJA_PO_CIKLUSU", "5")
    assert len(audit.entries) == 1
    service.update_configuration(_admin(), "MAX_IDEJA_PO_CIKLUSU", "5")
    assert len(audit.entries) == 1  # drugi identican PUT ne dodaje novi audit zapis
    assert db.committed == 2  # ali se i dalje commituje (bezopasno, nema promene)


def test_idempotent_put_matching_default_no_audit_on_first_write():
    service, db, repo, audit = _service()
    service.update_configuration(_admin(), "MAX_IDEJA_PO_CIKLUSU", "3")  # "3" je vec default
    assert audit.entries == []
    assert len(db.added) == 1  # red se ipak kreira


# ==================================================================== rollback
def test_rollback_when_audit_log_raises():
    class RaisingAudit:
        def log(self, *a, **kw):
            raise RuntimeError("audit down")

    service, db, repo, _ = _service(audit=RaisingAudit())
    with pytest.raises(RuntimeError):
        service.update_configuration(_admin(), "MAX_IDEJA_PO_CIKLUSU", "5")
    assert db.rolled_back == 1
    assert db.committed == 0


def test_rollback_when_commit_raises():
    class RaisingCommitDb(FakeDb):
        def commit(self):
            raise RuntimeError("commit down")

    db = RaisingCommitDb()
    repo = FakeAdminConfigurationRepository()
    service = AdminConfigurationService(db, repository=repo, audit_service=FakeAuditService())
    with pytest.raises(RuntimeError):
        service.update_configuration(_admin(), "MAX_IDEJA_PO_CIKLUSU", "5")
    assert db.rolled_back == 1


def test_no_db_queries_after_commit():
    """Response se sastavlja pre commit-a; get_for_update/list_active_by_keys se ne
    pozivaju ponovo nakon commit-a."""
    service, db, repo, _ = _service()
    calls_before = []

    original_commit = db.commit

    def spy_commit():
        calls_before.append((len(repo.for_update_calls),))
        original_commit()

    db.commit = spy_commit
    service.update_configuration(_admin(), "MAX_IDEJA_PO_CIKLUSU", "5")
    # for_update pozvan tacno jednom, PRE commit-a (spy je zabelezio isto stanje
    # kao i posle - znaci da se posle commit-a nije pozvao jos jednom)
    assert repo.for_update_calls == ["MAX_IDEJA_PO_CIKLUSU"]
    assert calls_before[0][0] == 1


# ================================================== sistemska obavestenja (enqueue hook)
def test_current_version_change_enqueues_app_version_changed():
    service, db, repo, audit = _service()
    service.update_configuration(_admin(), "CURRENT_VERSION", "2.0")

    calls = [c for c in service.system_notifications.calls if c[0] == "enqueue_app_version_changed"]
    assert calls == [("enqueue_app_version_changed", ("2.0",))]


def test_current_version_idempotent_put_does_not_enqueue_again():
    service, db, repo, audit = _service()
    service.update_configuration(_admin(), "CURRENT_VERSION", "2.0")
    service.update_configuration(_admin(), "CURRENT_VERSION", "2.0")

    calls = [c for c in service.system_notifications.calls if c[0] == "enqueue_app_version_changed"]
    assert calls == [("enqueue_app_version_changed", ("2.0",))]


def test_other_key_change_does_not_enqueue_app_version_changed():
    service, db, repo, audit = _service()
    service.update_configuration(_admin(), "MAX_IDEJA_PO_CIKLUSU", "5")

    assert service.system_notifications.calls == []
