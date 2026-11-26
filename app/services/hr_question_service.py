"""PITAJ HR - zaposleni (Bearer).

- Modul vidi zaposleni kome je PITAJ_HR ukljucen; inace 404 HR_QUESTION_NOT_AVAILABLE.
- Pitanje je privatno: vide ga samo zaposleni koji ga je postavio i HR (portal). Pitanja
  se salju samo sa imenom (bez anonimnih).
- Tok: POSLATO -> (HR odgovori) ODGOVORENO -> (jedno dopunsko pitanje) POSLATO ->
  (HR odgovori) ZATVORENO. HR moze da zatvori pitanje u svakom trenutku.
- Najvise DNEVNI_LIMIT novih pitanja dnevno (dopuna se ne broji).
- Aplikaciji se ime HR-ovca koji je odgovorio ne vraca ("HR sluzba").
- "Cesta pitanja" su javni odgovori koje HR objavljuje bez imena onoga ko je pitao."""

import datetime
from collections.abc import Callable

from sqlalchemy.orm import Session

from app.core.exceptions import (
    HrQuestionCategoryInvalidError,
    HrQuestionDailyLimitError,
    HrQuestionFollowUpNotAllowedError,
    HrQuestionNotAvailableError,
    HrQuestionNotFoundError,
    ValidationBusinessError,
)
from app.models.hr_pitanje import (
    AUTOR_ZAPOSLENI,
    STATUS_ODGOVORENO,
    STATUS_POSLATO,
    HrPitanje,
    HrPoruka,
)
from app.models.korisnik import Korisnik
from app.repositories.configuration_repository import ConfigurationRepository
from app.repositories.hr_question_repository import HrQuestionRepository
from app.repositories.module_access_repository import ModuleAccessRepository
from app.services.kudos_service import clean_text
from app.services.module_access_service import ModuleAccessService

MODULE_CODE = "PITAJ_HR"
DNEVNI_LIMIT = 5
MAX_PITANJE = 1000
MAX_ODGOVOR = 2000
PREGLED_DUZINA = 120


def preview(text: str, length: int = PREGLED_DUZINA) -> str:
    one_line = " ".join((text or "").split())
    return one_line if len(one_line) <= length else one_line[: length - 1].rstrip() + "…"


