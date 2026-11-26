"""PITAJ HR - admin (GMX Portal, admin ili HR).

- Kategorije (sifarnik): lista, nova, izmena (bez brisanja; neaktivna se ne nudi za nova pitanja).
- Pitanja: lista po statusu/kategoriji, detalj sa prepiskom i imenom zaposlenog, odgovor,
  zatvaranje. Odgovor salje zaposlenom obavestenje i push (dogadjaj HR_QUESTION_ANSWERED);
  odgovor na dopunsko pitanje zatvara pitanje.
- Cesta pitanja: HR pise (ili prepravlja) tekst i objavljuje ga svima, bez imena."""

import datetime
import re
from collections.abc import Callable

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import (
    HrCategoryAlreadyExistsError,
    HrCategoryNotFoundError,
    HrFaqNotFoundError,
    HrQuestionAnswerNotAllowedError,
    HrQuestionCategoryInvalidError,
    HrQuestionInvalidStatusError,
    HrQuestionNotFoundError,
    ValidationBusinessError,
)
from app.models.hr_pitanje import (
    AUTOR_HR,
    STATUS_ODGOVORENO,
    STATUS_POSLATO,
    STATUS_ZATVORENO,
    STATUSI,
    HrCestoPitanje,
    HrKategorija,
    HrPitanje,
    HrPoruka,
)
from app.models.korisnik import Korisnik
from app.models.sistemski_dogadjaj import DOGADJAJ_TIP_HR_QUESTION_ANSWERED
from app.repositories.audit_repository import AuditRepository
from app.repositories.hr_question_repository import HrQuestionRepository
from app.repositories.system_event_repository import SystemEventRepository
from app.services.audit_service import AuditService
from app.services.hr_question_service import MAX_ODGOVOR, MAX_PITANJE, preview
from app.services.kudos_service import clean_text

SIFRA_RE = re.compile(r"^[A-Z0-9_]{1,30}$")
ENTITY_QUESTION = "HR_PITANJE"
ENTITY_CATEGORY = "HR_KATEGORIJA"
ENTITY_FAQ = "HR_CESTO_PITANJE"
AUDIT_ANSWERED = "ADMIN_HR_QUESTION_ANSWERED"
AUDIT_CLOSED = "ADMIN_HR_QUESTION_CLOSED"
AUDIT_CATEGORY_CREATED = "ADMIN_HR_CATEGORY_CREATED"
AUDIT_CATEGORY_UPDATED = "ADMIN_HR_CATEGORY_UPDATED"
AUDIT_FAQ_CREATED = "ADMIN_HR_FAQ_CREATED"
AUDIT_FAQ_UPDATED = "ADMIN_HR_FAQ_UPDATED"


def category_view(k: HrKategorija) -> dict:
    return {
        "sifra": k.sifra,
        "naziv": k.naziv,
        "redosled": int(k.redosled),
        "aktivna": k.aktivna == "D",
        "kreirao_platni_broj": k.kreirao_platni_broj,
        "izmenio_platni_broj": k.izmenio_platni_broj,
        "datum_kreiranja": k.datum_kreiranja,
        "datum_izmene": k.datum_izmene,
    }


