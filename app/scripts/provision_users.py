"""Manual one-shot entry point: python -m app.scripts.provision_users

Processes all pending candidates (batch by batch, commit per user) and prints a
summary. Sends real SMS when SMS_PROVIDER=oracle."""

from app.core.config import get_settings
from app.core.logging import setup_logging
from app.db.session import SessionLocal, engine
from app.repositories.audit_repository import AuditRepository
from app.repositories.korisnik_repository import KorisnikRepository
from app.services.audit_service import AuditService
from app.services.provisioning_service import ProvisioningService
from app.services.sms_service import get_sms_provider


def main() -> None:
    setup_logging()
    settings = get_settings()

    db = SessionLocal()
    try:
        service = ProvisioningService(
            korisnik_repository=KorisnikRepository(db),
            sms_provider=get_sms_provider(settings.sms_provider, engine=engine),
            audit_service=AuditService(AuditRepository(db), izvor=settings.audit_source),
        )
        result = service.provision_all_pending(db)
    finally:
        db.close()

    print("Provisioning završen.")
    print(f"  Ukupno obrađeno: {result.total_candidates}")
    print(f"  Uspešno provisioned: {result.provisioned}")
    print(f"  Preskočeno (nema telefon): {result.skipped_no_phone}")
    print(f"  Preskočeno (nevalidan telefon): {result.skipped_invalid_phone}")
    print(f"  SMS greške: {result.sms_errors}")
    print(f"  Ostale greške: {result.errors}")


if __name__ == "__main__":
    main()
