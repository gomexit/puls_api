"""GOMEX PUTANJA - zaposleni (Bearer).

- Igru vidi zaposleni kome je modul IGRA ukljucen; inace 404 GAME_NOT_AVAILABLE.
- Jedan nivo dnevno, isti za sve. Nivo pravi server sam (game_generator) pri prvom
  pokretanju tog dana; isti datum uvek daje isti nivo.
- Igra se koliko god puta; racuna se PRVO ispravno resenje. Vreme meri server: od
  poslednjeg pokretanja pre resenja do prijema resenja. Resenje proverava server.
- Rezultat: moje vreme, prosek moje prodavnice (od MIN_RESENJA_ZA_PROSEK resenja) i
  niz dana zaredom. Nema rang liste sa imenima."""

import datetime
import json
from collections.abc import Callable

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import (
    GameInvalidPathError,
    GameLevelExpiredError,
    GameNotAvailableError,
    GameNotStartedError,
)
from app.models.igra import REZULTAT_RESEN, REZULTAT_U_TOKU, IgraNivo, IgraRezultat
from app.models.korisnik import Korisnik
from app.repositories.configuration_repository import ConfigurationRepository
from app.repositories.game_repository import GameRepository
from app.repositories.module_access_repository import ModuleAccessRepository
from app.services import game_generator
from app.services.module_access_service import ModuleAccessService

MODULE_CODE = "IGRA"
MIN_RESENJA_ZA_PROSEK = 3
NIZ_MAX_DANA = 366

STATUS_NIJE_POCETO = "NIJE_POCETO"
STATUS_U_TOKU = "U_TOKU"
STATUS_RESENO = "RESENO"


