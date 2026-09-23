import logging

from app.core.config import get_settings
from app.db.session import SessionLocal, engine
from app.repositories.audit_repository import AuditRepository
from app.repositories.configuration_repository import ConfigurationRepository
from app.repositories.korisnik_repository import KorisnikRepository
from app.services.audit_service import AuditService
from app.services.configuration_service import ConfigurationService
from app.services.provisioning_service import ProvisioningService
from app.services.sms_service import get_sms_provider

logger = logging.getLogger("puls.scheduler")

PROVISIONING_JOB_ID = "provisioning_job"


def run_provisioning_job() -> None:
    """One provisioning pass. Single-instance worker: plain query, commit per user."""
    settings = get_settings()
    db = SessionLocal()
    try:
        service = ProvisioningService(
            korisnik_repository=KorisnikRepository(db),
            sms_provider=get_sms_provider(settings.sms_provider, engine=engine),
            audit_service=AuditService(AuditRepository(db), izvor=settings.audit_source),
            configuration_service=ConfigurationService(ConfigurationRepository(db)),
        )
        result = service.provision_pending(db, batch_size=settings.provisioning_batch_size)
        if result.total_candidates:
            logger.info(
                "Provisioning job: provisioned=%d skipped_no_phone=%d "
                "skipped_invalid_phone=%d sms_errors=%d errors=%d",
                result.provisioned,
                result.skipped_no_phone,
                result.skipped_invalid_phone,
                result.sms_errors,
                result.errors,
            )
    except Exception:
        db.rollback()
        logger.exception("Provisioning job failed")
    finally:
        db.close()
