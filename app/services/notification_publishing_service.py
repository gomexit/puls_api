import datetime
from collections.abc import Callable

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import (
    InvalidNotificationStatusTransitionError,
    NotificationEditNotAllowedError,
    NotificationNotFoundError,
    ValidationBusinessError,
)
from app.models.korisnik import Korisnik
from app.models.obavestenje import (
    AKCIJA_IDEA,
    AKCIJA_SURVEY,
    CILJ_ORGJED,
    CILJ_PLATNI_BROJ,
    CILJ_SVI,
    CILJEVI_NEPODRZANI,
    OBAVESTENJE_STATUS_ARCHIVED,
    OBAVESTENJE_STATUS_DRAFT,
    OBAVESTENJE_STATUS_PUBLISHED,
    Obavestenje,
    ObavestenjeCilj,
    ObavestenjePrimalac,
    is_valid_notification_transition,
)
from app.repositories.audit_repository import AuditRepository
from app.repositories.configuration_repository import ConfigurationRepository
from app.repositories.notification_repository import NotificationRepository
from app.repositories.notification_targeting_repository import NotificationTargetingRepository
from app.repositories.push_delivery_repository import PushDeliveryRepository
from app.schemas.notification import NotificationDraftInput
from app.services.audit_service import AuditAction, AuditService
from app.services.configuration_service import ConfigurationService

DEFAULT_EXPIRY_KEY = "NOTIFICATION_DEFAULT_EXPIRY_DAYS"
DEFAULT_EXPIRY_FALLBACK = 30


