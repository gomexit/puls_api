from sqlalchemy.dialects import oracle

from app.repositories.korisnik_repository import KorisnikRepository
from app.services.provisioning_service import ProvisioningService
from tests.fakes import (
    FakeAuditService,
    FakeDb,
    FakeKorisnikRepository,
    FakeSmsProvider,
    make_korisnik,
)


def build_provisioning_service(korisnici, sms_should_succeed=True):
    korisnik_repository = FakeKorisnikRepository(korisnici)
    sms_provider = FakeSmsProvider(should_succeed=sms_should_succeed)
    audit_service = FakeAuditService()
    service = ProvisioningService(korisnik_repository, sms_provider, audit_service)
    return service, korisnik_repository, sms_provider, audit_service


# --- Oracle SQL must stay lock-free (fixes ORA-02014) -----------------------------

def test_candidates_query_has_no_for_update_or_skip_locked():
    repo = KorisnikRepository(db=None)
    sql = str(repo.candidates_for_provisioning_query(limit=100).compile(dialect=oracle.dialect()))
    upper = sql.upper()
    assert "FOR UPDATE" not in upper
    assert "SKIP LOCKED" not in upper
    assert "ORDER BY" in upper


# --- provision_pending (worker batch) ---------------------------------------------

def test_candidate_with_valid_phone_gets_password():
    korisnik = make_korisnik(lozinka_hash=None, broj_telefona="060123456")
    service, _, sms, audit = build_provisioning_service([korisnik])
    db = FakeDb()

    result = service.provision_pending(db, batch_size=100)

    assert result.provisioned == 1
    assert korisnik.lozinka_hash is not None
    assert korisnik.datum_slanja_prve_lozinke is not None
    assert korisnik.obavezna_promena_lozinke == "D"
    assert len(sms.sent) == 1
    assert db.committed >= 1
    assert any(e["sifra_akcije"] == "PROVISIONING_USPESAN" for e in audit.entries)


def test_candidate_without_phone_is_skipped():
    korisnik = make_korisnik(lozinka_hash=None, broj_telefona=None)
    service, _, sms, audit = build_provisioning_service([korisnik])
    db = FakeDb()

    result = service.provision_pending(db, batch_size=100)

    assert result.skipped_no_phone == 1
    assert result.provisioned == 0
    assert korisnik.lozinka_hash is None
    assert sms.sent == []
    assert any(e["sifra_akcije"] == "PROVISIONING_GRESKA" for e in audit.entries)


def test_candidate_with_invalid_phone_is_skipped():
    korisnik = make_korisnik(lozinka_hash=None, broj_telefona="+381601234567")
    service, _, sms, audit = build_provisioning_service([korisnik])
    db = FakeDb()

    result = service.provision_pending(db, batch_size=100)

    assert result.skipped_invalid_phone == 1
    assert result.provisioned == 0
    assert korisnik.lozinka_hash is None
    assert sms.sent == []


def test_sms_failure_does_not_write_password_hash():
    korisnik = make_korisnik(lozinka_hash=None, broj_telefona="060123456")
    service, _, sms, audit = build_provisioning_service([korisnik], sms_should_succeed=False)
    db = FakeDb()

    result = service.provision_pending(db, batch_size=100)

    assert result.sms_errors == 1
    assert result.provisioned == 0
    assert korisnik.lozinka_hash is None
    assert any(e["sifra_akcije"] == "PROVISIONING_GRESKA" for e in audit.entries)


def test_one_failing_user_does_not_stop_others():
    good = make_korisnik(lozinka_hash=None, broj_telefona="060111111")
    bad = make_korisnik(lozinka_hash=None, broj_telefona="060222222")
    good2 = make_korisnik(lozinka_hash=None, broj_telefona="060333333")

    class ExplodingSms(FakeSmsProvider):
        def send_sms(self, phone_number, message):
            if phone_number == "060222222":
                raise RuntimeError("boom")
            return super().send_sms(phone_number, message)

    repo = FakeKorisnikRepository([good, bad, good2])
    service = ProvisioningService(repo, ExplodingSms(), FakeAuditService())
    db = FakeDb()

    result = service.provision_pending(db, batch_size=100)

    assert result.provisioned == 2  # good and good2 still processed
    assert result.errors == 1
    assert good.lozinka_hash is not None
    assert good2.lozinka_hash is not None
    assert bad.lozinka_hash is None


