import datetime
import logging

from sqlalchemy.orm import Session

from app.core.phone import is_valid_local_mobile_phone
from app.core.security import generate_temporary_password, hash_password
from app.models.korisnik import Korisnik
from app.repositories.korisnik_repository import KorisnikRepository
from app.services.audit_service import AuditAction, AuditService
from app.services.sms_service import SmsProvider

logger = logging.getLogger("puls.provisioning")


class ProvisioningResult:
    def __init__(self):
        self.total_candidates = 0
        self.provisioned = 0
        self.skipped_no_phone = 0
        self.skipped_invalid_phone = 0
        self.sms_errors = 0
        self.errors = 0

    def add(self, other: "ProvisioningResult") -> None:
        self.total_candidates += other.total_candidates
        self.provisioned += other.provisioned
        self.skipped_no_phone += other.skipped_no_phone
        self.skipped_invalid_phone += other.skipped_invalid_phone
        self.sms_errors += other.sms_errors
        self.errors += other.errors


class ProvisioningService:
    """Assigns a temporary password and sends it by SMS to newly synced employees.

    Single-instance worker: no distributed locking. Candidates are processed one by
    one and committed individually so one bad user never blocks the rest."""

    def __init__(
        self,
        korisnik_repository: KorisnikRepository,
        sms_provider: SmsProvider,
        audit_service: AuditService,
    ):
        self.korisnik_repository = korisnik_repository
        self.sms_provider = sms_provider
        self.audit_service = audit_service

    def provision_pending(self, db: Session, batch_size: int = 100) -> ProvisioningResult:
        """Provision one batch of candidates. Commits per user."""
        result = ProvisioningResult()
        candidates = self.korisnik_repository.list_candidates_for_provisioning(limit=batch_size)
        result.total_candidates = len(candidates)

        for korisnik in candidates:
            try:
                self._provision_one(korisnik, result)
                db.commit()
            except Exception:
                db.rollback()
                result.errors += 1
                logger.exception("Provisioning failed for platni_broj=%s", korisnik.platni_broj)

        return result

    def _provision_one(self, korisnik: Korisnik, result: ProvisioningResult) -> None:
        phone = korisnik.broj_telefona
        if not phone:
            result.skipped_no_phone += 1
            self.audit_service.log(
                AuditAction.PROVISIONING_GRESKA,
                korisnik_id=korisnik.id,
                platni_broj=korisnik.platni_broj,
                detalji="Korisnik nema broj telefona, provisioning preskočen.",
            )
            return

        if not is_valid_local_mobile_phone(phone):
            result.skipped_invalid_phone += 1
            self.audit_service.log(
                AuditAction.PROVISIONING_GRESKA,
                korisnik_id=korisnik.id,
                platni_broj=korisnik.platni_broj,
                detalji="Broj telefona nije u formatu 06XXXXXXX, provisioning preskočen.",
            )
            return

        temporary_password = generate_temporary_password()
        message = f"Vaša privremena lozinka za PULS je: {temporary_password}"
        if not self.sms_provider.send_sms(phone, message):
            result.sms_errors += 1
            self.audit_service.log(
                AuditAction.PROVISIONING_GRESKA,
                korisnik_id=korisnik.id,
                platni_broj=korisnik.platni_broj,
                detalji="Slanje SMS-a sa privremenom lozinkom nije uspelo.",
            )
            return

        korisnik.lozinka_hash = hash_password(temporary_password)
        korisnik.datum_slanja_prve_lozinke = datetime.datetime.now()
        korisnik.obavezna_promena_lozinke = "D"
        result.provisioned += 1
        self.audit_service.log(
            AuditAction.PROVISIONING_USPESAN,
            korisnik_id=korisnik.id,
            platni_broj=korisnik.platni_broj,
        )

    def provision_all_pending(self, db: Session) -> ProvisioningResult:
        """One-shot entry point: fetch every pending candidate once and process each,
        committing per user. A single query means each user is attempted exactly once
        (no double counting) and the loop always terminates. Suited to the small
        internal user base this system serves."""
        result = ProvisioningResult()
        candidates = self.korisnik_repository.list_candidates_for_provisioning()
        result.total_candidates = len(candidates)

        for korisnik in candidates:
            try:
                self._provision_one(korisnik, result)
                db.commit()
            except Exception:
                db.rollback()
                result.errors += 1
                logger.exception("Provisioning failed for platni_broj=%s", korisnik.platni_broj)

        return result
