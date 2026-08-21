"""In-memory fake SystemEventRepository (bez prave Oracle baze) - koristi se za
servisne testove modula SISTEMSKA OBAVESTENJA. Ostali kolaboratori (NotificationRepo/
PushDeliveryRepo/TargetingRepo/ConfigService) se ponovo koriste iz notification_fakes.py."""

import datetime
import itertools
from types import SimpleNamespace

from app.models.sistemski_dogadjaj import DOGADJAJ_STATUS_PENDING, SistemskiDogadjaj

_ids = itertools.count(1)


def _next_id() -> int:
    return next(_ids)


class _FakeAnketa(SimpleNamespace):
    """Ogleda Anketa.is_available_to_employees (SCHEDULED/ACTIVE + unutar perioda)."""

    def is_available_to_employees(self, now: datetime.datetime) -> bool:
        return self.status in ("SCHEDULED", "ACTIVE") and self.datum_pocetka <= now <= self.datum_zavrsetka


class _FakeCiklus(SimpleNamespace):
    """Ogleda IdeaCiklus.is_submission_open (AKTIVAN + unutar perioda)."""

    def is_submission_open(self, now: datetime.datetime) -> bool:
        return self.status == "AKTIVAN" and self.datum_pocetka <= now <= self.datum_zavrsetka


def make_anketa(**ov) -> _FakeAnketa:
    # Sirok podrazumevan period (obuhvata sve fiksne "now" vrednosti koriscene u
    # testovima) - testovi koji ispituju istek/period eksplicitno prosledjuju svoje datume.
    defaults = dict(
        id=_next_id(),
        naziv="Anketa",
        status="ACTIVE",
        datum_pocetka=datetime.datetime(2020, 1, 1),
        datum_zavrsetka=datetime.datetime(2030, 1, 1),
    )
    defaults.update(ov)
    return _FakeAnketa(**defaults)


def make_ciklus(**ov) -> _FakeCiklus:
    defaults = dict(
        id=_next_id(),
        naziv="Ciklus",
        status="AKTIVAN",
        datum_pocetka=datetime.datetime(2020, 1, 1),
        datum_zavrsetka=datetime.datetime(2030, 1, 1),
    )
    defaults.update(ov)
    return _FakeCiklus(**defaults)


def make_ideja(**ov) -> SimpleNamespace:
    defaults = dict(id=_next_id(), korisnik_id=1, ciklus_id=1, naslov="Ideja", status="TOP_10")
    defaults.update(ov)
    return SimpleNamespace(**defaults)


class FakeSystemEventRepo:
    def __init__(self):
        self.events: dict[int, SistemskiDogadjaj] = {}
        self.keys: dict[str, int] = {}
        self.surveys: dict[int, SimpleNamespace] = {}
        self.cycles: dict[int, SimpleNamespace] = {}
        self.ideas: dict[int, SimpleNamespace] = {}
        # anketa_id -> [(korisnik_id, status), ...]
        self.survey_participants: dict[int, list[tuple[int, str]]] = {}
        # ciklus_id -> set(korisnik_id) koji imaju bar jednu ideju
        self.cycle_idea_authors: dict[int, set[int]] = {}
        self.enqueue_calls: list[str] = []

    # --- setup helpers ---
    def seed_survey(self, anketa: SimpleNamespace, participants: list[tuple[int, str]] | None = None):
        self.surveys[anketa.id] = anketa
        self.survey_participants[anketa.id] = list(participants or [])
        return anketa

    def seed_cycle(self, ciklus: SimpleNamespace, idea_authors: set[int] | None = None):
        self.cycles[ciklus.id] = ciklus
        self.cycle_idea_authors[ciklus.id] = set(idea_authors or set())
        return ciklus

    def seed_idea(self, ideja: SimpleNamespace):
        self.ideas[ideja.id] = ideja
        return ideja

    # --- enqueue ---
    def enqueue_if_absent(self, kljuc, tip, resurs_id, vrednost, now) -> bool:
        self.enqueue_calls.append(kljuc)
        if kljuc in self.keys:
            return False
        event = SistemskiDogadjaj(
            id=_next_id(),
            dogadjaj_kljuc=kljuc,
            tip_dogadjaja=tip,
            resurs_id=resurs_id,
            vrednost=vrednost,
            status=DOGADJAJ_STATUS_PENDING,
            broj_pokusaja=0,
            datum_sledeceg_pokusaja=now,
            poslednji_error_code=None,
            obavestenje_id=None,
            datum_kreiranja=now,
            datum_obrade=None,
        )
        self.events[event.id] = event
        self.keys[kljuc] = event.id
        return True

    # --- worker: claim ---
    def list_ready_ids(self, now, limit) -> list[int]:
        ready = [
            e for e in self.events.values()
            if e.status == DOGADJAJ_STATUS_PENDING
            and (e.datum_sledeceg_pokusaja is None or e.datum_sledeceg_pokusaja <= now)
        ]
        ready.sort(key=lambda e: (e.datum_sledeceg_pokusaja or now, e.id))
        return [e.id for e in ready[:limit]]

    def get_for_update(self, event_id):
        return self.events.get(event_id)

    # --- discovery ---
    def find_scheduled_surveys_now_active(self, now):
        return [
            a for a in self.surveys.values()
            if a.status == "SCHEDULED" and a.datum_pocetka <= now < a.datum_zavrsetka
        ]

    def find_surveys_expiring_within(self, now, window_end):
        return [
            a for a in self.surveys.values()
            if a.status in ("SCHEDULED", "ACTIVE")
            and a.datum_pocetka <= now < a.datum_zavrsetka <= window_end
        ]

    def find_cycles_expiring_within(self, now, window_end):
        return [
            c for c in self.cycles.values()
            if c.status == "AKTIVAN" and now < c.datum_zavrsetka <= window_end
        ]

    # --- resolucija resursa ---
    def get_survey(self, survey_id):
        return self.surveys.get(survey_id)

    def get_cycle(self, cycle_id):
        return self.cycles.get(cycle_id)

    def get_idea(self, idea_id):
        return self.ideas.get(idea_id)

    def survey_participant_ids(self, survey_id):
        return {uid for uid, _status in self.survey_participants.get(survey_id, [])}

    def survey_participant_ids_not_submitted(self, survey_id):
        return {
            uid for uid, status in self.survey_participants.get(survey_id, [])
            if status != "SUBMITTED"
        }

    def user_ids_with_idea_in_cycle(self, cycle_id):
        return set(self.cycle_idea_authors.get(cycle_id, set()))
