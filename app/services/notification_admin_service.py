import datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import (
    InvalidNotificationStatusTransitionError,
    NotificationCategoryAlreadyExistsError,
    NotificationCategoryNotFoundError,
    NotificationNotFoundError,
)
from app.models.korisnik import Korisnik
from app.models.obavestenje import (
    OBAVESTENJE_STATUS_ARCHIVED,
    OBAVESTENJE_STATUS_PUBLISHED,
    Obavestenje,
    ObavestenjeKategorija,
)
from app.repositories.audit_repository import AuditRepository
from app.repositories.notification_repository import NotificationRepository
from app.services.audit_service import AuditAction, AuditService
from app.services.notification_publishing_service import NotificationPublishingService

# PK constraint kategorija - mapiramo samo taj konkretan konflikt na 409.
CATEGORY_PK_CONSTRAINT = "PK_PULS_OBAV_KATEGORIJE"


class NotificationAdminService:
    """Admin/HR (GMX Portal) modul OBAVESTENJA. Orkestrira kategorije, listu, detalj
    i statistiku; kreiranje/izmenu/objavu/arhiviranje delegira NotificationPublishingService-u
    (centralno mesto validacije i materijalizacije primalaca). Owns transakcije kategorija."""

    def __init__(
        self,
        db: Session,
        repository: NotificationRepository | None = None,
        publishing_service: NotificationPublishingService | None = None,
        audit_service: AuditService | None = None,
    ):
        self.db = db
        self.settings = get_settings()
        self.repo = repository or NotificationRepository(db)
        self.audit_service = audit_service or AuditService(
            AuditRepository(db), izvor=self.settings.audit_source
        )
        self.publishing = publishing_service or NotificationPublishingService(
            db, repository=self.repo, audit_service=self.audit_service
        )
        # Deli isti push-delivery repo kao publishing (jedan izvor, ista sesija).
        self.push_delivery = self.publishing.push_delivery

    # ==================================================================== KATEGORIJE
    def list_categories(self, aktivna: bool | None) -> list[ObavestenjeKategorija]:
        return self.repo.list_categories(aktivna)

    def create_category(self, actor: Korisnik, sifra: str, naziv: str, aktivna: bool, redosled):
        try:
            now = datetime.datetime.now()
            kat = self.repo.add_category(
                ObavestenjeKategorija(
                    sifra=sifra,
                    naziv=naziv,
                    aktivna="D" if aktivna else "N",
                    redosled=redosled,
                    datum_kreiranja=now,
                )
            )
            self.audit_service.log(
                AuditAction.NOTIFICATION_CATEGORY_CREATED,
                korisnik_id=actor.id,
                platni_broj=actor.platni_broj,
                tip_entiteta="OBAVESTENJE_KATEGORIJA",
                entitet_id=kat.sifra,
            )
            self.db.commit()
            return kat
        except IntegrityError as exc:
            # Samo PK/unique konflikt sifre -> 409; sve ostalo se propagira (ne maskira).
            self.db.rollback()
            if CATEGORY_PK_CONSTRAINT in str(getattr(exc, "orig", exc)).upper():
                raise NotificationCategoryAlreadyExistsError() from exc
            raise
        except Exception:
            self.db.rollback()
            raise

    def update_category(self, actor: Korisnik, sifra: str, naziv: str, aktivna: bool, redosled):
        try:
            kat = self.repo.get_category(sifra)
            if kat is None:
                raise NotificationCategoryNotFoundError()
            kat.naziv = naziv
            kat.aktivna = "D" if aktivna else "N"
            kat.redosled = redosled
            kat.datum_izmene = datetime.datetime.now()
            self.audit_service.log(
                AuditAction.NOTIFICATION_CATEGORY_UPDATED,
                korisnik_id=actor.id,
                platni_broj=actor.platni_broj,
                tip_entiteta="OBAVESTENJE_KATEGORIJA",
                entitet_id=kat.sifra,
            )
            self.db.commit()
            return kat
        except Exception:
            self.db.rollback()
            raise

    # =================================================================== OBAVESTENJA
    def list_notifications(self, status, category, datum_od, datum_do, page, page_size) -> dict:
        rows, total = self.repo.admin_list(status, category, datum_od, datum_do, page, page_size)
        return {
            "items": [_list_view(r) for r in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    def get_detail(self, notification_id: int) -> dict:
        obav = self.repo.get_notification(notification_id)
        if obav is None:
            raise NotificationNotFoundError()
        return self._detail_view(obav)

    def create(self, actor: Korisnik, payload) -> dict:
        # Jedna transakcija: apply (bez commit) -> flush -> sastavi detalj -> commit.
        # Ako sastavljanje detalja padne, rollback ponistava celu izmenu (bez 500 nad
        # vec commitovanom promenom). Posle commit-a NEMA novih DB upita.
        try:
            obav = self.publishing.apply_create_draft(actor, payload)
            self.db.flush()
            detail = self._detail_view(obav)
            self.db.commit()
            return detail
        except Exception:
            self.db.rollback()
            raise

    def update(self, actor: Korisnik, notification_id: int, payload) -> dict:
        try:
            obav = self.publishing.apply_update_draft(actor, notification_id, payload)
            self.db.flush()
            detail = self._detail_view(obav)
            self.db.commit()
            return detail
        except Exception:
            self.db.rollback()
            raise

    def change_status(self, actor: Korisnik, notification_id: int, novi_status: str, datum_isteka) -> dict:
        try:
            if novi_status == OBAVESTENJE_STATUS_PUBLISHED:
                obav = self.publishing.apply_publish(actor, notification_id, datum_isteka)
            elif novi_status == OBAVESTENJE_STATUS_ARCHIVED:
                obav = self.publishing.apply_archive(actor, notification_id)
            else:
                # Npr. ciljni DRAFT: nedozvoljen prelaz.
                raise InvalidNotificationStatusTransitionError()
            # Flush nove recipient redove PRE racunanja statistike u detalju.
            self.db.flush()
            detail = self._detail_view(obav)
            self.db.commit()
            return detail
        except Exception:
            self.db.rollback()
            raise

    def get_stats(self, notification_id: int) -> dict:
        obav = self.repo.get_notification(notification_id)
        if obav is None:
            raise NotificationNotFoundError()
        ukupno, procitano = self.repo.recipient_counts(notification_id)
        procenat = round((procitano / ukupno * 100), 2) if ukupno else 0.0
        # Aditivno: push statistika. push_sent = "FCM prihvatio", NE potvrda dostave uredjaju.
        push = self.push_delivery.stats_for_notification(notification_id)
        return {
            "notification_id": notification_id,
            "broj_primalaca": ukupno,
            "broj_procitanih": procitano,
            "broj_neprocitanih": ukupno - procitano,
            "procenat_procitanih": procenat,
            **push,
        }

    def resend_unread(self, actor: Korisnik, notification_id: int) -> dict:
        # Jedna transakcija: apply_resend (bez commit) -> pripremi rezultat -> commit.
        try:
            affected = self.publishing.apply_resend_unread(actor, notification_id)
            self.db.flush()
            result = {"notification_id": notification_id, "resent_count": affected}
            self.db.commit()
            return result
        except Exception:
            self.db.rollback()
            raise

    # ----------------------------------------------------------------- helpers
    def _detail_view(self, obav: Obavestenje) -> dict:
        kat = self.repo.get_category(obav.kategorija_sifra)
        ukupno, procitano = self.repo.recipient_counts(obav.id)
        targets = self.repo.get_targets(obav.id)
        return {
            "id": obav.id,
            "kategorija": {
                "sifra": obav.kategorija_sifra,
                "naziv": kat.naziv if kat else obav.kategorija_sifra,
            },
            "naslov": obav.naslov,
            "kratak_tekst": obav.kratak_tekst,
            "sadrzaj": obav.sadrzaj,
            "status": obav.status,
            "akcija": {
                "tip": obav.akcija_tip,
                "resurs_id": int(obav.resurs_id) if obav.resurs_id is not None else None,
                "url": obav.akcija_url,
            },
            "ciljevi": [{"tip_cilja": t.tip_cilja, "vrednost": t.vrednost} for t in targets],
            "kreirao_platni_broj": obav.kreirao_platni_broj,
            "datum_objave": obav.datum_objave,
            "datum_isteka": obav.datum_isteka,
            "datum_kreiranja": obav.datum_kreiranja,
            "datum_izmene": obav.datum_izmene,
            "broj_primalaca": ukupno,
            "broj_procitanih": procitano,
            "broj_neprocitanih": ukupno - procitano,
        }


def _list_view(row) -> dict:
    ukupno = int(row.broj_primalaca)
    procitano = int(row.broj_procitanih)
    return {
        "id": row.id,
        "kategorija": {"sifra": row.kategorija_sifra, "naziv": row.kategorija_naziv},
        "naslov": row.naslov,
        "kratak_tekst": row.kratak_tekst,
        "status": row.status,
        "akcija": {
            "tip": row.akcija_tip,
            "resurs_id": int(row.resurs_id) if row.resurs_id is not None else None,
            "url": row.akcija_url,
        },
        "kreirao_platni_broj": row.kreirao_platni_broj,
        "datum_objave": row.datum_objave,
        "datum_isteka": row.datum_isteka,
        "datum_kreiranja": row.datum_kreiranja,
        "datum_izmene": row.datum_izmene,
        "broj_primalaca": ukupno,
        "broj_procitanih": procitano,
        "broj_neprocitanih": ukupno - procitano,
    }
