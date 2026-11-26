"""HVALA, KOLEGA! - admin (GMX Portal, admin ili HR).

Zahvalnice se objavljuju bez odobrenja; portal vidi prijavljene (NA_PROVERI posle
PRIJAVA_PRAG prijava), sakriva ih ili vraca. Vracena zahvalnica dobija PROVERENA='D'
i nove prijave je vise ne sklanjaju same. Imena prijavilaca se ne prikazuju."""

import datetime
from collections.abc import Callable

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import KudosInvalidStatusError, KudosNotFoundError
from app.models.korisnik import Korisnik
from app.models.zahvalnica import (
    STATUS_OBJAVLJENA,
    STATUS_SAKRIVENA,
    STATUSI,
    Zahvalnica,
)
from app.repositories.audit_repository import AuditRepository
from app.repositories.kudos_repository import KudosRepository
from app.services.audit_service import AuditService
from app.services.kudos_service import kudos_views

ENTITY_KUDOS = "ZAHVALNICA"
AUDIT_HIDDEN = "ADMIN_KUDOS_HIDDEN"
AUDIT_RESTORED = "ADMIN_KUDOS_RESTORED"


class KudosAdminService:
    def __init__(
        self,
        db: Session,
        repository: KudosRepository | None = None,
        audit_service: AuditService | None = None,
        now_fn: Callable[[], datetime.datetime] | None = None,
    ):
        self.db = db
        self.repo = repository or KudosRepository(db)
        self.audit_service = audit_service or AuditService(AuditRepository(db), izvor=get_settings().audit_source)
        self._now_fn = now_fn or datetime.datetime.now

    def list(self, status: str | None, page: int, page_size: int) -> dict:
        if status is not None:
            status = status.strip().upper()
            if status not in STATUSI:
                raise KudosInvalidStatusError()
        total, rows = self.repo.admin_list(status, (page - 1) * page_size, page_size)
        counts = self.repo.report_counts([int(z.id) for z in rows])
        return {
            "items": [self._view(z, counts.get(int(z.id), 0)) for z in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    def get(self, zahvalnica_id: int) -> dict:
        z = self.repo.get(zahvalnica_id)
        if z is None:
            raise KudosNotFoundError()
        prijave = self.repo.reports(int(z.id))
        view = self._view(z, len(prijave))
        view["prijave"] = [{"razlog": p.razlog, "datum_kreiranja": p.datum_kreiranja} for p in prijave]
        return view

    def hide(self, actor: Korisnik, zahvalnica_id: int) -> dict:
        return self._set_status(actor, zahvalnica_id, STATUS_SAKRIVENA, AUDIT_HIDDEN)

    def restore(self, actor: Korisnik, zahvalnica_id: int) -> dict:
        return self._set_status(actor, zahvalnica_id, STATUS_OBJAVLJENA, AUDIT_RESTORED)

    def _set_status(self, actor: Korisnik, zahvalnica_id: int, status: str, akcija: str) -> dict:
        try:
            z = self.repo.get_for_update(zahvalnica_id)
            if z is None:
                raise KudosNotFoundError()
            z.status = status
            z.proverena = "D"
            z.datum_izmene = self._now_fn()
            z.izmenio_korisnik_id = int(actor.id)
            self.audit_service.log(
                akcija,
                korisnik_id=actor.id,
                platni_broj=actor.platni_broj,
                tip_entiteta=ENTITY_KUDOS,
                entitet_id=str(int(z.id)),
                detalji=f"zahvalnica_id={int(z.id)}; status={status}",
            )
            self.db.flush()
            view = self.get(int(z.id))
            self.db.commit()
            return view
        except Exception:
            self.db.rollback()
            raise

    def _view(self, z: Zahvalnica, broj_prijava: int) -> dict:
        # Isti prikaz osoba kao u aplikaciji (ime, prezime, org. jedinica), bez platnog broja.
        base = kudos_views(self.repo, [z], 0, with_status=True)[0]
        base.pop("moja", None)
        base.pop("mogu_prijaviti", None)
        base["broj_prijava"] = broj_prijava
        base["proverena"] = z.proverena == "D"
        base["datum_izmene"] = z.datum_izmene
        return base
