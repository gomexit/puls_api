import datetime
from collections.abc import Callable

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import NotificationNotFoundError
from app.models.korisnik import Korisnik
from app.models.obavestenje import ObavestenjePrimalac
from app.repositories.audit_repository import AuditRepository
from app.repositories.notification_repository import NotificationRepository
from app.services.audit_service import AuditAction, AuditService


class NotificationService:
    """Employee Inbox modul OBAVESTENJA. Owns the transaction boundary.

    Vidljivost je striktno ogranicena na materijalizovane primaoce trenutnog
    korisnika i na dostupna (PUBLISHED, u periodu) obavestenja. Tudji/nedostupni
    ID uvek daje isti NOTIFICATION_NOT_FOUND (ne otkriva postojanje)."""

    def __init__(
        self,
        db: Session,
        repository: NotificationRepository | None = None,
        audit_service: AuditService | None = None,
        now_fn: Callable[[], datetime.datetime] = datetime.datetime.now,
    ):
        self.db = db
        self.settings = get_settings()
        self.repo = repository or NotificationRepository(db)
        self.audit_service = audit_service or AuditService(
            AuditRepository(db), izvor=self.settings.audit_source
        )
        self._now = now_fn

    # ------------------------------------------------------------------- lista
    def list_inbox(
        self,
        korisnik: Korisnik,
        page: int,
        page_size: int,
        read_status: str,
        category: str | None,
    ) -> dict:
        now = self._now()
        rows, total = self.repo.list_inbox(
            korisnik.id, now, read_status, category, page, page_size
        )
        unread_count = self.repo.count_unread(korisnik.id, now)
        items = [_item_view(obav, primalac, kat) for (obav, primalac, kat) in rows]
        return {
            "items": items,
            "page": page,
            "page_size": page_size,
            "total": total,
            "has_more": page * page_size < total,
            "unread_count": unread_count,
        }

    def unread_count(self, korisnik: Korisnik) -> int:
        return self.repo.count_unread(korisnik.id, self._now())

    # ------------------------------------------------------------------ detalj
    def get_detail(self, korisnik: Korisnik, notification_id: int) -> dict:
        # GET detalja NE menja stanje (ne oznacava kao procitano).
        row = self.repo.get_inbox_item(korisnik.id, notification_id, self._now())
        if row is None:
            raise NotificationNotFoundError()
        obav, primalac, kat = row
        view = _item_view(obav, primalac, kat)
        view["sadrzaj"] = obav.sadrzaj
        return view

    # --------------------------------------------------------------- read/unread
    def mark_read(self, korisnik: Korisnik, notification_id: int) -> tuple[ObavestenjePrimalac, int]:
        try:
            now = self._now()
            primalac = self._require_recipient(korisnik, notification_id, now)
            # Idempotentno: originalni DATUM_CITANJA se ne menja pri ponovljenom pozivu.
            if primalac.procitano != "D":
                primalac.procitano = "D"
                primalac.datum_citanja = now
                primalac.datum_izmene = now
                self.audit_service.log(
                    AuditAction.NOTIFICATION_READ,
                    korisnik_id=korisnik.id,
                    platni_broj=korisnik.platni_broj,
                    tip_entiteta="OBAVESTENJE",
                    entitet_id=str(notification_id),
                )
            # SessionLocal je autoflush=False: eksplicitni flush da count_unread vidi
            # izmenu. Sve (izmena + audit + brojanje) se zavrsava PRE commit-a; ako flush
            # ili count padne, rollback ponistava i izmenu i audit. Bez upita posle commit-a.
            self.db.flush()
            unread = self.repo.count_unread(korisnik.id, now)
            self.db.commit()
            return primalac, unread
        except Exception:
            self.db.rollback()
            raise

    def mark_unread(self, korisnik: Korisnik, notification_id: int) -> tuple[ObavestenjePrimalac, int]:
        try:
            now = self._now()
            primalac = self._require_recipient(korisnik, notification_id, now)
            if primalac.procitano != "N":
                primalac.procitano = "N"
                primalac.datum_citanja = None
                primalac.datum_izmene = now
                self.audit_service.log(
                    AuditAction.NOTIFICATION_MARKED_UNREAD,
                    korisnik_id=korisnik.id,
                    platni_broj=korisnik.platni_broj,
                    tip_entiteta="OBAVESTENJE",
                    entitet_id=str(notification_id),
                )
            # Isti transakcioni redosled kao mark_read: flush -> count -> commit.
            self.db.flush()
            unread = self.repo.count_unread(korisnik.id, now)
            self.db.commit()
            return primalac, unread
        except Exception:
            self.db.rollback()
            raise

    def _require_recipient(
        self, korisnik: Korisnik, notification_id: int, now: datetime.datetime
    ) -> ObavestenjePrimalac:
        # Obavestenje mora biti trenutno dostupno...
        if self.repo.get_available_notification(notification_id, now) is None:
            raise NotificationNotFoundError()
        # ...i mora postojati red primaoca za OVOG korisnika (menja samo svoj red).
        primalac = self.repo.get_recipient_for_update(notification_id, korisnik.id)
        if primalac is None:
            raise NotificationNotFoundError()
        return primalac


def _item_view(obav, primalac, kat) -> dict:
    return {
        "id": obav.id,
        "kategorija": {"sifra": kat.sifra, "naziv": kat.naziv},
        "naslov": obav.naslov,
        "kratak_tekst": obav.kratak_tekst,
        "datum_objave": obav.datum_objave,
        "datum_isteka": obav.datum_isteka,
        "procitano": primalac.procitano == "D",
        "datum_citanja": primalac.datum_citanja,
        "akcija": {
            "tip": obav.akcija_tip,
            "resurs_id": int(obav.resurs_id) if obav.resurs_id is not None else None,
            "url": obav.akcija_url,
        },
    }