class GameService:
    def __init__(
        self,
        db: Session,
        repository: GameRepository | None = None,
        module_access: ModuleAccessService | None = None,
        now_fn: Callable[[], datetime.datetime] | None = None,
    ):
        self.db = db
        self.repo = repository or GameRepository(db)
        self.module_access = module_access or ModuleAccessService(
            ConfigurationRepository(db), ModuleAccessRepository(db)
        )
        self._now_fn = now_fn or datetime.datetime.now

    def _require_module(self, korisnik: Korisnik) -> None:
        if not self.module_access.is_enabled(korisnik, MODULE_CODE):
            raise GameNotAvailableError()

    # ================================================================ pregled
    def daily(self, korisnik: Korisnik) -> dict:
        """Stanje danasnjeg nivoa za mene. Bez upisa u bazu."""
        self._require_module(korisnik)
        today = self._now_fn().date()
        nivo = self.repo.get_level(today)
        rezultat = self.repo.get_result(int(nivo.id), int(korisnik.id)) if nivo is not None else None
        return self._summary(korisnik, today, nivo, rezultat)

    def badge_count(self, korisnik: Korisnik) -> int:
        """1 dok danasnji nivo nije resen (za "Moj kutak")."""
        today = self._now_fn().date()
        nivo = self.repo.get_level(today)
        if nivo is None:
            return 1
        rezultat = self.repo.get_result(int(nivo.id), int(korisnik.id))
        return 0 if rezultat is not None and rezultat.status == REZULTAT_RESEN else 1

    def _summary(self, korisnik: Korisnik, today: datetime.date, nivo, rezultat) -> dict:
        velicina, broj_tacaka, _ = game_generator.difficulty(today)
        if rezultat is None:
            status = STATUS_NIJE_POCETO
        elif rezultat.status == REZULTAT_RESEN:
            status = STATUS_RESENO
        else:
            status = STATUS_U_TOKU
        prosek, broj_resenih = None, None
        if nivo is not None and rezultat is not None and rezultat.orgjed_sifra:
            count, avg = self.repo.orgjed_average(int(nivo.id), rezultat.orgjed_sifra)
            broj_resenih = count
            if count >= MIN_RESENJA_ZA_PROSEK and avg is not None:
                prosek = round(avg)
        return {
            "datum": today,
            "velicina": velicina,
            "broj_tacaka": broj_tacaka,
            "status": status,
            "moje_vreme_ms": int(rezultat.trajanje_ms) if status == STATUS_RESENO else None,
            "niz_dana": self._streak(int(korisnik.id), today),
            "prosek_orgjed_ms": prosek,
            "broj_resenih_orgjed": broj_resenih,
        }

    def _streak(self, korisnik_id: int, today: datetime.date) -> int:
        dani = self.repo.solved_dates(korisnik_id, today - datetime.timedelta(days=NIZ_MAX_DANA))
        dan = today if today in dani else today - datetime.timedelta(days=1)
        niz = 0
        while dan in dani:
            niz += 1
            dan -= datetime.timedelta(days=1)
        return niz

    # ================================================================== start
    def _level_for(self, datum: datetime.date, now: datetime.datetime) -> IgraNivo:
        nivo = self.repo.get_level(datum)
        if nivo is not None:
            return nivo
        podaci, resenje = game_generator.generate(datum)
        return self.repo.add_level(
            IgraNivo(
                datum=datum,
                velicina=podaci["velicina"],
                podaci=json.dumps(podaci, separators=(",", ":")),
                resenje=json.dumps([list(c) for c in resenje], separators=(",", ":")),
                datum_kreiranja=now,
            )
        )

    def start(self, korisnik: Korisnik) -> dict:
        self._require_module(korisnik)
        try:
            return self._start(korisnik)
        except IntegrityError:
            # Konkurentno pravljenje nivoa ili prvog reda za korisnika: procitaj postojeci.
            self.db.rollback()
            return self._start(korisnik)

    def _start(self, korisnik: Korisnik) -> dict:
        try:
            now = self._now_fn()
            today = now.date()
            nivo = self._level_for(today, now)
            rezultat = self.repo.get_result_for_update(int(nivo.id), int(korisnik.id))
            if rezultat is None:
                rezultat = self.repo.add_result(
                    IgraRezultat(
                        nivo_id=int(nivo.id),
                        korisnik_id=int(korisnik.id),
                        orgjed_sifra=self.repo.primary_orgjed(int(korisnik.id)),
                        status=REZULTAT_U_TOKU,
                        datum_pocetka=now,
                        datum_resenja=None,
                        trajanje_ms=None,
                        broj_pokretanja=1,
                    )
                )
            elif rezultat.status == REZULTAT_U_TOKU:
                # Nova partija pre resenja: sat krece ispocetka.
                rezultat.datum_pocetka = now
                rezultat.broj_pokretanja = int(rezultat.broj_pokretanja) + 1
            podaci = json.loads(nivo.podaci)
            view = {
                "datum": today,
                "velicina": int(podaci["velicina"]),
                "tacke": podaci["tacke"],
                "zidovi": podaci["zidovi"],
                "status": STATUS_RESENO if rezultat.status == REZULTAT_RESEN else STATUS_U_TOKU,
            }
            self.db.commit()
            return view
        except IntegrityError:
            raise
        except Exception:
            self.db.rollback()
            raise

    # ================================================================ resenje
    def submit(self, korisnik: Korisnik, datum: datetime.date, putanja: list) -> dict:
        self._require_module(korisnik)
        try:
            now = self._now_fn()
            today = now.date()
            if datum != today:
                raise GameLevelExpiredError()
            nivo = self.repo.get_level(today)
            rezultat = self.repo.get_result_for_update(int(nivo.id), int(korisnik.id)) if nivo else None
            if nivo is None or rezultat is None:
                raise GameNotStartedError()
            if not game_generator.is_valid_solution(json.loads(nivo.podaci), putanja):
                raise GameInvalidPathError()
            prvo = rezultat.status == REZULTAT_U_TOKU
            if prvo:
                rezultat.status = REZULTAT_RESEN
                rezultat.datum_resenja = now
                rezultat.trajanje_ms = max(0, int((now - rezultat.datum_pocetka).total_seconds() * 1000))
                self.db.flush()
            view = self._summary(korisnik, today, nivo, rezultat)
            view["prvo_resenje"] = prvo
            self.db.commit()
            return view
        except Exception:
            self.db.rollback()
            raise