class NotificationPublishingService:
    """Centralni servis za kreiranje, izmenu, objavljivanje i arhiviranje obavestenja
    i materijalizaciju primalaca.

    Koriste ga: admin API (app/api/v1/admin_notifications.py preko NotificationAdminService),
    automatski dogadjaji (nova anketa, status ideje) i buduci FCM sloj.

    Dve grupe metoda:
      * apply_* rade SAMO poslovnu izmenu (validacija, mutacija, audit) BEZ commit/rollback
        - transakciju vodi pozivalac; koristi ih NotificationAdminService da bi izmena i
          sastavljanje HTTP odgovora bili u JEDNOJ transakciji (commit tek na kraju).
      * javne create_draft/update_draft/publish/archive su tanki wrapper-i za direktne
        pozivaoce: apply_* + commit, uz rollback na gresku."""

    def __init__(
        self,
        db: Session,
        repository: NotificationRepository | None = None,
        targeting_repository: NotificationTargetingRepository | None = None,
        audit_service: AuditService | None = None,
        configuration_service: ConfigurationService | None = None,
        push_delivery_repository: PushDeliveryRepository | None = None,
        now_fn: Callable[[], datetime.datetime] = datetime.datetime.now,
    ):
        self.db = db
        self.settings = get_settings()
        self.repo = repository or NotificationRepository(db)
        self.targeting = targeting_repository or NotificationTargetingRepository(db)
        self.audit_service = audit_service or AuditService(
            AuditRepository(db), izvor=self.settings.audit_source
        )
        self.config = configuration_service or ConfigurationService(ConfigurationRepository(db))
        self.push_delivery = push_delivery_repository or PushDeliveryRepository(db)
        self._now = now_fn

    # --------------------------------------------------- deljena poslovna validacija
    def _validate_payload_business(self, payload: NotificationDraftInput) -> None:
        """Poslovne provere zajednicke za create i update (uz vec izvrsenu schema
        field-level validaciju). Centralizovano da se ne duplira u admin servisu."""
        # Kategorija mora postojati (FK); aktivnost se proverava tek pri objavljivanju.
        if self.repo.get_category(payload.kategorija_sifra) is None:
            raise ValidationBusinessError("Kategorija obaveštenja ne postoji.")
        # CENTRALA/MALOPRODAJA se odbijaju odmah (a ne tek pri publish).
        for c in payload.ciljevi:
            if c.tip_cilja in CILJEVI_NEPODRZANI:
                raise ValidationBusinessError(
                    "Ciljanje CENTRALA/MALOPRODAJA nije podržano (nedostaje pouzdan HR podatak)."
                )
        self._validate_resource(payload.akcija_tip, payload.resurs_id)

    def _validate_resource(self, akcija_tip: str, resurs_id: int | None) -> None:
        """SURVEY/IDEA RESURS_ID mora pokazivati na postojeci entitet. Ne dodaje se
        polymorphic FK u DDL - integritet se cuva ovde (i pri create/update i pri publish)."""
        if akcija_tip == AKCIJA_SURVEY:
            if resurs_id is None or not self.repo.survey_exists(resurs_id):
                raise ValidationBusinessError("Anketa (resurs_id) za SURVEY akciju ne postoji.")
        elif akcija_tip == AKCIJA_IDEA:
            if resurs_id is None or not self.repo.idea_exists(resurs_id):
                raise ValidationBusinessError("Ideja (resurs_id) za IDEA akciju ne postoji.")

    # ================================================================ apply_* (bez commit)
    def apply_create_draft(
        self, actor: Korisnik | None, payload: NotificationDraftInput
    ) -> Obavestenje:
        """Kreira DRAFT + ciljeve + audit. BEZ commit/rollback - transakciju vodi pozivalac."""
        self._validate_payload_business(payload)
        now = self._now()
        # Autor iskljucivo iz autentikovanog actor-a; NULL za sistemski dogadjaj.
        # Payload ne moze da odredi/lazira autora (schema: extra='forbid').
        kreirao = actor.platni_broj if actor else None
        obav = self.repo.add_notification(
            Obavestenje(
                kategorija_sifra=payload.kategorija_sifra,
                naslov=payload.naslov,
                kratak_tekst=payload.kratak_tekst,
                sadrzaj=payload.sadrzaj,
                status=OBAVESTENJE_STATUS_DRAFT,
                akcija_tip=payload.akcija_tip,
                resurs_id=payload.resurs_id,
                akcija_url=payload.akcija_url,
                kreirao_platni_broj=kreirao,
                datum_objave=None,
                datum_isteka=payload.datum_isteka,
                datum_kreiranja=now,
            )
        )
        for c in payload.ciljevi:
            self.repo.add_target(
                ObavestenjeCilj(
                    obavestenje_id=obav.id,
                    tip_cilja=c.tip_cilja,
                    vrednost=c.vrednost,
                    datum_kreiranja=now,
                )
            )
        self.audit_service.log(
            AuditAction.NOTIFICATION_CREATED,
            korisnik_id=actor.id if actor else None,
            platni_broj=actor.platni_broj if actor else None,
            tip_entiteta="OBAVESTENJE",
            entitet_id=str(obav.id),
        )
        return obav

    def apply_update_draft(
        self, actor: Korisnik | None, notification_id: int, payload: NotificationDraftInput
    ) -> Obavestenje:
        """Full-replace DRAFT-a + ciljeva + audit. BEZ commit/rollback."""
        obav = self.repo.get_notification_for_update(notification_id)
        if obav is None:
            raise NotificationNotFoundError()
        # Izmena dozvoljena samo dok je DRAFT (PUBLISHED/ARCHIVED -> 409).
        if obav.status != OBAVESTENJE_STATUS_DRAFT:
            raise NotificationEditNotAllowedError()

        # Najpre KOMPLETNA validacija (uklj. novi resurs); tek onda zamena ciljeva,
        # da stari DRAFT i stari ciljevi ostanu netaknuti ako nesto padne.
        self._validate_payload_business(payload)

        now = self._now()
        obav.kategorija_sifra = payload.kategorija_sifra
        obav.naslov = payload.naslov
        obav.kratak_tekst = payload.kratak_tekst
        obav.sadrzaj = payload.sadrzaj
        obav.akcija_tip = payload.akcija_tip
        obav.resurs_id = payload.resurs_id
        obav.akcija_url = payload.akcija_url
        obav.datum_isteka = payload.datum_isteka
        obav.datum_izmene = now
        # ID, autor, DATUM_KREIRANJA i STATUS se NE menjaju.

        self.repo.delete_targets(notification_id)
        self.db.flush()
        for c in payload.ciljevi:
            self.repo.add_target(
                ObavestenjeCilj(
                    obavestenje_id=notification_id,
                    tip_cilja=c.tip_cilja,
                    vrednost=c.vrednost,
                    datum_kreiranja=now,
                )
            )
        self.audit_service.log(
            AuditAction.NOTIFICATION_UPDATED,
            korisnik_id=actor.id if actor else None,
            platni_broj=actor.platni_broj if actor else None,
            tip_entiteta="OBAVESTENJE",
            entitet_id=str(notification_id),
        )
        return obav

    def apply_archive(self, actor: Korisnik | None, notification_id: int) -> Obavestenje:
        """Arhivira PUBLISHED (primaoci ostaju) + audit. BEZ commit/rollback."""
        obav = self.repo.get_notification_for_update(notification_id)
        if obav is None:
            raise NotificationNotFoundError()
        if not is_valid_notification_transition(obav.status, OBAVESTENJE_STATUS_ARCHIVED):
            raise InvalidNotificationStatusTransitionError()

        now = self._now()
        obav.status = OBAVESTENJE_STATUS_ARCHIVED
        obav.datum_izmene = now
        # Redovi primalaca se NE brisu (istorija citanja ostaje).
        self.audit_service.log(
            AuditAction.NOTIFICATION_ARCHIVED,
            korisnik_id=actor.id if actor else None,
            platni_broj=actor.platni_broj if actor else None,
            tip_entiteta="OBAVESTENJE",
            entitet_id=str(obav.id),
        )
        return obav

    def apply_publish(
        self,
        actor: Korisnik | None,
        notification_id: int,
        datum_isteka: datetime.datetime | None = None,
    ) -> Obavestenje:
        """Objavljuje DRAFT: materijalizuje primaoce + audit. BEZ commit/rollback.
        Pozivalac treba da flush-uje pre citanja statistike novih primalaca."""
        # Direktno prosledjen datum_isteka mora biti timezone-naive (Oracle ugovor).
        # Aware vrednost NE sme izazvati TypeError/500 pri poredjenju sa naive 'now'.
        if datum_isteka is not None and datum_isteka.tzinfo is not None:
            raise ValidationBusinessError(
                "Datum isteka mora biti lokalni, bez vremenske zone (bez Z ili offseta)."
            )
        now = self._now()
        obav = self.repo.get_notification_for_update(notification_id)
        if obav is None:
            raise NotificationNotFoundError()
        # Ponovljeno objavljivanje / arhivirano -> jasan 409, bez duplih primalaca.
        if obav.status != OBAVESTENJE_STATUS_DRAFT or not is_valid_notification_transition(
            obav.status, OBAVESTENJE_STATUS_PUBLISHED
        ):
            raise InvalidNotificationStatusTransitionError()

        kat = self.repo.get_category(obav.kategorija_sifra)
        if kat is None or kat.aktivna != "D":
            raise ValidationBusinessError("Kategorija obaveštenja ne postoji ili nije aktivna.")

        # Ponovna provera resursa (SURVEY/IDEA) pri publish - anketa/ideja moze
        # da bude obrisana izmedju kreiranja i objavljivanja.
        self._validate_resource(obav.akcija_tip, obav.resurs_id)

        targets = self.repo.get_targets(notification_id)
        if not targets:
            raise ValidationBusinessError("Obaveštenje nema definisane ciljne grupe.")

        user_ids = self._resolve_recipients(targets)
        if not user_ids:
            # Nista se ne commituje - nema delimicno objavljenog obavestenja.
            raise ValidationBusinessError("Nijedan aktivan primalac nije pronađen za ciljne grupe.")

        istek = datum_isteka if datum_isteka is not None else obav.datum_isteka
        if istek is None:
            dana = self.config.get_int(DEFAULT_EXPIRY_KEY, DEFAULT_EXPIRY_FALLBACK)
            istek = now + datetime.timedelta(days=dana)
        if istek <= now:
            raise ValidationBusinessError("Datum isteka mora biti posle datuma objave.")

        existing = self.repo.existing_recipient_ids(notification_id)
        for uid in user_ids - existing:
            self.repo.add_recipient(
                ObavestenjePrimalac(
                    obavestenje_id=notification_id,
                    korisnik_id=uid,
                    procitano="N",
                    datum_citanja=None,
                    datum_kreiranja=now,
                )
            )

        # Outbox: po jedan PENDING push red za svakog primaoca, u ISTOJ transakciji.
        # FCM se NE poziva ovde (worker to radi kasnije). Idempotentno (bez duplih redova).
        self.push_delivery.create_pending_for_recipients(notification_id, user_ids, now)

        obav.status = OBAVESTENJE_STATUS_PUBLISHED
        obav.datum_objave = now
        obav.datum_isteka = istek
        obav.datum_izmene = now

        self.audit_service.log(
            AuditAction.NOTIFICATION_PUBLISHED,
            korisnik_id=actor.id if actor else None,
            platni_broj=actor.platni_broj if actor else None,
            tip_entiteta="OBAVESTENJE",
            entitet_id=str(obav.id),
        )
        return obav

    def apply_resend_unread(self, actor: Korisnik | None, notification_id: int) -> int:
        """Resend push SAMO nepr. primaocima. Radi samo za PUBLISHED i jos aktivno/neisteklo
        obavestenje. NE menja read/unread. Bez duplih redova (+BROJ_PONOVNIH_SLANJA).
        Vraca broj primalaca vracenih u PENDING. BEZ commit/rollback."""
        obav = self.repo.get_notification_for_update(notification_id)
        if obav is None:
            raise NotificationNotFoundError()
        if obav.status != OBAVESTENJE_STATUS_PUBLISHED:
            raise InvalidNotificationStatusTransitionError()
        now = self._now()
        if not obav.is_available_to_employees(now):
            raise ValidationBusinessError("Obaveštenje nije aktivno objavljeno (isteklo/arhivirano).")

        unread_ids = self.repo.unread_recipient_ids(notification_id)
        affected = self.push_delivery.requeue_unread(notification_id, unread_ids, now)
        self.audit_service.log(
            AuditAction.NOTIFICATION_PUSH_RESEND,
            korisnik_id=actor.id if actor else None,
            platni_broj=actor.platni_broj if actor else None,
            tip_entiteta="OBAVESTENJE",
            entitet_id=str(notification_id),
            detalji=f"resend_unread={affected}",
        )
        return affected

    # ============================================== javni wrapper-i (apply_* + commit)
    def create_draft(self, actor: Korisnik | None, payload: NotificationDraftInput) -> Obavestenje:
        try:
            obav = self.apply_create_draft(actor, payload)
            self.db.commit()
            return obav
        except Exception:
            self.db.rollback()
            raise

    def update_draft(
        self, actor: Korisnik | None, notification_id: int, payload: NotificationDraftInput
    ) -> Obavestenje:
        try:
            obav = self.apply_update_draft(actor, notification_id, payload)
            self.db.commit()
            return obav
        except Exception:
            self.db.rollback()
            raise

    def archive(self, actor: Korisnik | None, notification_id: int) -> Obavestenje:
        try:
            obav = self.apply_archive(actor, notification_id)
            self.db.commit()
            return obav
        except Exception:
            self.db.rollback()
            raise

    def publish(
        self,
        actor: Korisnik | None,
        notification_id: int,
        datum_isteka: datetime.datetime | None = None,
    ) -> Obavestenje:
        try:
            obav = self.apply_publish(actor, notification_id, datum_isteka)
            self.db.commit()
            return obav
        except Exception:
            self.db.rollback()
            raise

    def _resolve_recipients(self, targets) -> set[int]:
        user_ids: set[int] = set()
        for t in targets:
            if t.tip_cilja in CILJEVI_NEPODRZANI:
                raise ValidationBusinessError(
                    "Ciljanje CENTRALA/MALOPRODAJA nije podržano (nedostaje pouzdan HR podatak)."
                )
            if t.tip_cilja == CILJ_SVI:
                user_ids |= self.targeting.all_active_user_ids()
            elif t.tip_cilja == CILJ_ORGJED:
                user_ids |= self.targeting.user_ids_by_orgjed(t.vrednost)
            elif t.tip_cilja == CILJ_PLATNI_BROJ:
                uid = self.targeting.user_id_by_platni_broj(t.vrednost)
                if uid is not None:
                    user_ids.add(uid)
        return user_ids
