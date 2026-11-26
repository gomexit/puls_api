"""PULS IZAZOV - zaposleni (Bearer).

- Kviz vidi zaposleni kome je modul KVIZ ukljucen i koga pogadja ciljanje
  (bez ciljeva = svi). Nevidljiv kviz daje isti 404 kao nepostojeci.
- Jedan pokusaj po kvizu. Vreme meri server: rok = DATUM_POCETKA + TRAJANJE_SEKUNDI
  (+ GRACE_SECONDS za mreznu latenciju). Posle roka pokusaj se zavrsava (lenjo, pri
  sledecem pozivu), a neodgovorena pitanja se racunaju kao netacna.
- Tacan odgovor i objasnjenje se nikad ne salju pre nego sto zaposleni odgovori.
- Prosek org. jedinice se prikazuje tek od MIN_POKUSAJA_ZA_PROSEK zavrsenih pokusaja."""

import datetime
from collections.abc import Callable

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import (
    InvalidQuizAnswerError,
    QuizAlreadyPlayedError,
    QuizAttemptFinishedError,
    QuizAttemptInProgressError,
    QuizAttemptNotFoundError,
    QuizNotFoundError,
    QuizQuestionAlreadyAnsweredError,
    QuizTimeExpiredError,
)
from app.models.korisnik import Korisnik
from app.models.kviz import (
    KVIZ_CILJ_ORGJED,
    KVIZ_CILJ_PLATNI_BROJ,
    KVIZ_STATUS_ARHIVIRAN,
    POKUSAJ_U_TOKU,
    POKUSAJ_ZAVRSEN,
    Kviz,
    KvizOdgovor,
    KvizPokusaj,
)
from app.repositories.configuration_repository import ConfigurationRepository
from app.repositories.module_access_repository import ModuleAccessRepository
from app.repositories.quiz_repository import QuizRepository
from app.services.module_access_service import ModuleAccessService
from app.services.quiz_admin_service import MIN_POKUSAJA_ZA_PROSEK

MODULE_CODE = "KVIZ"
GRACE_SECONDS = 5
IMAGE_URL_PREFIX = "/api/v1/images"


def _image_url(slika_id) -> str | None:
    return f"{IMAGE_URL_PREFIX}/{int(slika_id)}" if slika_id is not None else None