class HrQuestionAdminService:
    def __init__(
        self,
        db: Session,
        repository: HrQuestionRepository | None = None,
        audit_service: AuditService | None = None,
        event_repository: SystemEventRepository | None = None,
        now_fn: Callable[[], datetime.datetime] | None = None,
    ):
        self.db = db
        self.repo = repository or HrQuestionRepository(db)
        self.audit_service = audit_service or AuditService(AuditRepository(db), izvor=get_settings().audit_source)
        self.events = event_repository or SystemEventRepository(db)
        self._now_fn = now_fn or datetime.datetime.now

    # ============================================================= kategorije
    def list_categories(self, aktivna: bool | None = None) -> list[dict]:
        flag = None if aktivna is None else ("D" if aktivna else "N")
        return [category_view(k) for k in self.repo.list_categories(flag)]

    def create_category(self, actor: Korisnik, sifra: str, naziv: str, redosled: int, aktivna: bool) -> dict:
        sifra_norm = (sifra or "").strip().upper()
        if not SIFRA_RE.match(sifra_norm):
            raise ValidationBusinessError("Šifra sme da sadrži samo velika slova, cifre i _ (najviše 30).")
        naziv = self._text(naziv, 100, "Naziv")
        try:
            if self.repo.get_category(sifra_norm) is not None:
                raise HrCategoryAlreadyExistsError()
            now = self._now_fn()
            kat = self.repo.add_category(
                HrKategorija(
                    sifra=sifra_norm,
                    naziv=naziv,
                    redosled=redosled,
                    aktivna="D" if aktivna else "N",
                    kreirao_platni_broj=actor.platni_broj,
                    izmenio_platni_broj=actor.platni_broj,
                    datum_kreiranja=now,
                    datum_izmene=now,
                )
            )
            self._audit(actor, AUDIT_CATEGORY_CREATED, ENTITY_CATEGORY, sifra_norm,
                        f"sifra={sifra_norm}; aktivna={kat.aktivna}")
            view = category_view(kat)
            self.db.commit()
            return view
        except IntegrityError as exc:  # konkurentan unos iste sifre
            self.db.rollback()
            raise HrCategoryAlreadyExistsError() from exc
        except Exception:
            self.db.rollback()
            raise

    def update_category(self, actor: Korisnik, sifra: str, naziv: str, redosled: int, aktivna: bool) -> dict:
        sifra_norm = (sifra or "").strip().upper()
        naziv = self._text(naziv, 100, "Naziv")
        try:
            kat = self.repo.get_category_for_update(sifra_norm)
            if kat is None:
                raise HrCategoryNotFoundError()
            flag = "D" if aktivna else "N"
            if (kat.naziv, int(kat.redosled), kat.aktivna) != (naziv, redosled, flag):
                kat.naziv = naziv
                kat.redosled = redosled
                kat.aktivna = flag
                kat.izmenio_platni_broj = actor.platni_broj
                kat.datum_izmene = self._now_fn()
                self.db.flush()
                self._audit(actor, AUDIT_CATEGORY_UPDATED, ENTITY_CATEGORY, sifra_norm,
                            f"sifra={sifra_norm}; aktivna={flag}")
            view = category_view(kat)
            self.db.commit()
            return view
        except Exception:
            self.db.rollback()
            raise

    # =============================================================== pitanja
    def list_questions(self, status: str | None, kategorija: str | None, page: int, page_size: int) -> dict:
        if status is not None:
            status = status.strip().upper()
            if status not in STATUSI:
                raise HrQuestionInvalidStatusError()
        kat = (kategorija or "").strip().upper() or None
        total, rows = self.repo.admin_list(status, kat, (page - 1) * page_size, page_size)
        first = self.repo.first_messages([int(p.id) for p in rows])
        people = self._people(rows, [])
        names = self.repo.category_names()
        orgjed_names = self.repo.orgjed_names({p.orgjed for p in rows if p.orgjed})
        items = []
        for p in rows:
            view = self._base(p, people, names, orgjed_names)
            m = first.get(int(p.id))
            view["pregled"] = preview(m.tekst if m else "")
            items.append(view)
        return {"items": items, "total": total, "page": page, "page_size": page_size}

    def get_question(self, pitanje_id: int) -> dict:
        p = self.repo.get_question(pitanje_id)
        if p is None:
            raise HrQuestionNotFoundError()
        return self._detail(p)

    def answer(self, actor: Korisnik, pitanje_id: int, tekst: str) -> dict:
        tekst = self._text(tekst, MAX_ODGOVOR, "Odgovor")
        try:
            p = self.repo.get_question_for_update(pitanje_id)
            if p is None:
                raise HrQuestionNotFoundError()
            if p.status != STATUS_POSLATO:
                raise HrQuestionAnswerNotAllowedError()
            now = self._now_fn()
            m = self.repo.add_message(
                HrPoruka(pitanje_id=int(p.id), autor=AUTOR_HR, korisnik_id=int(actor.id), tekst=tekst,
                         datum_kreiranja=now)
            )
            p.status = STATUS_ZATVORENO if p.dopuna_poslata == "D" else STATUS_ODGOVORENO
            p.procitano = "N"
            p.datum_odgovora = now
            p.datum_izmene = now
            self.db.flush()
            self.events.enqueue_if_absent(
                f"HR_QUESTION_ANSWERED:{int(p.id)}:{int(m.id)}",
                DOGADJAJ_TIP_HR_QUESTION_ANSWERED,
                int(p.id),
                str(int(m.id)),
                now,
            )
            self._audit(actor, AUDIT_ANSWERED, ENTITY_QUESTION, str(int(p.id)),
                        f"pitanje_id={int(p.id)}; status={p.status}")
            view = self._detail(p)
            self.db.commit()
            return view
        except Exception:
            self.db.rollback()
            raise

    def close(self, actor: Korisnik, pitanje_id: int) -> dict:
        try:
            p = self.repo.get_question_for_update(pitanje_id)
            if p is None:
                raise HrQuestionNotFoundError()
            if p.status != STATUS_ZATVORENO:
                p.status = STATUS_ZATVORENO
                p.datum_izmene = self._now_fn()
                self.db.flush()
                self._audit(actor, AUDIT_CLOSED, ENTITY_QUESTION, str(int(p.id)), f"pitanje_id={int(p.id)}")
            view = self._detail(p)
            self.db.commit()
            return view
        except Exception:
            self.db.rollback()
            raise

    # ========================================================= cesta pitanja
    def list_faq(self, aktivno: bool | None, kategorija: str | None) -> list[dict]:
        flag = None if aktivno is None else ("D" if aktivno else "N")
        kat = (kategorija or "").strip().upper() or None
        names = self.repo.category_names()
        return [self._faq_view(f, names) for f in self.repo.list_faq(flag, kat)]

    def create_faq(
        self,
        actor: Korisnik,
        kategorija_sifra: str,
        pitanje: str,
        odgovor: str,
        redosled: int,
        aktivno: bool,
        izvor_pitanje_id: int | None,
    ) -> dict:
        sifra = self._category_code(kategorija_sifra)
        pitanje = self._text(pitanje, MAX_PITANJE, "Pitanje")
        odgovor = self._text(odgovor, MAX_ODGOVOR, "Odgovor")
        try:
            if izvor_pitanje_id is not None and self.repo.get_question(izvor_pitanje_id) is None:
                raise HrQuestionNotFoundError()
            now = self._now_fn()
            f = self.repo.add_faq(
                HrCestoPitanje(
                    kategorija_sifra=sifra,
                    pitanje=pitanje,
                    odgovor=odgovor,
                    redosled=redosled,
                    aktivno="D" if aktivno else "N",
                    izvor_pitanje_id=izvor_pitanje_id,
                    kreirao_platni_broj=actor.platni_broj,
                    izmenio_platni_broj=actor.platni_broj,
                    datum_kreiranja=now,
                    datum_izmene=now,
                )
            )
            self._audit(actor, AUDIT_FAQ_CREATED, ENTITY_FAQ, str(int(f.id)),
                        f"faq_id={int(f.id)}; aktivno={f.aktivno}")
            view = self._faq_view(f, self.repo.category_names())
            self.db.commit()
            return view
        except Exception:
            self.db.rollback()
            raise

    def update_faq(
        self, actor: Korisnik, faq_id: int, kategorija_sifra: str, pitanje: str, odgovor: str, redosled: int,
        aktivno: bool,
    ) -> dict:
        sifra = self._category_code(kategorija_sifra)
        pitanje = self._text(pitanje, MAX_PITANJE, "Pitanje")
        odgovor = self._text(odgovor, MAX_ODGOVOR, "Odgovor")
        try:
            f = self.repo.get_faq_for_update(faq_id)
            if f is None:
                raise HrFaqNotFoundError()
            flag = "D" if aktivno else "N"
            if (f.kategorija_sifra, f.pitanje, f.odgovor, int(f.redosled), f.aktivno) != (
                sifra, pitanje, odgovor, redosled, flag
            ):
                f.kategorija_sifra = sifra
                f.pitanje = pitanje
                f.odgovor = odgovor
                f.redosled = redosled
                f.aktivno = flag
                f.izmenio_platni_broj = actor.platni_broj
                f.datum_izmene = self._now_fn()
                self.db.flush()
                self._audit(actor, AUDIT_FAQ_UPDATED, ENTITY_FAQ, str(int(f.id)),
                            f"faq_id={int(f.id)}; aktivno={flag}")
            view = self._faq_view(f, self.repo.category_names())
            self.db.commit()
            return view
        except Exception:
            self.db.rollback()
            raise

    # ================================================================ pomocno
    def _category_code(self, kategorija_sifra: str) -> str:
        sifra = (kategorija_sifra or "").strip().upper()
        if self.repo.get_category(sifra) is None:
            raise HrQuestionCategoryInvalidError()
        return sifra

    @staticmethod
    def _text(value: str, max_len: int, label: str) -> str:
        text = clean_text(value)
        if not text or len(text) > max_len:
            raise ValidationBusinessError(f"{label}: obavezno, najviše {max_len} znakova.")
        return text

    def _people(self, rows: list[HrPitanje], poruke: list[HrPoruka]) -> dict[int, Korisnik]:
        return self.repo.users_by_ids({int(p.korisnik_id) for p in rows} | {int(m.korisnik_id) for m in poruke})

    @staticmethod
    def _base(p: HrPitanje, people: dict[int, Korisnik], names: dict[str, str], orgjed_names: dict[str, str]) -> dict:
        k = people.get(int(p.korisnik_id))
        return {
            "id": int(p.id),
            "zaposleni": {
                "id": int(p.korisnik_id),
                "ime": k.ime if k else "",
                "prezime": k.prezime if k else "",
                "platni_broj": k.platni_broj if k else None,
                "orgjed_naziv": orgjed_names.get(p.orgjed or ""),
            },
            "kategorija_sifra": p.kategorija_sifra,
            "kategorija_naziv": names.get(p.kategorija_sifra, p.kategorija_sifra),
            "status": p.status,
            "dopuna_poslata": p.dopuna_poslata == "D",
            "odgovor_procitan": p.procitano == "D",
            "datum_kreiranja": p.datum_kreiranja,
            "datum_izmene": p.datum_izmene,
            "datum_odgovora": p.datum_odgovora,
        }

    def _detail(self, p: HrPitanje) -> dict:
        poruke = self.repo.messages(int(p.id))
        people = self._people([p], poruke)
        orgjed_names = self.repo.orgjed_names({p.orgjed} if p.orgjed else set())
        view = self._base(p, people, self.repo.category_names(), orgjed_names)

        def autor_ime(m: HrPoruka) -> str:
            k = people.get(int(m.korisnik_id))
            return f"{k.ime} {k.prezime}".strip() if k else ""

        view["poruke"] = [
            {"autor": m.autor, "autor_ime": autor_ime(m), "tekst": m.tekst, "datum_kreiranja": m.datum_kreiranja}
            for m in poruke
        ]
        return view

    @staticmethod
    def _faq_view(f: HrCestoPitanje, names: dict[str, str]) -> dict:
        return {
            "id": int(f.id),
            "kategorija_sifra": f.kategorija_sifra,
            "kategorija_naziv": names.get(f.kategorija_sifra, f.kategorija_sifra),
            "pitanje": f.pitanje,
            "odgovor": f.odgovor,
            "redosled": int(f.redosled),
            "aktivno": f.aktivno == "D",
            "izvor_pitanje_id": int(f.izvor_pitanje_id) if f.izvor_pitanje_id is not None else None,
            "datum_kreiranja": f.datum_kreiranja,
            "datum_izmene": f.datum_izmene,
        }

    def _audit(self, actor: Korisnik, akcija: str, tip: str, entitet_id: str, detalji: str) -> None:
        # Bez teksta pitanja i odgovora (licni podaci).
        self.audit_service.log(
            akcija,
            korisnik_id=actor.id,
            platni_broj=actor.platni_broj,
            tip_entiteta=tip,
            entitet_id=entitet_id,
            detalji=detalji,
        )
