import datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import (
    ActiveIdeaCycleAlreadyExistsError,
    IdeaCycleNotFoundError,
    IdeaNotFoundError,
    InvalidIdeaCycleTransitionError,
    InvalidIdeaStatusTransitionError,
    ValidationBusinessError,
)
from app.models.idea_ciklus import (
    CIKLUS_STATUS_AKTIVAN,
    IdeaCiklus,
    is_valid_cycle_transition,
)
from app.models.ideja import (
    IDEJA_STATUS_NAGRADJENA,
    IDEJA_STATUS_TOP_10,
    Ideja,
    compute_konacna_ocena,
    is_valid_idea_transition,
)
from app.models.korisnik import Korisnik
from app.repositories.audit_repository import AuditRepository
from app.repositories.idea_cycle_repository import IdeaCycleRepository
from app.repositories.idea_repository import IdeaRepository
from app.services.audit_service import AuditAction, AuditService
from app.services.system_notification_service import SystemNotificationService


# Unique (function-based) indeks koji garantuje najvise jedan AKTIVAN ciklus.
ACTIVE_CYCLE_UNIQUE_INDEX = "UX_IDEA_CIKLUS_JEDAN_AKTIVAN"


def _is_active_cycle_conflict(exc: IntegrityError) -> bool:
    """True samo ako IntegrityError potice od indeksa jedinstvenog aktivnog ciklusa.
    Ne pretvaramo sve IntegrityError-e u isti business kod."""
    return ACTIVE_CYCLE_UNIQUE_INDEX in str(getattr(exc, "orig", exc)).upper()


