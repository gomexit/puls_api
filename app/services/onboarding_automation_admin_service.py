import datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import (
    SurveyAutomationConflictError,
    SurveyAutomationNotAllowedForAnonymousError,
    SurveyNotFoundError,
)
from app.models.anketa_ucesce import AnketaAutomatika
from app.models.korisnik import Korisnik
from app.repositories.audit_repository import AuditRepository
from app.repositories.onboarding_automation_repository import OnboardingAutomationRepository
from app.repositories.survey_repository import SurveyRepository
from app.services.audit_service import AuditAction, AuditService


class OnboardingAutomationAdminService:
    """Admin/HR modul: pravila automatske dodele onboarding ankete (PULS_ANKETA_AUTOMATIKA).
    Owns the transaction boundary (commit/rollback), prati stil SurveyAdminService."""

    def __init__(
        self,
        db: Session,
        repository: OnboardingAutomationRepository | None = None,
        survey_repository: SurveyRepository | None = None,
        audit_service: AuditService | None = None,
    ):
        self.db = db
        self.settings = get_settings()
        self.repo = repository or OnboardingAutomationRepository(db)
        self.survey_repo = survey_repository or SurveyRepository(db)
        self.audit_service = audit_service or AuditService(
            AuditRepository(db), izvor=self.settings.audit_source
        )

    def list_automations(self) -> list[AnketaAutomatika]:
        return self.repo.list_all()

    def upsert(self, actor: Korisnik, anketa_id: int, payload) -> AnketaAutomatika:
        try:
            anketa = self.survey_repo.get_survey(anketa_id)
            if anketa is None:
                raise SurveyNotFoundError()
            if anketa.anonimna != "N":
                raise SurveyAutomationNotAllowedForAnonymousError()

            existing = self.repo.get_by_survey_id(anketa_id)
            if existing is not None:
                pravilo = self.repo.get_for_update(existing.id)
            else:
                pravilo = None

            if payload.aktivna:
                self._assert_no_milestone_conflict(
                    payload.dani_od_zaposlenja, exclude_id=pravilo.id if pravilo is not None else None
                )

            now = datetime.datetime.now()

            if pravilo is None:
                pravilo = self.repo.add(
                    AnketaAutomatika(
                        anketa_id=anketa_id,
                        dani_od_zaposlenja=payload.dani_od_zaposlenja,
                        rok_dana=payload.rok_dana,
                        datum_primene_od=payload.datum_primene_od,
                        aktivna="D" if payload.aktivna else "N",
                        datum_kreiranja=now,
                    )
                )
                self._log_upsert(actor, anketa_id, pravilo)
                self.db.commit()
                return pravilo

            nova_aktivna = "D" if payload.aktivna else "N"
            unchanged = (
                pravilo.dani_od_zaposlenja == payload.dani_od_zaposlenja
                and pravilo.rok_dana == payload.rok_dana
                and pravilo.datum_primene_od == payload.datum_primene_od
                and pravilo.aktivna == nova_aktivna
            )
            if unchanged:
                self.db.commit()
                return pravilo

            pravilo.dani_od_zaposlenja = payload.dani_od_zaposlenja
            pravilo.rok_dana = payload.rok_dana
            pravilo.datum_primene_od = payload.datum_primene_od
            pravilo.aktivna = nova_aktivna
            pravilo.datum_izmene = now
            self._log_upsert(actor, anketa_id, pravilo)
            self.db.commit()
            return pravilo
        except IntegrityError as exc:
            # Konkurentni INSERT/UPDATE je pogodio jedan od dva poznata konflikta
            # (pre-provera je prosla ali unique indeks odbio); mapiramo SAMO njih -
            # ostale IntegrityError re-raise (isti obrazac kao SurveyAdminService.create_type).
            self.db.rollback()
            orig = str(getattr(exc, "orig", exc)).upper()
            if "UX_ANKETA_AUTOMATIKA_ANKETA" in orig or "UX_ANKETA_AUTOMATIKA_AKTIVNA_MILESTONE" in orig:
                raise SurveyAutomationConflictError() from exc
            raise
        except Exception:
            self.db.rollback()
            raise

    def _assert_no_milestone_conflict(self, dani_od_zaposlenja: int, exclude_id: int | None) -> None:
        for pravilo in self.repo.find_active_rules():
            if pravilo.dani_od_zaposlenja != dani_od_zaposlenja:
                continue
            if exclude_id is not None and pravilo.id == exclude_id:
                continue
            raise SurveyAutomationConflictError()

    def _log_upsert(self, actor: Korisnik, anketa_id: int, pravilo: AnketaAutomatika) -> None:
        self.audit_service.log(
            AuditAction.SURVEY_AUTOMATION_UPSERTED,
            korisnik_id=actor.id,
            platni_broj=actor.platni_broj,
            tip_entiteta="ANKETA_AUTOMATIKA",
            entitet_id=str(pravilo.id),
            detalji=(
                f"anketa_id={anketa_id};dani_od_zaposlenja={pravilo.dani_od_zaposlenja};"
                f"rok_dana={pravilo.rok_dana};aktivna={pravilo.aktivna}"
            ),
        )
