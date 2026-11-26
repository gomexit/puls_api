"""HVALA, KOLEGA! - zaposleni (Bearer).

- Modul vidi zaposleni kome je ZAHVALNICE ukljucen; inace 404 KUDOS_NOT_AVAILABLE.
- Zahvalnica se objavljuje odmah (bez odobrenja HR-a). Zastita: ne sebi, najvise
  DNEVNI_LIMIT dnevno, filter neprimerenih reci, prijave kolega (PRIJAVA_PRAG prijava
  sklanja zahvalnicu do pregleda HR-a).
- Primalac dobija SISTEM obavestenje i push (dogadjaj KUDOS_RECEIVED, worker).
- Pretraga kolega vraca samo ime, prezime i naziv org. jedinice - nikad telefon ni
  platni broj; samo aktivni zaposleni kojima je modul ukljucen."""

import datetime
from collections.abc import Callable

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import (
    KudosCannotReportError,
    KudosDailyLimitError,
    KudosInappropriateError,
    KudosNotAvailableError,
    KudosNotFoundError,
    KudosRecipientInvalidError,
    KudosSelfError,
    ValidationBusinessError,
)
from app.models.korisnik import (
    STATUS_NALOGA_OMOGUCEN,
    STATUS_ZAPOSLENJA_AKTIVAN,
    Korisnik,
)
from app.models.sistemski_dogadjaj import DOGADJAJ_TIP_KUDOS_RECEIVED
from app.models.zahvalnica import (
    POVODI,
    STATUS_NA_PROVERI,
    STATUS_OBJAVLJENA,
    Zahvalnica,
    ZahvalnicaPrijava,
)
from app.repositories.configuration_repository import ConfigurationRepository
from app.repositories.kudos_repository import KudosRepository
from app.repositories.module_access_repository import ModuleAccessRepository
from app.repositories.system_event_repository import SystemEventRepository
from app.services.kudos_text_filter import is_inappropriate
from app.services.module_access_service import ModuleAccessService

MODULE_CODE = "ZAHVALNICE"
DNEVNI_LIMIT = 5
PRIJAVA_PRAG = 3
MAX_TEKST = 280
PRETRAGA_MIN = 3
PRETRAGA_LIMIT = 20

OPSEG_PRODAVNICA = "prodavnica"
OPSEG_SVI = "svi"
SMER_PRIMLJENE = "primljene"
SMER_POSLATE = "poslate"


def clean_text(value: str | None) -> str:
    """Trim i jedan razmak umesto niza praznina (novi redovi se cuvaju, najvise jedan prazan red)."""
    lines = [" ".join(line.split()) for line in (value or "").replace("\r\n", "\n").split("\n")]
    out: list[str] = []
    for line in lines:
        if line or (out and out[-1]):
            out.append(line)
    return "\n".join(out).strip()