class HrQuestionService:
    def __init__(
        self,
        db: Session,
        repository: HrQuestionRepository | None = None,
        module_access: ModuleAccessService | None = None,
        now_fn: Callable[[], datetime.datetime] | None = None,
    ):
        self.db = db
        self.repo = repository or HrQuestionRepository(db)
        self.module_access = module_access or ModuleAccessService(
            ConfigurationRepository(db), ModuleAccessRepository(db)
        )
        self._now_fn = now_fn or datetime.datetime.now

    def _require_module(self, korisnik: Korisnik) -> None:
        if not self.module_access.is_enabled(korisnik, MODULE_CODE):
            raise HrQuestionNotAvailableError()

    # ============================================================== sifarnici
    def categories(self, korisnik: Korisnik) -> list[dict]:
        self._require_module(korisnik)
        return [{"sifra": k.sifra, "naziv": k.naziv} for k in self.repo.list_categories("D")]

    def faq(self, korisnik: Korisnik, kategorija: str | None) -> list[dict]:
        self._require_module(korisnik)
        kat = (kategorija or "").strip().upper() or None
        names = self.repo.category_names()
        active = {k.sifra for k in self.repo.list_categories("D")}
        return [
            {
                "id": int(f.id),
                "kategorija_sifra": f.kategorija_sifra,
                "kategorija_naziv": names.get(f.kategorija_sifra, f.kategorija_sifra),
                "pitanje": f.pitanje,
                "odgovor": f.odgovor,
            }
            for f in self.repo.list_faq("D", kat)
            if f.kategorija_sifra in active
        ]

    # =============================================================== pitanja
    def mine(self, korisnik: Korisnik, page: int, page_size: int) -> dict:
        self._require_module(korisnik)
        rows = self.repo.mine(int(korisnik.id), (page - 1) * page_size, page_size + 1)
        rows_page = rows[:page_size]
        first = self.repo.first_messages([int(p.id) for p in rows_page])
        names = self.repo.category_names()
        return {
            "items": [self._summary(p, first.get(int(p.id)), names) for p in rows_page],
            "ima_jos": len(rows) > page_size,
        }

    def badge_count(self, korisnik: Korisnik) -> int:
        """Broj mojih pitanja sa odgovorom koji jos nisam otvorio (za "Moj kutak")."""
        return self.repo.unread_count(int(korisnik.id))

    def detail(self, korisnik: Korisnik, pitanje_id: int) -> dict:
        """Prepiska; otvaranje oznacava odgovor procitanim."""
        self._require_module(korisnik)
        try:
            p = self.repo.get_question(pitanje_id)
            if p is None or int(p.korisnik_id) != int(korisnik.id):
                raise HrQuestionNotFoundError()
            if p.procitano == "N":
                p.procitano = "D"
                self.db.flush()
            view = self._detail(p)
            self.db.commit()
            return view
        except Exception:
            self.db.rollback()
            raise

    def ask(self, korisnik: Korisnik, kategorija_sifra: str, tekst: str) -> dict:
        self._require_module(korisnik)
        tekst = self._clean(tekst)
        sifra = (kategorija_sifra or "").strip().upper()
        try:
            kat = self.repo.get_category(sifra)
            if kat is None or kat.aktivna != "D":
                raise HrQuestionCategoryInvalidError()
            now = self._now_fn()
            pocetak_dana = datetime.datetime.combine(now.date(), datetime.time.min)
            if self.repo.count_asked_since(int(korisnik.id), pocetak_dana) >= DNEVNI_LIMIT:
                raise HrQuestionDailyLimitError()
            p = self.repo.add_question(
                HrPitanje(
                    korisnik_id=int(korisnik.id),
                    kategorija_sifra=sifra,
                    orgjed=self.repo.primary_orgjed(int(korisnik.id)),
                    status=STATUS_POSLATO,
                    dopuna_poslata="N",
                    procitano="D",
                    datum_kreiranja=now,
                    datum_izmene=now,
                    datum_odgovora=None,
                )
            )
            self.repo.add_message(
                HrPoruka(pitanje_id=int(p.id), autor=AUTOR_ZAPOSLENI, korisnik_id=int(korisnik.id), tekst=tekst,
                         datum_kreiranja=now)
            )
            view = self._detail(p)
            self.db.commit()
            return view
        except Exception:
            self.db.rollback()
            raise

    def follow_up(self, korisnik: Korisnik, pitanje_id: int, tekst: str) -> dict:
        """Jedno dopunsko pitanje posle odgovora HR-a."""
        self._require_module(korisnik)
        tekst = self._clean(tekst)
        try:
            p = self.repo.get_question_for_update(pitanje_id)
            if p is None or int(p.korisnik_id) != int(korisnik.id):
                raise HrQuestionNotFoundError()
            if p.status != STATUS_ODGOVORENO or p.dopuna_poslata == "D":
                raise HrQuestionFollowUpNotAllowedError()
            now = self._now_fn()
            self.repo.add_message(
                HrPoruka(pitanje_id=int(p.id), autor=AUTOR_ZAPOSLENI, korisnik_id=int(korisnik.id), tekst=tekst,
                         datum_kreiranja=now)
            )
            p.status = STATUS_POSLATO
            p.dopuna_poslata = "D"
            p.procitano = "D"
            p.datum_izmene = now
            self.db.flush()
            view = self._detail(p)
            self.db.commit()
            return view
        except Exception:
            self.db.rollback()
            raise

    # ================================================================ prikaz
    @staticmethod
    def _clean(tekst: str) -> str:
        tekst = clean_text(tekst)
        if not tekst or len(tekst) > MAX_PITANJE:
            raise ValidationBusinessError("Napišite pitanje do 1000 znakova.")
        return tekst

    def _summary(self, p: HrPitanje, first: HrPoruka | None, names: dict[str, str]) -> dict:
        return {
            "id": int(p.id),
            "kategorija_sifra": p.kategorija_sifra,
            "kategorija_naziv": names.get(p.kategorija_sifra, p.kategorija_sifra),
            "pregled": preview(first.tekst if first else ""),
            "status": p.status,
            "nov_odgovor": p.procitano == "N",
            "datum_kreiranja": p.datum_kreiranja,
            "datum_izmene": p.datum_izmene,
        }

    def _detail(self, p: HrPitanje) -> dict:
        names = self.repo.category_names()
        return {
            "id": int(p.id),
            "kategorija_sifra": p.kategorija_sifra,
            "kategorija_naziv": names.get(p.kategorija_sifra, p.kategorija_sifra),
            "status": p.status,
            "mogu_dopuniti": p.status == STATUS_ODGOVORENO and p.dopuna_poslata != "D",
            "datum_kreiranja": p.datum_kreiranja,
            "poruke": [
                {"autor": m.autor, "tekst": m.tekst, "datum_kreiranja": m.datum_kreiranja}
                for m in self.repo.messages(int(p.id))
            ],
        }