class QuizService:
    def __init__(
        self,
        db: Session,
        repository: QuizRepository | None = None,
        module_access: ModuleAccessService | None = None,
        access_repository: ModuleAccessRepository | None = None,
        now_fn: Callable[[], datetime.datetime] | None = None,
    ):
        self.db = db
        self.repo = repository or QuizRepository(db)
        self.access_repo = access_repository or ModuleAccessRepository(db)
        self.module_access = module_access or ModuleAccessService(ConfigurationRepository(db), self.access_repo)
        self._now_fn = now_fn or datetime.datetime.now

    # ================================================================ vidljivost
    def _visible(self, korisnik: Korisnik, kviz: Kviz, orgjed: frozenset[str] | None = None) -> bool:
        ciljevi = self.repo.get_targets(int(kviz.id))
        if not ciljevi:
            return True
        if orgjed is None:
            orgjed = self.access_repo.active_orgjed_codes(int(korisnik.id))
        for c in ciljevi:
            if c.tip_cilja == KVIZ_CILJ_PLATNI_BROJ and c.vrednost == korisnik.platni_broj:
                return True
            if c.tip_cilja == KVIZ_CILJ_ORGJED and c.vrednost in orgjed:
                return True
        return False

    def _current_quiz(self, korisnik: Korisnik, now: datetime.datetime) -> Kviz | None:
        if not self.module_access.is_enabled(korisnik, MODULE_CODE):
            return None
        open_quizzes = self.repo.find_open_published(now)
        if not open_quizzes:
            return None
        orgjed = self.access_repo.active_orgjed_codes(int(korisnik.id))
        for kviz in open_quizzes:
            if self._visible(korisnik, kviz, orgjed):
                return kviz
        return None

    def _visible_quiz_or_404(self, korisnik: Korisnik, kviz_id: int) -> Kviz:
        kviz = self.repo.get(kviz_id)
        if kviz is None or kviz.status == KVIZ_STATUS_ARHIVIRAN:
            raise QuizNotFoundError()
        if not self.module_access.is_enabled(korisnik, MODULE_CODE) or not self._visible(korisnik, kviz):
            raise QuizNotFoundError()
        return kviz

    # ================================================================== vreme
    @staticmethod
    def _deadline(p: KvizPokusaj, kviz: Kviz) -> datetime.datetime:
        return p.datum_pocetka + datetime.timedelta(seconds=int(kviz.trajanje_sekundi))

    def _expired(self, p: KvizPokusaj, kviz: Kviz, now: datetime.datetime) -> bool:
        return now > self._deadline(p, kviz) + datetime.timedelta(seconds=GRACE_SECONDS)

    def _finalize(self, p: KvizPokusaj, kviz: Kviz, now: datetime.datetime) -> None:
        rok = self._deadline(p, kviz)
        kraj = min(now, rok)
        p.status = POKUSAJ_ZAVRSEN
        p.datum_zavrsetka = kraj
        p.trajanje_ms = max(0, int((kraj - p.datum_pocetka).total_seconds() * 1000))

    # ================================================================ pocetni
    def current(self, korisnik: Korisnik) -> dict:
        """Trenutni kviz i stanje mog pokusaja. Bez upisa u bazu."""
        now = self._now_fn()
        kviz = self._current_quiz(korisnik, now)
        if kviz is None:
            return {"kviz": None, "pokusaj": None}
        broj_pitanja = len(self.repo.get_questions(int(kviz.id)))
        pokusaj = self.repo.get_attempt(int(kviz.id), int(korisnik.id))
        pokusaj_view = None
        if pokusaj is not None:
            status = pokusaj.status
            if status == POKUSAJ_U_TOKU and self._expired(pokusaj, kviz, now):
                status = POKUSAJ_ZAVRSEN
            pokusaj_view = {"id": int(pokusaj.id), "status": status, "broj_tacnih": int(pokusaj.broj_tacnih)}
        return {
            "kviz": {
                "id": int(kviz.id),
                "naziv": kviz.naziv,
                "opis": kviz.opis,
                "datum_od": kviz.datum_od,
                "datum_do": kviz.datum_do,
                "trajanje_sekundi": int(kviz.trajanje_sekundi),
                "broj_pitanja": broj_pitanja,
            },
            "pokusaj": pokusaj_view,
        }

    def badge_count(self, korisnik: Korisnik) -> int:
        """1 ako postoji aktivan kviz koji zaposleni jos nije zavrsio (za "Moj kutak")."""
        state = self.current(korisnik)
        if state["kviz"] is None:
            return 0
        pokusaj = state["pokusaj"]
        return 0 if pokusaj is not None and pokusaj["status"] == POKUSAJ_ZAVRSEN else 1

    # ================================================================== start
    def start(self, korisnik: Korisnik, kviz_id: int) -> dict:
        try:
            view = self._start(korisnik, kviz_id)
        except IntegrityError:
            # Konkurentan start istog korisnika (UQ KVIZ_ID, KORISNIK_ID): procitaj postojeci.
            self.db.rollback()
            view = self._start(korisnik, kviz_id)
        return view

    def _start(self, korisnik: Korisnik, kviz_id: int) -> dict:
        try:
            now = self._now_fn()
            kviz = self._visible_quiz_or_404(korisnik, kviz_id)
            pokusaj = self.repo.get_attempt_for_update(int(kviz.id), int(korisnik.id))
            if pokusaj is not None:
                if pokusaj.status == POKUSAJ_U_TOKU and self._expired(pokusaj, kviz, now):
                    self._finalize(pokusaj, kviz, now)
                    self.db.commit()
                    raise QuizAlreadyPlayedError()
                if pokusaj.status == POKUSAJ_ZAVRSEN:
                    raise QuizAlreadyPlayedError()
            else:
                if not kviz.is_open(now):
                    raise QuizNotFoundError()
                if not self.repo.get_questions(int(kviz.id)):
                    raise QuizNotFoundError()
                pokusaj = KvizPokusaj(
                    kviz_id=int(kviz.id),
                    korisnik_id=int(korisnik.id),
                    orgjed_sifra=self.repo.primary_orgjed(int(korisnik.id)),
                    status=POKUSAJ_U_TOKU,
                    datum_pocetka=now,
                    datum_zavrsetka=None,
                    broj_tacnih=0,
                    trajanje_ms=None,
                )
                self.repo.add_attempt(pokusaj)
                self.db.flush()
            view = self._play_view(pokusaj, kviz, now)
            self.db.commit()
            return view
        except IntegrityError:
            raise
        except Exception:
            self.db.rollback()
            raise

    # ================================================================ odgovor
    def answer(self, korisnik: Korisnik, pokusaj_id: int, pitanje_id: int, opcija_id: int) -> dict:
        try:
            now = self._now_fn()
            pokusaj, kviz = self._own_attempt(korisnik, pokusaj_id)
            if pokusaj.status == POKUSAJ_ZAVRSEN:
                raise QuizAttemptFinishedError()
            if self._expired(pokusaj, kviz, now):
                # Zavrsetak se cuva (commit), pa tek onda greska - rollback posle commit-a je no-op.
                self._finalize(pokusaj, kviz, now)
                self.db.commit()
                raise QuizTimeExpiredError()
            view = self._record_answer(pokusaj, kviz, pitanje_id, opcija_id, now)
            self.db.commit()
            return view
        except Exception:
            self.db.rollback()
            raise

    def _record_answer(self, pokusaj: KvizPokusaj, kviz: Kviz, pitanje_id: int, opcija_id: int, now) -> dict:
        pitanja = self.repo.get_questions(int(kviz.id))
        pitanje = next((p for p in pitanja if int(p.id) == pitanje_id), None)
        if pitanje is None:
            raise InvalidQuizAnswerError()
        opcije = self.repo.get_options([int(pitanje.id)])
        izabrana = next((o for o in opcije if int(o.id) == opcija_id), None)
        if izabrana is None:
            raise InvalidQuizAnswerError()
        odgovori = self.repo.get_answers(int(pokusaj.id))
        if any(int(o.pitanje_id) == pitanje_id for o in odgovori):
            raise QuizQuestionAlreadyAnsweredError()
        tacna = next(o for o in opcije if o.tacna == "D")
        tacan = izabrana.tacna == "D"
        self.repo.add_answer(
            KvizOdgovor(
                pokusaj_id=int(pokusaj.id),
                pitanje_id=pitanje_id,
                opcija_id=opcija_id,
                tacan="D" if tacan else "N",
                datum_odgovora=now,
            )
        )
        if tacan:
            pokusaj.broj_tacnih = int(pokusaj.broj_tacnih) + 1
        broj_odgovorenih = len(odgovori) + 1
        zavrsen = broj_odgovorenih >= len(pitanja)
        if zavrsen:
            self._finalize(pokusaj, kviz, now)
        self.db.flush()
        return {
            "pitanje_id": pitanje_id,
            "opcija_id": opcija_id,
            "tacan": tacan,
            "tacna_opcija_id": int(tacna.id),
            "objasnjenje": pitanje.objasnjenje,
            "broj_tacnih": int(pokusaj.broj_tacnih),
            "broj_odgovorenih": broj_odgovorenih,
            "broj_pitanja": len(pitanja),
            "zavrsen": zavrsen,
        }

    # =============================================================== rezultat
    def finish(self, korisnik: Korisnik, pokusaj_id: int) -> dict:
        """Zaposleni zavrsava ranije (ili aplikacija posle isteka vremena). Idempotentno."""
        try:
            now = self._now_fn()
            pokusaj, kviz = self._own_attempt(korisnik, pokusaj_id)
            if pokusaj.status == POKUSAJ_U_TOKU:
                self._finalize(pokusaj, kviz, now)
                self.db.flush()
            view = self._result_view(pokusaj, kviz)
            self.db.commit()
            return view
        except Exception:
            self.db.rollback()
            raise

    def result(self, korisnik: Korisnik, pokusaj_id: int) -> dict:
        try:
            now = self._now_fn()
            pokusaj, kviz = self._own_attempt(korisnik, pokusaj_id)
            if pokusaj.status == POKUSAJ_U_TOKU:
                if not self._expired(pokusaj, kviz, now):
                    raise QuizAttemptInProgressError()
                self._finalize(pokusaj, kviz, now)
                self.db.flush()
            view = self._result_view(pokusaj, kviz)
            self.db.commit()
            return view
        except Exception:
            self.db.rollback()
            raise

    # ================================================================ helpers
    def _own_attempt(self, korisnik: Korisnik, pokusaj_id: int) -> tuple[KvizPokusaj, Kviz]:
        pokusaj = self.repo.get_attempt_by_id_for_update(pokusaj_id)
        if pokusaj is None or int(pokusaj.korisnik_id) != int(korisnik.id):
            raise QuizAttemptNotFoundError()
        kviz = self.repo.get(int(pokusaj.kviz_id))
        if kviz is None:
            raise QuizAttemptNotFoundError()
        return pokusaj, kviz

    def _questions_with_options(self, kviz: Kviz):
        pitanja = self.repo.get_questions(int(kviz.id))
        opcije = self.repo.get_options(int(p.id) for p in pitanja)
        by_q: dict[int, list] = {}
        for o in opcije:
            by_q.setdefault(int(o.pitanje_id), []).append(o)
        for lst in by_q.values():
            lst.sort(key=lambda o: int(o.redosled))
        names = self.repo.category_names(p.kategorija_sifra for p in pitanja)
        return pitanja, by_q, names

    def _play_view(self, pokusaj: KvizPokusaj, kviz: Kviz, now: datetime.datetime) -> dict:
        pitanja, by_q, names = self._questions_with_options(kviz)
        odgovori = {int(o.pitanje_id): o for o in self.repo.get_answers(int(pokusaj.id))}
        rok = self._deadline(pokusaj, kviz)
        items = []
        for p in pitanja:
            opcije = by_q.get(int(p.id), [])
            odg = odgovori.get(int(p.id))
            odgovor_view = None
            if odg is not None:  # vec odgovoreno: sme da se pokaze tacan odgovor
                tacna = next((o for o in opcije if o.tacna == "D"), None)
                odgovor_view = {
                    "opcija_id": int(odg.opcija_id),
                    "tacan": odg.tacan == "D",
                    "tacna_opcija_id": int(tacna.id) if tacna is not None else None,
                    "objasnjenje": p.objasnjenje,
                }
            items.append(
                {
                    "id": int(p.id),
                    "redosled": int(p.redosled),
                    "tekst": p.tekst,
                    "kategorija": names.get(p.kategorija_sifra, p.kategorija_sifra),
                    "slika_url": _image_url(p.slika_id),
                    # Bez oznake tacnosti!
                    "opcije": [{"id": int(o.id), "tekst": o.tekst} for o in opcije],
                    "odgovor": odgovor_view,
                }
            )
        return {
            "pokusaj_id": int(pokusaj.id),
            "kviz_id": int(kviz.id),
            "naziv": kviz.naziv,
            "status": pokusaj.status,
            "trajanje_sekundi": int(kviz.trajanje_sekundi),
            "datum_pocetka": pokusaj.datum_pocetka,
            "rok": rok,
            "preostalo_sekundi": max(0, int((rok - now).total_seconds())),
            "broj_pitanja": len(pitanja),
            "broj_tacnih": int(pokusaj.broj_tacnih),
            "pitanja": items,
        }

    def _result_view(self, pokusaj: KvizPokusaj, kviz: Kviz) -> dict:
        pitanja, by_q, names = self._questions_with_options(kviz)
        odgovori = {int(o.pitanje_id): o for o in self.repo.get_answers(int(pokusaj.id))}
        prosek = None
        broj_ucesnika = None
        if pokusaj.orgjed_sifra:
            count, avg = self.repo.orgjed_average(int(kviz.id), pokusaj.orgjed_sifra)
            if count >= MIN_POKUSAJA_ZA_PROSEK and avg is not None:
                prosek = round(avg, 1)
                broj_ucesnika = count
        return {
            "pokusaj_id": int(pokusaj.id),
            "kviz_id": int(kviz.id),
            "naziv": kviz.naziv,
            "status": pokusaj.status,
            "broj_tacnih": int(pokusaj.broj_tacnih),
            "broj_pitanja": len(pitanja),
            "trajanje_ms": int(pokusaj.trajanje_ms) if pokusaj.trajanje_ms is not None else None,
            "datum_pocetka": pokusaj.datum_pocetka,
            "datum_zavrsetka": pokusaj.datum_zavrsetka,
            "prosek_orgjed": prosek,
            "broj_ucesnika_orgjed": broj_ucesnika,
            "pitanja": [
                {
                    "id": int(p.id),
                    "redosled": int(p.redosled),
                    "tekst": p.tekst,
                    "kategorija": names.get(p.kategorija_sifra, p.kategorija_sifra),
                    "slika_url": _image_url(p.slika_id),
                    "opcije": [
                        {"id": int(o.id), "tekst": o.tekst, "tacna": o.tacna == "D"}
                        for o in by_q.get(int(p.id), [])
                    ],
                    "moja_opcija_id": int(odgovori[int(p.id)].opcija_id) if int(p.id) in odgovori else None,
                    "tacan": odgovori[int(p.id)].tacan == "D" if int(p.id) in odgovori else False,
                    "objasnjenje": p.objasnjenje,
                }
                for p in pitanja
            ],
        }