class KudosService:
    def __init__(
        self,
        db: Session,
        repository: KudosRepository | None = None,
        module_access: ModuleAccessService | None = None,
        event_repository: SystemEventRepository | None = None,
        now_fn: Callable[[], datetime.datetime] | None = None,
    ):
        self.db = db
        self.repo = repository or KudosRepository(db)
        self.module_access = module_access or ModuleAccessService(
            ConfigurationRepository(db), ModuleAccessRepository(db)
        )
        self.events = event_repository or SystemEventRepository(db)
        self._now_fn = now_fn or datetime.datetime.now

    def _require_module(self, korisnik: Korisnik) -> None:
        if not self.module_access.is_enabled(korisnik, MODULE_CODE):
            raise KudosNotAvailableError()

    # ================================================================ pregled
    def feed(self, korisnik: Korisnik, opseg: str, page: int, page_size: int) -> dict:
        self._require_module(korisnik)
        orgjed = None
        if opseg == OPSEG_PRODAVNICA:
            orgjed = self.repo.primary_orgjed(int(korisnik.id))
            if orgjed is None:
                return {"items": [], "ima_jos": False, "opseg": opseg}
        rows = self.repo.feed(orgjed, (page - 1) * page_size, page_size + 1)
        return {"items": self._views(rows[:page_size], korisnik), "ima_jos": len(rows) > page_size, "opseg": opseg}

    def mine(self, korisnik: Korisnik, smer: str, page: int, page_size: int) -> dict:
        self._require_module(korisnik)
        kid = int(korisnik.id)
        try:
            if smer == SMER_POSLATE:
                rows = self.repo.sent(kid, (page - 1) * page_size, page_size + 1)
            else:
                rows = self.repo.received(kid, (page - 1) * page_size, page_size + 1)
                if page == 1 and self.repo.mark_received_read(kid):
                    self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        return {
            "items": self._views(rows[:page_size], korisnik, with_status=smer == SMER_POSLATE),
            "ima_jos": len(rows) > page_size,
            "smer": smer,
        }

    def badge_count(self, korisnik: Korisnik) -> int:
        """Broj neprocitanih primljenih zahvalnica (za "Moj kutak")."""
        return self.repo.unread_count(int(korisnik.id))

    def search_colleagues(self, korisnik: Korisnik, q: str) -> list[dict]:
        self._require_module(korisnik)
        tokens = [t for t in clean_text(q).replace("\n", " ").split(" ") if t][:3]
        if not tokens or len("".join(tokens)) < PRETRAGA_MIN:
            return []
        out = []
        found = self.repo.search_colleagues(tokens, int(korisnik.id), PRETRAGA_LIMIT)
        orgjed = {int(k.id): self.repo.primary_orgjed(int(k.id)) for k in found}
        names = self.repo.orgjed_names({s for s in orgjed.values() if s})
        for k in found:
            if not self.module_access.is_enabled(k, MODULE_CODE):
                continue
            out.append(
                {
                    "id": int(k.id),
                    "ime": k.ime,
                    "prezime": k.prezime,
                    "orgjed_naziv": names.get(orgjed[int(k.id)] or ""),
                }
            )
        return out

    # ================================================================= slanje
    def send(self, korisnik: Korisnik, primalac_id: int, povod: str, tekst: str) -> dict:
        self._require_module(korisnik)
        if primalac_id == int(korisnik.id):
            raise KudosSelfError()
        povod = (povod or "").strip().upper()
        tekst = clean_text(tekst)
        if povod not in POVODI or not tekst or len(tekst) > MAX_TEKST:
            raise ValidationBusinessError("Izaberite povod i napišite tekst do 280 znakova.")
        if is_inappropriate(tekst):
            raise KudosInappropriateError()
        try:
            now = self._now_fn()
            primalac = self.repo.get_user(primalac_id)
            if (
                primalac is None
                or primalac.status_zaposlenja != STATUS_ZAPOSLENJA_AKTIVAN
                or primalac.status_naloga != STATUS_NALOGA_OMOGUCEN
                or not self.module_access.is_enabled(primalac, MODULE_CODE)
            ):
                raise KudosRecipientInvalidError()
            pocetak_dana = datetime.datetime.combine(now.date(), datetime.time.min)
            if self.repo.count_sent_since(int(korisnik.id), pocetak_dana) >= DNEVNI_LIMIT:
                raise KudosDailyLimitError()
            z = self.repo.add(
                Zahvalnica(
                    posiljalac_id=int(korisnik.id),
                    primalac_id=primalac_id,
                    posiljalac_orgjed=self.repo.primary_orgjed(int(korisnik.id)),
                    primalac_orgjed=self.repo.primary_orgjed(primalac_id),
                    povod=povod,
                    tekst=tekst,
                    status=STATUS_OBJAVLJENA,
                    proverena="N",
                    procitana="N",
                    datum_kreiranja=now,
                    datum_izmene=None,
                    izmenio_korisnik_id=None,
                )
            )
            self.events.enqueue_if_absent(
                f"KUDOS_RECEIVED:{int(z.id)}", DOGADJAJ_TIP_KUDOS_RECEIVED, int(z.id), None, now
            )
            view = self._views([z], korisnik, with_status=True)[0]
            self.db.commit()
            return view
        except Exception:
            self.db.rollback()
            raise

    # ================================================================ prijava
    def report(self, korisnik: Korisnik, zahvalnica_id: int, razlog: str | None) -> dict:
        self._require_module(korisnik)
        try:
            z = self.repo.get_for_update(zahvalnica_id)
            if z is None or z.status != STATUS_OBJAVLJENA:
                raise KudosNotFoundError()
            if int(z.posiljalac_id) == int(korisnik.id):
                raise KudosCannotReportError()
            if not self.repo.has_report(int(z.id), int(korisnik.id)):
                self.repo.add_report(
                    ZahvalnicaPrijava(
                        zahvalnica_id=int(z.id),
                        korisnik_id=int(korisnik.id),
                        razlog=(clean_text(razlog)[:200] or None),
                        datum_kreiranja=self._now_fn(),
                    )
                )
                if z.proverena != "D" and self.repo.report_count(int(z.id)) >= PRIJAVA_PRAG:
                    z.status = STATUS_NA_PROVERI
                    z.datum_izmene = self._now_fn()
            self.db.commit()
            return {"prijavljena": True}
        except IntegrityError:
            # Ista prijava u isto vreme (UQ): vec je prijavljeno.
            self.db.rollback()
            return {"prijavljena": True}
        except Exception:
            self.db.rollback()
            raise

    def _views(self, rows: list[Zahvalnica], korisnik: Korisnik, with_status: bool = False) -> list[dict]:
        return kudos_views(self.repo, rows, int(korisnik.id), with_status)


def kudos_views(repo: KudosRepository, rows: list[Zahvalnica], me: int, with_status: bool = False) -> list[dict]:
    """Prikaz zahvalnica: osobe samo sa imenom, prezimenom i nazivom org. jedinice."""
    users = repo.users_by_ids({int(z.posiljalac_id) for z in rows} | {int(z.primalac_id) for z in rows})
    names = repo.orgjed_names({s for z in rows for s in (z.posiljalac_orgjed, z.primalac_orgjed) if s})

    def person(uid: int, orgjed: str | None) -> dict:
        k = users.get(uid)
        return {
            "id": uid,
            "ime": k.ime if k else "",
            "prezime": k.prezime if k else "",
            "orgjed_naziv": names.get(orgjed or ""),
        }

    return [
        {
            "id": int(z.id),
            "posiljalac": person(int(z.posiljalac_id), z.posiljalac_orgjed),
            "primalac": person(int(z.primalac_id), z.primalac_orgjed),
            "povod": z.povod,
            "povod_naziv": POVODI.get(z.povod, z.povod),
            "tekst": z.tekst,
            "datum_kreiranja": z.datum_kreiranja,
            "moja": me in (int(z.posiljalac_id), int(z.primalac_id)),
            "mogu_prijaviti": int(z.posiljalac_id) != me,
            "status": z.status if with_status else None,
        }
        for z in rows
    ]
