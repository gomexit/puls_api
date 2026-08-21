"""Sistemska obavestenja: idempotentni event queue (PULS_SISTEMSKI_DOGADJAJI) +
worker obrada koja materijalizuje Oracle Inbox obavestenje/push redove preko
NotificationPublishingService.apply_publish_system.

enqueue_* metode NEMAJU sopstveni commit - pozivaju se iz poslovne transakcije
(anketa/ciklus/ideja/config servisa). discover_events/process_batch vode SOPSTVENU
transakciju i koristi ih ISKLJUCIVO zaseban worker proces (system_notification_worker.py),
nikad web request handler."""

import datetime
import logging
from collections.abc import Callable

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.configuration_definitions import validate_https_url
from app.core.exceptions import ValidationBusinessError
from app.models.idea_ciklus import IdeaCiklus
from app.models.ideja import IDEJA_STATUS_NAGRADJENA, IDEJA_STATUS_TOP_10
from app.models.obavestenje import AKCIJA_IDEA, AKCIJA_IDEA_CYCLE, AKCIJA_NONE, AKCIJA_SURVEY, AKCIJA_URL
from app.models.sistemski_dogadjaj import (
    DOGADJAJ_STATUS_FAILED,
    DOGADJAJ_STATUS_PENDING,
    DOGADJAJ_STATUS_PROCESSED,
    DOGADJAJ_STATUS_SKIPPED,
    DOGADJAJ_TIP_APP_VERSION_CHANGED,
    DOGADJAJ_TIP_IDEA_CYCLE_ACTIVATED,
    DOGADJAJ_TIP_IDEA_CYCLE_EXPIRING,
    DOGADJAJ_TIP_IDEA_NAGRADJENA,
    DOGADJAJ_TIP_IDEA_TOP_10,
    DOGADJAJ_TIP_SURVEY_ACTIVATED,
    DOGADJAJ_TIP_SURVEY_EXPIRING,
    SistemskiDogadjaj,
)
from app.repositories.audit_repository import AuditRepository
from app.repositories.configuration_repository import ConfigurationRepository
from app.repositories.notification_repository import NotificationRepository
from app.repositories.notification_targeting_repository import NotificationTargetingRepository
from app.repositories.push_delivery_repository import PushDeliveryRepository
from app.repositories.system_event_repository import SystemEventRepository
from app.services.audit_service import AuditService
from app.services.configuration_service import ConfigurationService
from app.services.notification_publishing_service import NotificationPublishingService

logger = logging.getLogger("puls.system_notifications")

EXPIRY_WINDOW_HOURS = 24
DEFAULT_EXPIRY_KEY = "NOTIFICATION_DEFAULT_EXPIRY_DAYS"
DEFAULT_EXPIRY_FALLBACK = 30
DOWNLOAD_URL_KEY = "DOWNLOAD_URL"
CURRENT_VERSION_KEY = "CURRENT_VERSION"
CURRENT_VERSION_FALLBACK = "1.0"
SYSTEM_CATEGORY = "SISTEM"
MAX_BACKOFF_MIN = 60


def _retry_backoff(attempts: int) -> datetime.timedelta:
    return datetime.timedelta(minutes=min(MAX_BACKOFF_MIN, 2 ** max(0, attempts - 1)))


