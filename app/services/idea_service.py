import datetime
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import (
    IdeaEditNotAllowedError,
    IdeaLimitReachedError,
    IdeaNotFoundError,
    NoActiveIdeaCycleError,
)
from app.models.idea_ciklus import IdeaCiklus
from app.models.ideja import IDEJA_STATUS_POSLATA, Ideja
from app.models.korisnik import Korisnik
from app.repositories.audit_repository import AuditRepository
from app.repositories.configuration_repository import ConfigurationRepository
from app.repositories.idea_cycle_repository import IdeaCycleRepository
from app.repositories.idea_repository import IdeaRepository
from app.repositories.korisnik_repository import KorisnikRepository
from app.services.audit_service import AuditAction, AuditService
from app.services.configuration_service import ConfigurationService

MAX_IDEJA_KEY = "MAX_IDEJA_PO_CIKLUSU"
MAX_IDEJA_FALLBACK = 3
TOP_IDEAS_KEY = "TOP_IDEAS_COUNT"
TOP_IDEAS_FALLBACK = 10


@dataclass
class CurrentCycleOverview:
    cycle: IdeaCiklus | None
    submission_open: bool
    max_ideas: int
    used_ideas: int
    remaining_ideas: int


@dataclass
class RankedIdea:
    rang: int
    ideja: Ideja


class IdeaService:
    """Employee-facing modul IDEJE. Owns the transaction boundary: commit on
    success, rollback on any failure - partial state is never persisted."""

    def __init__(
        self,
        db: Session,
        idea_repository: IdeaRepository | None = None,
        cycle_repository: IdeaCycleRepository | None = None,
        korisnik_repository: KorisnikRepository | None = None,
        configuration_service: ConfigurationService | None = None,
        audit_service: AuditService | None = None,
    ):
        self.db = db
        self.settings = get_settings()
        self.idea_repository = idea_repository or IdeaRepository(db)
        self.cycle_repository = cycle_repository or IdeaCycleRepository(db)
        self.korisnik_repository = korisnik_repository or KorisnikRepository(db)
        self.configuration_service = configuration_service or ConfigurationService(
            ConfigurationRepository(db)
        )
        self.audit_service = audit_service or AuditService(
            AuditRepository(db), izvor=self.settings.audit_source
        )

    def _max_ideas(self) -> int:
        return self.configuration_service.get_int(MAX_IDEJA_KEY, MAX_IDEJA_FALLBACK)

    def _top_count(self) -> int:
        return self.configuration_service.get_int(TOP_IDEAS_KEY, TOP_IDEAS_FALLBACK)

    def get_current_cycle_overview(self, korisnik: Korisnik) -> CurrentCycleOverview:
        now = datetime.datetime.now()
        max_ideas = self._max_ideas()
        cycle = self.cycle_repository.get_active_cycle()
        if cycle is None:
            return CurrentCycleOverview(
                cycle=None,
                submission_open=False,
                max_ideas=max_ideas,
                used_ideas=0,
                remaining_ideas=0,
            )
        used = self.idea_repository.count_user_ideas_in_cycle(korisnik.id, cycle.id)
        remaining = max(0, max_ideas - used)
        return CurrentCycleOverview(
            cycle=cycle,
            submission_open=cycle.is_submission_open(now),
            max_ideas=max_ideas,
            used_ideas=used,
            remaining_ideas=remaining,
        )

    def create_idea(self, korisnik: Korisnik, naslov: str, opis: str) -> Ideja:
        try:
            now = datetime.datetime.now()
            # Zakljucaj red aktivnog ciklusa da provera limita + upis budu serijalizovani.
            cycle = self.cycle_repository.get_active_cycle_for_update()
            if cycle is None or not cycle.is_submission_open(now):
                raise NoActiveIdeaCycleError()

            used = self.idea_repository.count_user_ideas_in_cycle(korisnik.id, cycle.id)
            if used >= self._max_ideas():
                raise IdeaLimitReachedError()

            raspored = self.korisnik_repository.get_primary_active_raspored(korisnik.id)
            orgjed_sifra = raspored.orgjed_sifra if raspored else None

            ideja = self.idea_repository.create(
                korisnik_id=korisnik.id,
                ciklus_id=cycle.id,
                platni_broj=korisnik.platni_broj,
                ime_autora=korisnik.ime,
                prezime_autora=korisnik.prezime,
                orgjed_sifra=orgjed_sifra,
                naslov=naslov,
                opis=opis,
            )
            self.audit_service.log(
                AuditAction.IDEA_CREATED,
                korisnik_id=korisnik.id,
                platni_broj=korisnik.platni_broj,
                tip_entiteta="IDEJA",
                entitet_id=str(ideja.id),
                detalji=f"ciklus_id={cycle.id}",
            )
            self.db.commit()
            return ideja
        except Exception:
            self.db.rollback()
            raise

    def list_my_ideas(self, korisnik: Korisnik, ciklus_id: int | None = None) -> list[Ideja]:
        return self.idea_repository.list_by_user(korisnik.id, ciklus_id)

    def get_my_idea(self, korisnik: Korisnik, idea_id: int) -> Ideja:
        ideja = self.idea_repository.get_by_id(idea_id)
        # Za tudju/nepostojecu ideju vracamo isti odgovor - ne otkrivamo postojanje resursa.
        if ideja is None or ideja.korisnik_id != korisnik.id:
            raise IdeaNotFoundError()
        return ideja

    def update_my_idea(self, korisnik: Korisnik, idea_id: int, naslov: str, opis: str) -> Ideja:
        try:
            ideja = self.idea_repository.get_by_id(idea_id)
            if ideja is None or ideja.korisnik_id != korisnik.id:
                raise IdeaNotFoundError()
            if ideja.status != IDEJA_STATUS_POSLATA:
                raise IdeaEditNotAllowedError()

            cycle = self.cycle_repository.get_by_id(ideja.ciklus_id)
            now = datetime.datetime.now()
            if cycle is None or not cycle.is_submission_open(now):
                raise IdeaEditNotAllowedError()

            ideja.naslov = naslov
            ideja.opis = opis
            ideja.datum_izmene = now

            self.audit_service.log(
                AuditAction.IDEA_UPDATED,
                korisnik_id=korisnik.id,
                platni_broj=korisnik.platni_broj,
                tip_entiteta="IDEJA",
                entitet_id=str(ideja.id),
            )
            self.db.commit()
            return ideja
        except Exception:
            self.db.rollback()
            raise

    def list_top(self, ciklus_id: int | None = None) -> list[RankedIdea]:
        if ciklus_id is None:
            cycle = self.cycle_repository.get_active_cycle()
            if cycle is None:
                return []
            ciklus_id = cycle.id
        ideje = self.idea_repository.list_top(ciklus_id, self._top_count())
        return [RankedIdea(rang=i, ideja=ideja) for i, ideja in enumerate(ideje, start=1)]