def test_batch_size_limits_pending_batch():
    korisnici = [make_korisnik(lozinka_hash=None, broj_telefona="060123456") for _ in range(5)]
    service, _, _, _ = build_provisioning_service(korisnici)
    db = FakeDb()

    result = service.provision_pending(db, batch_size=2)

    assert result.total_candidates == 2


# --- provision_all_pending (one-shot loop) ----------------------------------------

def test_all_valid_candidates_are_processed():
    korisnici = [make_korisnik(lozinka_hash=None, broj_telefona="060123456") for _ in range(5)]
    service, _, sms, _ = build_provisioning_service(korisnici)
    db = FakeDb()

    result = service.provision_all_pending(db)

    assert result.total_candidates == 5
    assert result.provisioned == 5
    assert all(k.lozinka_hash is not None for k in korisnici)


def test_one_shot_terminates_when_only_unprovisionable_remain():
    # Every candidate has an invalid phone: nothing can be provisioned, must still stop.
    korisnici = [make_korisnik(lozinka_hash=None, broj_telefona="+381601234567") for _ in range(3)]
    service, _, sms, _ = build_provisioning_service(korisnici)
    db = FakeDb()

    result = service.provision_all_pending(db)

    assert result.provisioned == 0
    assert result.skipped_invalid_phone == 3  # counted exactly once each
    assert result.total_candidates == 3
    assert sms.sent == []


def test_one_shot_no_double_counting_mixed():
    valid = [make_korisnik(lozinka_hash=None, broj_telefona="060123456") for _ in range(2)]
    invalid = [make_korisnik(lozinka_hash=None, broj_telefona=None) for _ in range(2)]
    service, _, _, _ = build_provisioning_service(valid + invalid)
    db = FakeDb()

    result = service.provision_all_pending(db)

    assert result.provisioned == 2
    assert result.skipped_no_phone == 2  # each skipped user counted once
    assert result.total_candidates == 4


# --- SMS poruka sa linkom za preuzimanje (DOWNLOAD_URL iz PULS_KONFIGURACIJA) ------

from app.services.provisioning_service import (  # noqa: E402
    SMS_MAX_LENGTH,
    build_initial_password_sms,
)

URL = "https://puls.gomex.rs/apk/index.html"
LOZINKA = "Ab3dEf7hJk9m"  # generate_temporary_password() uvek daje 12 karaktera


def test_sms_with_link_is_single_line_link_first_password_last():
    msg = build_initial_password_sms(LOZINKA, URL)
    assert msg == f"Preuzmite aplikaciju PULS: {URL} Vasa privremena lozinka: {LOZINKA}"
    assert "\n" not in msg and "\r" not in msg  # gateway ne isporucuje prelom reda
    assert msg.endswith(LOZINKA)  # nista iza lozinke
    assert len(msg) == 101 <= SMS_MAX_LENGTH


def test_sms_without_url_is_password_only():
    assert build_initial_password_sms(LOZINKA, None) == f"Vasa privremena lozinka za PULS je: {LOZINKA}"


def test_sms_drops_link_when_too_long():
    huge_url = "https://puls.gomex.rs/" + "y" * 120
    assert build_initial_password_sms(LOZINKA, huge_url) == f"Vasa privremena lozinka za PULS je: {LOZINKA}"


def test_sms_never_exceeds_limit_and_never_has_newline():
    for n in range(0, 200):
        msg = build_initial_password_sms(LOZINKA, "https://p.rs/" + "z" * n)
        assert len(msg) <= SMS_MAX_LENGTH
        assert "\n" not in msg
        assert msg.endswith(LOZINKA)


def test_provisioning_sends_download_page_link():
    korisnik = make_korisnik(lozinka_hash=None, broj_telefona="060123456")
    service, _, sms, _ = build_provisioning_service([korisnik])

    service.provision_pending(FakeDb(), batch_size=100)

    _, message = sms.sent[0]
    assert message.startswith(f"Preuzmite aplikaciju PULS: {URL} Vasa privremena lozinka: ")
    assert "\n" not in message
    assert ".apk" not in message.lower()  # operateri blokiraju direktne .apk linkove
    assert len(message) == 101 <= SMS_MAX_LENGTH
