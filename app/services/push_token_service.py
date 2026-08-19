"""Employee push-token servis (registracija/deaktivacija). Owns transakciju.
Identitet (korisnik, uredjaj) dolazi iz AuthContext-a, nikad iz payload-a.
FCM token se NIKADA ne loguje ni upisuje u audit detalje."""

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import PushTokenConflictError
from app.models.korisnik import Korisnik
from app.repositories.audit_repository import AuditRepository
from app.repositories.push_token_repository import PushTokenRepository
from app.services.audit_service import AuditAction, AuditService

# Function-based unique indeksi iz sql/004 koji stite "jedan aktivan uredjaj/token"
# pravilo na DB nivou. Samo konflikt na OVA DVA imena se prevodi u poslovnu gresku;
# sve ostale IntegrityError greske se propagiraju nepromenjene (ne maskiraju se).
_ACTIVE_TOKEN_CONSTRAINTS = ("UX_PUSH_TOKEN_AKTIVAN_HASH", "UX_PUSH_TOKEN_AKTIVAN_KOR")


def _is_active_token_conflict(exc: IntegrityError) -> bool:
    text = str(getattr(exc, "orig", exc)).upper()
    return any(name in text for name in _ACTIVE_TOKEN_CONSTRAINTS)


class PushTokenService:
    def __init__(
        self,
        db: Session,
        token_repository: PushTokenRepository | None = None,
        audit_service: AuditService | None = None,
    ):
        self.db = db
        self.settings = get_settings()
        self.repo = token_repository or PushTokenRepository(db)
        self.audit_service = audit_service or AuditService(
            AuditRepository(db), izvor=self.settings.audit_source
        )

    def register(self, korisnik: Korisnik, uredjaj_id: str, fcm_token: str, app_version: str | None) -> None:
        try:
            self.repo.upsert(korisnik.id, uredjaj_id, fcm_token, app_version)
            # Audit bez tokena: samo cinjenica registracije.
            self.audit_service.log(
                AuditAction.PUSH_TOKEN_REGISTERED,
                korisnik_id=korisnik.id,
                platni_broj=korisnik.platni_broj,
                tip_entiteta="PUSH_TOKEN",
                entitet_id=str(korisnik.id),
            )
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            if _is_active_token_conflict(exc):
                raise PushTokenConflictError() from exc
            raise
        except Exception:
            self.db.rollback()
            raise

    def deactivate_current_device(self, korisnik: Korisnik, uredjaj_id: str) -> None:
        try:
            self.repo.deactivate_user_device(korisnik.id, uredjaj_id)
            self.audit_service.log(
                AuditAction.PUSH_TOKEN_DEACTIVATED,
                korisnik_id=korisnik.id,
                platni_broj=korisnik.platni_broj,
                tip_entiteta="PUSH_TOKEN",
                entitet_id=str(korisnik.id),
            )
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