class SystemNotificationService:
    def __init__(
        self,
        db: Session,
        event_repository: SystemEventRepository | None = None,
        targeting_repository: NotificationTargetingRepository | None = None,
        publishing_service: NotificationPublishingService | None = None,
        configuration_service: ConfigurationService | None = None,
        max_attempts: int = 5,
        now_fn: Callable[[], datetime.datetime] = datetime.datetime.now,
    ):
        self.db = db
        settings = get_settings()
        self.event_repo = event_repository or SystemEventRepository(db)
        self.targeting = targeting_repository or NotificationTargetingRepository(db)
        self.config = configuration_service or ConfigurationService(ConfigurationRepository(db))
        self.publishing = publishing_service or NotificationPublishingService(
            db,
            repository=NotificationRepository(db),
            targeting_repository=self.targeting,
            audit_service=AuditService(AuditRepository(db), izvor=settings.audit_source),
            configuration_service=self.config,
            push_delivery_repository=PushDeliveryRepository(db),
            now_fn=now_fn,
        )
        self.max_attempts = max_attempts
        self._now = now_fn

    # ============================================================= enqueue (bez commit)
    def enqueue_survey_activated(self, anketa_id: int) -> bool:
        return self.event_repo.enqueue_if_absent(
            f"SURVEY_ACTIVATED:{anketa_id}", DOGADJAJ_TIP_SURVEY_ACTIVATED, anketa_id, None, self._now()
        )

    def enqueue_survey_expiring(self, anketa_id: int, datum_zavrsetka: datetime.datetime) -> bool:
        # VREDNOST = tacan rok u trenutku enqueue-a - obrada kasnije proverava da se
        # rok u medjuvremenu nije promenio (produzenje kreira NOV kljuc/dogadjaj, pa
        # stari podsetnik za stari rok mora biti SKIPPED, ne objavljen sa zastarelim rokom).
        iso = datum_zavrsetka.isoformat()
        kljuc = f"SURVEY_EXPIRING:{anketa_id}:{iso}"
        return self.event_repo.enqueue_if_absent(
            kljuc, DOGADJAJ_TIP_SURVEY_EXPIRING, anketa_id, iso, self._now()
        )

    def enqueue_idea_cycle_activated(self, ciklus_id: int) -> bool:
        return self.event_repo.enqueue_if_absent(
            f"IDEA_CYCLE_ACTIVATED:{ciklus_id}",
            DOGADJAJ_TIP_IDEA_CYCLE_ACTIVATED,
            ciklus_id,
            None,
            self._now(),
        )

    def enqueue_idea_cycle_expiring(self, ciklus_id: int, datum_zavrsetka: datetime.datetime) -> bool:
        iso = datum_zavrsetka.isoformat()
        kljuc = f"IDEA_CYCLE_EXPIRING:{ciklus_id}:{iso}"
        return self.event_repo.enqueue_if_absent(
            kljuc, DOGADJAJ_TIP_IDEA_CYCLE_EXPIRING, ciklus_id, iso, self._now()
        )

    def enqueue_idea_top_10(self, idea_id: int) -> bool:
        return self.event_repo.enqueue_if_absent(
            f"IDEA_TOP_10:{idea_id}", DOGADJAJ_TIP_IDEA_TOP_10, idea_id, None, self._now()
        )

    def enqueue_idea_nagradjena(self, idea_id: int) -> bool:
        return self.event_repo.enqueue_if_absent(
            f"IDEA_NAGRADJENA:{idea_id}", DOGADJAJ_TIP_IDEA_NAGRADJENA, idea_id, None, self._now()
        )

    def enqueue_app_version_changed(self, version: str) -> bool:
        return self.event_repo.enqueue_if_absent(
            f"APP_VERSION_CHANGED:{version}", DOGADJAJ_TIP_APP_VERSION_CHANGED, None, version, self._now()
        )

    # ============================================================= worker: otkrivanje
    def discover_events(self) -> dict:
        """Otkriva dogadjaje koje NIJE trigerovao direktan poslovni poziv: SCHEDULED
        ankete koje su vremenom postale efektivno dostupne, i podsetnike (rok u
        narednih 24h). Sopstvena transakcija (commit na kraju), zasebna od
        process_batch - poziva je iskljucivo worker."""
        now = self._now()
        window_end = now + datetime.timedelta(hours=EXPIRY_WINDOW_HOURS)
        discovered = 0
        try:
            for anketa in self.event_repo.find_scheduled_surveys_now_active(now):
                if self.enqueue_survey_activated(anketa.id):
                    discovered += 1
            for anketa in self.event_repo.find_surveys_expiring_within(now, window_end):
                if self.enqueue_survey_expiring(anketa.id, anketa.datum_zavrsetka):
                    discovered += 1
            for ciklus in self.event_repo.find_cycles_expiring_within(now, window_end):
                if self.enqueue_idea_cycle_expiring(ciklus.id, ciklus.datum_zavrsetka):
                    discovered += 1
            self.db.commit()
        except Exception:
            self.db.rollback()
            logger.exception("Otkrivanje sistemskih dogadjaja nije uspelo.")
            raise
        return {"discovered": discovered}

    # ============================================================= worker: obrada
    def process_batch(self, batch_size: int) -> dict:
        """Obradjuje do batch_size PENDING dogadjaja, jedan po jedan - sopstvena
        transakcija po dogadjaju (kao push worker). Greska jednog dogadjaja ne
        zaustavlja ostale."""
        now = self._now()
        ids = self.event_repo.list_ready_ids(now, batch_size)
        summary = {"processed": 0, "published": 0, "skipped": 0, "retry": 0, "failed": 0}
        for event_id in ids:
            try:
                outcome = self._process_one(event_id)
                self.db.commit()
                summary["processed"] += 1
                summary[outcome] = summary.get(outcome, 0) + 1
            except Exception as exc:
                self.db.rollback()
                status_after = self._record_failure(event_id, type(exc).__name__)
                summary[status_after] = summary.get(status_after, 0) + 1
                logger.exception("Sistemski dogadjaj nije obradjen (event_id=%s)", event_id)
        return summary

    def _process_one(self, event_id: int) -> str:
        event = self.event_repo.get_for_update(event_id)
        if event is None or event.status != DOGADJAJ_STATUS_PENDING:
            # Vec obradjeno (konkurentni/ponovljeni poziv) - idempotentno, ne greska.
            return "skipped"
        now = self._now()
        recipients, content = self._resolve(event, now)
        if not recipients or content is None:
            event.status = DOGADJAJ_STATUS_SKIPPED
            event.datum_obrade = now
            return "skipped"

        datum_isteka = content["datum_isteka"]
        if datum_isteka is None:
            dana = self.config.get_int(DEFAULT_EXPIRY_KEY, DEFAULT_EXPIRY_FALLBACK)
            datum_isteka = now + datetime.timedelta(days=dana)

        # Zavrsna zastita: datum_isteka <= now (npr. rok u medjuvremenu prosao) ->
        # SKIPPED, nikad retry/FAILED - ovo NIJE greska obrade.
        if datum_isteka <= now:
            event.status = DOGADJAJ_STATUS_SKIPPED
            event.datum_obrade = now
            return "skipped"

        obav = self.publishing.apply_publish_system(
            kategorija_sifra=SYSTEM_CATEGORY,
            naslov=content["naslov"],
            kratak_tekst=content["kratak_tekst"],
            sadrzaj=content["sadrzaj"],
            akcija_tip=content["akcija_tip"],
            resurs_id=content["resurs_id"],
            akcija_url=content["akcija_url"],
            recipient_ids=recipients,
            datum_isteka=datum_isteka,
        )
        event.status = DOGADJAJ_STATUS_PROCESSED
        event.obavestenje_id = obav.id
        event.datum_obrade = now
        return "published"

    # ------------------------------------------------------- resolucija po tipu
    def _resolve(self, event: SistemskiDogadjaj, now: datetime.datetime):
        if event.tip_dogadjaja == DOGADJAJ_TIP_SURVEY_ACTIVATED:
            return self._resolve_survey_activated(event)
        if event.tip_dogadjaja == DOGADJAJ_TIP_SURVEY_EXPIRING:
            return self._resolve_survey_expiring(event)
        if event.tip_dogadjaja == DOGADJAJ_TIP_IDEA_CYCLE_ACTIVATED:
            return self._resolve_idea_cycle_activated(event)
        if event.tip_dogadjaja == DOGADJAJ_TIP_IDEA_CYCLE_EXPIRING:
            return self._resolve_idea_cycle_expiring(event)
        if event.tip_dogadjaja == DOGADJAJ_TIP_IDEA_TOP_10:
            # Istorijski dogadjaj stvarnog prelaska - salje se i ako je ideja u
            # medjuvremenu vec presla u NAGRADJENA (korisnik ne sme "izgubiti" TOP_10
            # obavestenje samo zato sto je sledeci prelaz nastupio pre workera).
            return self._resolve_idea_status(
                event, IDEJA_STATUS_TOP_10, allowed_statuses=(IDEJA_STATUS_TOP_10, IDEJA_STATUS_NAGRADJENA)
            )
        if event.tip_dogadjaja == DOGADJAJ_TIP_IDEA_NAGRADJENA:
            return self._resolve_idea_status(
                event, IDEJA_STATUS_NAGRADJENA, allowed_statuses=(IDEJA_STATUS_NAGRADJENA,)
            )
        if event.tip_dogadjaja == DOGADJAJ_TIP_APP_VERSION_CHANGED:
            return self._resolve_app_version_changed(event)
        return None, None

    def _resolve_survey_activated(self, event: SistemskiDogadjaj):
        anketa = self.event_repo.get_survey(event.resurs_id)
        now = self._now()
        if anketa is None or not anketa.is_available_to_employees(now):
            return None, None
        recipients = self.event_repo.survey_participant_ids(anketa.id)
        content = {
            "naslov": "Nova anketa je dostupna",
            "kratak_tekst": f"Anketa „{anketa.naziv}“ je sada aktivna.",
            "sadrzaj": f"Anketa „{anketa.naziv}“ je aktivirana i dostupna vam je za popunjavanje.",
            "akcija_tip": AKCIJA_SURVEY,
            "resurs_id": anketa.id,
            "akcija_url": None,
            "datum_isteka": anketa.datum_zavrsetka,
        }
        return recipients, content

    def _resolve_survey_expiring(self, event: SistemskiDogadjaj):
        anketa = self.event_repo.get_survey(event.resurs_id)
        now = self._now()
        if anketa is None:
            return None, None
        # Stari podsetnik za rok koji vise ne vazi (produzen u medjuvremenu) - preskoci.
        if event.vrednost != anketa.datum_zavrsetka.isoformat():
            return None, None
        if not anketa.is_available_to_employees(now) or anketa.datum_zavrsetka <= now:
            return None, None
        recipients = self.event_repo.survey_participant_ids_not_submitted(anketa.id)
        content = {
            "naslov": "Anketa uskoro ističe",
            "kratak_tekst": f"Anketa „{anketa.naziv}“ ističe uskoro.",
            "sadrzaj": (
                f"Rok za popunjavanje ankete „{anketa.naziv}“ ističe uskoro. "
                "Ne propustite priliku da učestvujete."
            ),
            "akcija_tip": AKCIJA_SURVEY,
            "resurs_id": anketa.id,
            "akcija_url": None,
            "datum_isteka": anketa.datum_zavrsetka,
        }
        return recipients, content

    def _resolve_idea_cycle_activated(self, event: SistemskiDogadjaj):
        ciklus = self.event_repo.get_cycle(event.resurs_id)
        now = self._now()
        if ciklus is None or not ciklus.is_submission_open(now):
            return None, None
        recipients = self.targeting.all_active_user_ids()
        content = self._idea_cycle_content(ciklus, activated=True)
        return recipients, content

    def _resolve_idea_cycle_expiring(self, event: SistemskiDogadjaj):
        ciklus = self.event_repo.get_cycle(event.resurs_id)
        now = self._now()
        if ciklus is None:
            return None, None
        # Stari podsetnik za rok koji vise ne vazi (produzen u medjuvremenu) - preskoci.
        if event.vrednost != ciklus.datum_zavrsetka.isoformat():
            return None, None
        if not ciklus.is_submission_open(now) or ciklus.datum_zavrsetka <= now:
            return None, None
        recipients = (
            self.targeting.all_active_user_ids() - self.event_repo.user_ids_with_idea_in_cycle(ciklus.id)
        )
        content = self._idea_cycle_content(ciklus, activated=False)
        return recipients, content

    @staticmethod
    def _idea_cycle_content(ciklus: IdeaCiklus, activated: bool) -> dict:
        if activated:
            naslov, kratak = "Novi ciklus ideja je pokrenut", f"Ciklus „{ciklus.naziv}“ je aktivan."
            sadrzaj = f"Ciklus ideja „{ciklus.naziv}“ je aktivan. Podelite svoju ideju."
        else:
            naslov, kratak = "Ciklus ideja uskoro ističe", f"Ciklus „{ciklus.naziv}“ ističe uskoro."
            sadrzaj = f"Rok za predlaganje ideja u ciklusu „{ciklus.naziv}“ ističe uskoro."
        return {
            "naslov": naslov,
            "kratak_tekst": kratak,
            "sadrzaj": sadrzaj,
            "akcija_tip": AKCIJA_IDEA_CYCLE,
            "resurs_id": ciklus.id,
            "akcija_url": None,
            "datum_isteka": ciklus.datum_zavrsetka,
        }

    def _resolve_idea_status(
        self, event: SistemskiDogadjaj, notification_status: str, allowed_statuses: tuple[str, ...]
    ):
        ideja = self.event_repo.get_idea(event.resurs_id)
        # Ne salji ako je ideja obrisana ili joj status vise NIJE medju dozvoljenima
        # za ovaj tip dogadjaja - "ne salji za ostale statuse".
        if ideja is None or ideja.status not in allowed_statuses:
            return None, None
        recipients = {ideja.korisnik_id}
        if notification_status == IDEJA_STATUS_TOP_10:
            naslov, kratak = "Vaša ideja je u TOP 10", f"Ideja „{ideja.naslov}“ je ušla u TOP 10."
        else:
            naslov, kratak = "Vaša ideja je nagrađena", f"Ideja „{ideja.naslov}“ je nagrađena."
        content = {
            "naslov": naslov,
            "kratak_tekst": kratak,
            "sadrzaj": kratak,
            "akcija_tip": AKCIJA_IDEA,
            "resurs_id": ideja.id,
            "akcija_url": None,
            "datum_isteka": None,
        }
        return recipients, content

    def _resolve_app_version_changed(self, event: SistemskiDogadjaj):
        # Stari dogadjaj za prethodnu verziju (CURRENT_VERSION je otad opet promenjena) -
        # preskoci; salje se samo dogadjaj koji odgovara TRENUTNO aktivnoj verziji.
        current_version = self.config.get_str(CURRENT_VERSION_KEY, CURRENT_VERSION_FALLBACK)
        if event.vrednost != current_version:
            return None, None
        recipients = self.targeting.all_active_user_ids()
        url = self._safe_download_url()
        content = {
            "naslov": "Dostupna je nova verzija aplikacije",
            "kratak_tekst": f"Verzija {event.vrednost} je dostupna.",
            "sadrzaj": f"Objavljena je nova verzija aplikacije ({event.vrednost}).",
            "akcija_tip": AKCIJA_URL if url else AKCIJA_NONE,
            "resurs_id": None,
            "akcija_url": url,
            "datum_isteka": None,
        }
        return recipients, content

    def _safe_download_url(self) -> str | None:
        raw = self.config.get_str(DOWNLOAD_URL_KEY, "")
        if not raw or not raw.strip():
            return None
        try:
            return validate_https_url(raw, DOWNLOAD_URL_KEY)
        except ValidationBusinessError:
            return None

    # ------------------------------------------------------------- retry/FAILED
    def _record_failure(self, event_id: int, error_code: str) -> str:
        """Sopstvena (nova) transakcija: uvecaj BROJ_POKUSAJA, upisi bezbedan
        POSLEDNJI_ERROR_CODE (samo naziv tipa izuzetka - bez poruke/tajni), i
        postavi PENDING+backoff ili FAILED posle maksimuma. Nikad ne baca dalje -
        greska ovde ne sme zaustaviti obradu ostalih dogadjaja u batch-u."""
        try:
            event = self.event_repo.get_for_update(event_id)
            if event is None:
                return "skipped"
            now = self._now()
            event.broj_pokusaja = (event.broj_pokusaja or 0) + 1
            event.poslednji_error_code = error_code[:100]
            if event.broj_pokusaja >= self.max_attempts:
                event.status = DOGADJAJ_STATUS_FAILED
                event.datum_sledeceg_pokusaja = None
                ishod = "failed"
            else:
                event.status = DOGADJAJ_STATUS_PENDING
                event.datum_sledeceg_pokusaja = now + _retry_backoff(event.broj_pokusaja)
                ishod = "retry"
            self.db.commit()
            return ishod
        except Exception:
            self.db.rollback()
            logger.exception("Sistemski dogadjaj retry bookkeeping nije uspeo (event_id=%s)", event_id)
            return "retry"
