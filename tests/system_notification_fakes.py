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


def make_korisnik(**ov) -> SimpleNamespace:
    defaults = dict(id=_next_id(), status_zaposlenja="AKTIVAN", status_naloga="OMOGUCEN")
    defaults.update(ov)
    return SimpleNamespace(**defaults)


def make_ucesce(**ov) -> SimpleNamespace:
    defaults = dict(
        id=_next_id(),
        anketa_id=1,
        korisnik_id=1,
        status="NOT_STARTED",
        automatika_id=1,
        datum_dostupnosti=datetime.datetime(2020, 1, 1),
        datum_isteka=datetime.datetime(2030, 1, 1),
    )
    defaults.update(ov)
    return SimpleNamespace(**defaults)


class FakeOnboardingAssignmentService:
    """No-op po default - postojeci SystemNotificationService testovi ne ispituju
    onboarding dodelu i nemaju pravu (SQL-sposobnu) fake bazu iza sebe."""

    def __init__(self):
        self.calls = 0

    def assign_due_surveys(self, now):
        self.calls += 1
        return {"assigned": 0}


class FakeAutomationRepo:
    """Fake OnboardingAutomationRepository - koristi se u SystemNotificationService
    testovima da oznaci koje ankete imaju PULS_ANKETA_AUTOMATIKA red (automatske/
    onboarding ankete koje ne dobijaju globalni SURVEY_ACTIVATED/SURVEY_EXPIRING)."""

    def __init__(self):
        self.by_survey: dict[int, object] = {}

    def get_by_survey_id(self, anketa_id):
        return self.by_survey.get(anketa_id)

    def mark_automatska(self, anketa_id: int) -> None:
        self.by_survey[anketa_id] = object()


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
        self.ucesca: dict[int, SimpleNamespace] = {}
        self.korisnici: dict[int, SimpleNamespace] = {}

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

    def seed_ucesce(self, ucesce: SimpleNamespace):
        self.ucesca[ucesce.id] = ucesce
        return ucesce

    def seed_korisnik(self, korisnik: SimpleNamespace):
        self.korisnici[korisnik.id] = korisnik
        return korisnik

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

    def find_active_surveys_now_expired(self, now):
        return [
            a for a in self.surveys.values()
            if a.status == "ACTIVE" and a.datum_zavrsetka <= now
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

    def get_ucesce(self, ucesce_id):
        return self.ucesca.get(ucesce_id)

    def get_korisnik(self, korisnik_id):
        return self.korisnici.get(korisnik_id)

    def survey_participant_ids(self, survey_id):
        return {uid for uid, _status in self.survey_participants.get(survey_id, [])}

    def survey_participant_ids_not_submitted(self, survey_id):
        return {
            uid for uid, status in self.survey_participants.get(survey_id, [])
            if status != "SUBMITTED"
        }

    def user_ids_with_idea_in_cycle(self, cycle_id):
        return set(self.cycle_idea_authors.get(cycle_id, set()))