class IdeaAdminService:
    """Admin/HR-facing modul IDEJE. Owns the transaction boundary."""

    def __init__(
        self,
        db: Session,
        idea_repository: IdeaRepository | None = None,
        cycle_repository: IdeaCycleRepository | None = None,
        audit_service: AuditService | None = None,
        system_notification_service: SystemNotificationService | None = None,
    ):
        self.db = db
        self.settings = get_settings()
        self.idea_repository = idea_repository or IdeaRepository(db)
        self.cycle_repository = cycle_repository or IdeaCycleRepository(db)
        self.audit_service = audit_service or AuditService(
            AuditRepository(db), izvor=self.settings.audit_source
        )
        self.system_notifications = system_notification_service or SystemNotificationService(db)

    # --- Ciklusi ---
    def list_cycles(self) -> list[IdeaCiklus]:
        return self.cycle_repository.list_cycles()

    def create_cycle(
        self,
        actor: Korisnik,
        naziv: str,
        datum_pocetka: datetime.datetime,
        datum_zavrsetka: datetime.datetime,
    ) -> IdeaCiklus:
        try:
            if datum_zavrsetka <= datum_pocetka:
                raise ValidationBusinessError("Datum završetka mora biti posle datuma početka.")
            ciklus = self.cycle_repository.create(naziv, datum_pocetka, datum_zavrsetka)
            self.audit_service.log(
                AuditAction.IDEA_CYCLE_CREATED,
                korisnik_id=actor.id,
                platni_broj=actor.platni_broj,
                tip_entiteta="IDEA_CIKLUS",
                entitet_id=str(ciklus.id),
            )
            self.db.commit()
            return ciklus
        except Exception:
            self.db.rollback()
            raise

    def change_cycle_status(self, actor: Korisnik, cycle_id: int, novi_status: str) -> IdeaCiklus:
        try:
            ciklus = self.cycle_repository.get_by_id(cycle_id)
            if ciklus is None:
                raise IdeaCycleNotFoundError()
            if not is_valid_cycle_transition(ciklus.status, novi_status):
                raise InvalidIdeaCycleTransitionError()
            # Najvise jedan AKTIVAN ciklus u datom trenutku.
            if novi_status == CIKLUS_STATUS_AKTIVAN and self.cycle_repository.count_active_cycles() > 0:
                raise ActiveIdeaCycleAlreadyExistsError()

            stari_status = ciklus.status
            ciklus.status = novi_status
            ciklus.datum_izmene = datetime.datetime.now()

            self.audit_service.log(
                AuditAction.IDEA_CYCLE_STATUS_CHANGED,
                korisnik_id=actor.id,
                platni_broj=actor.platni_broj,
                tip_entiteta="IDEA_CIKLUS",
                entitet_id=str(ciklus.id),
                detalji=f"{stari_status}->{novi_status}",
            )
            if novi_status == CIKLUS_STATUS_AKTIVAN:
                self.system_notifications.enqueue_idea_cycle_activated(ciklus.id)
            self.db.commit()
            return ciklus
        except IntegrityError as exc:
            # Konkurentna aktivacija: pre-provera je prosla, ali je DB unique indeks
            # odbio drugi commit. Mapiramo samo taj konkretan constraint.
            self.db.rollback()
            if _is_active_cycle_conflict(exc):
                raise ActiveIdeaCycleAlreadyExistsError() from exc
            raise
        except Exception:
            self.db.rollback()
            raise

    # --- Ideje ---
    def list_ideas(
        self,
        ciklus_id: int | None,
        status: str | None,
        korisnik_id: int | None,
        platni_broj: str | None,
        page: int,
        page_size: int,
    ) -> tuple[list[Ideja], int]:
        return self.idea_repository.admin_list(
            ciklus_id, status, korisnik_id, platni_broj, page, page_size
        )

    def get_idea(self, idea_id: int) -> Ideja:
        ideja = self.idea_repository.get_by_id(idea_id)
        if ideja is None:
            raise IdeaNotFoundError()
        return ideja

    def change_idea_status(self, actor: Korisnik, idea_id: int, novi_status: str) -> Ideja:
        try:
            ideja = self.idea_repository.get_by_id(idea_id)
            if ideja is None:
                raise IdeaNotFoundError()
            if not is_valid_idea_transition(ideja.status, novi_status):
                raise InvalidIdeaStatusTransitionError()

            stari_status = ideja.status
            ideja.status = novi_status
            ideja.datum_izmene = datetime.datetime.now()

            self.audit_service.log(
                AuditAction.IDEA_STATUS_CHANGED,
                korisnik_id=actor.id,
                platni_broj=actor.platni_broj,
                tip_entiteta="IDEJA",
                entitet_id=str(ideja.id),
                detalji=f"{stari_status}->{novi_status}",
            )
            if novi_status == IDEJA_STATUS_TOP_10:
                self.system_notifications.enqueue_idea_top_10(ideja.id)
            elif novi_status == IDEJA_STATUS_NAGRADJENA:
                self.system_notifications.enqueue_idea_nagradjena(ideja.id)
            self.db.commit()
            return ideja
        except Exception:
            self.db.rollback()
            raise

    def set_hr_score(self, actor: Korisnik, idea_id: int, hr_ocena: int) -> Ideja:
        try:
            if hr_ocena < 1 or hr_ocena > 10:
                raise ValidationBusinessError("HR ocena mora biti između 1 i 10.")
            ideja = self.idea_repository.get_by_id(idea_id)
            if ideja is None:
                raise IdeaNotFoundError()

            ideja.hr_ocena = hr_ocena
            # Konacna ocena se racuna samo ako postoje OBE ocene (HR i AI). U suprotnom NULL.
            ideja.konacna_ocena = compute_konacna_ocena(ideja.hr_ocena, ideja.ai_ocena)
            ideja.datum_izmene = datetime.datetime.now()

            self.audit_service.log(
                AuditAction.IDEA_HR_SCORE_SET,
                korisnik_id=actor.id,
                platni_broj=actor.platni_broj,
                tip_entiteta="IDEJA",
                entitet_id=str(ideja.id),
                detalji=f"hr_ocena={hr_ocena}",
            )
            self.db.commit()
            return ideja
        except Exception:
            self.db.rollback()
            raise