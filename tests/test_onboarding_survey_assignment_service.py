"""Servisni testovi za OnboardingSurveyAssignmentService (fake repozitorijumi, bez DB)."""

import datetime
import itertools
from types import SimpleNamespace

import pytest

from app.models.anketa_ucesce import AnketaUcesce
from app.services.onboarding_survey_assignment_service import OnboardingSurveyAssignmentService

_ids = itertools.count(1000)


def _next_id() -> int:
    return next(_ids)


def make_pravilo(**ov) -> SimpleNamespace:
    defaults = dict(
        id=1,
        anketa_id=10,
        dani_od_zaposlenja=7,
        rok_dana=7,
        datum_primene_od=datetime.date(2026, 1, 1),
        aktivna="D",
    )
    defaults.update(ov)
    return SimpleNamespace(**defaults)


def make_anketa(**ov) -> SimpleNamespace:
    defaults = dict(id=10, naziv="Onboarding anketa", status="ACTIVE", anonimna="N")
    defaults.update(ov)
    return SimpleNamespace(**defaults)


def make_korisnik(**ov) -> SimpleNamespace:
    defaults = dict(
        id=_next_id(),
        status_zaposlenja="AKTIVAN",
        status_naloga="OMOGUCEN",
        zakljucan="N",
        datum_zaposlenja=datetime.date(2026, 1, 1),
    )
    defaults.update(ov)
    return SimpleNamespace(**defaults)


class FakeAutomationRepo:
    """Fake koji stvarno primenjuje pravilo (milestone prozor/DATUM_PRIMENE_OD) nad
    listom seed-ovanih korisnika, umesto da SQL upit radi to posao."""

    def __init__(self):
        self.rules: list[SimpleNamespace] = []
        self.users: list[SimpleNamespace] = []
        self.participations: set[tuple[int, int]] = set()  # (anketa_id, korisnik_id)

    def seed_rule(self, pravilo):
        self.rules.append(pravilo)
        return pravilo

    def seed_user(self, korisnik):
        self.users.append(korisnik)
        return korisnik

    def seed_participation(self, anketa_id, korisnik_id):
        self.participations.add((anketa_id, korisnik_id))

    def find_active_rules(self):
        return [r for r in self.rules if r.aktivna == "D"]

    def find_qualified_candidates(self, pravilo, now):
        # Simulira NOT EXISTS na PULS_ANKETA_UCESCA - kandidat sa postojecim ucescem
        # se ne vraca (isto ponasanje kao stvarni korelisani upit u repou).
        today = now.date()
        out = []
        for u in self.users:
            if (pravilo.anketa_id, u.id) in self.participations:
                continue
            if u.status_zaposlenja != "AKTIVAN" or u.status_naloga != "OMOGUCEN":
                continue
            if u.datum_zaposlenja is None or u.datum_zaposlenja < pravilo.datum_primene_od:
                continue
            dostupnost = u.datum_zaposlenja + datetime.timedelta(days=int(pravilo.dani_od_zaposlenja))
            istek = dostupnost + datetime.timedelta(days=int(pravilo.rok_dana))
            if dostupnost <= today < istek:
                out.append(u)
        return out

    def existing_participation_exists(self, anketa_id, korisnik_id):
        return (anketa_id, korisnik_id) in self.participations


class FakeSurveyRepo:
    def __init__(self):
        self.surveys: dict[int, SimpleNamespace] = {}
        self.ucesca: list[AnketaUcesce] = []

    def seed_survey(self, anketa):
        self.surveys[anketa.id] = anketa
        return anketa

    def get_survey(self, anketa_id):
        return self.surveys.get(anketa_id)

    def add_ucesce(self, ucesce):
        ucesce.id = _next_id()
        self.ucesca.append(ucesce)
        return ucesce


class FakeEventRepo:
    def __init__(self):
        self.keys: set[str] = set()
        self.events: list[dict] = []
        self.fail_on_key: str | None = None

    def enqueue_if_absent(self, kljuc, tip, resurs_id, vrednost, now):
        if self.fail_on_key is not None and kljuc == self.fail_on_key:
            raise RuntimeError("simulated failure")
        if kljuc in self.keys:
            return False
        self.keys.add(kljuc)
        self.events.append(
            {"kljuc": kljuc, "tip": tip, "resurs_id": resurs_id, "vrednost": vrednost}
        )
        return True


def _service():
    automation = FakeAutomationRepo()
    survey = FakeSurveyRepo()
    event = FakeEventRepo()
    service = OnboardingSurveyAssignmentService(
        db=None, automation_repository=automation, survey_repository=survey, event_repository=event
    )
    return service, automation, survey, event


NOW = datetime.datetime(2026, 6, 1, 10, 0, 0)  # 2026-06-01


# ============================================================= milestone granice
@pytest.mark.parametrize(
    "dani_zaposlenja_pre,ocekivano",
    [(6, False), (7, True)],
)
def test_milestone_7_boundary(dani_zaposlenja_pre, ocekivano):
    service, automation, survey, event = _service()
    survey.seed_survey(make_anketa())
    automation.seed_rule(make_pravilo(dani_od_zaposlenja=7, rok_dana=7))
    datum_zaposlenja = (NOW - datetime.timedelta(days=dani_zaposlenja_pre)).date()
    automation.seed_user(make_korisnik(datum_zaposlenja=datum_zaposlenja))

    result = service.assign_due_surveys(NOW)
    assert (result["assigned"] == 1) is ocekivano
    assert (len(survey.ucesca) == 1) is ocekivano


@pytest.mark.parametrize("dani_pre,ocekivano", [(29, False), (30, True)])
def test_milestone_30_boundary(dani_pre, ocekivano):
    service, automation, survey, event = _service()
    survey.seed_survey(make_anketa())
    automation.seed_rule(make_pravilo(dani_od_zaposlenja=30, rok_dana=7))
    automation.seed_user(make_korisnik(datum_zaposlenja=(NOW - datetime.timedelta(days=dani_pre)).date()))
    result = service.assign_due_surveys(NOW)
    assert (result["assigned"] == 1) is ocekivano


@pytest.mark.parametrize("dani_pre,ocekivano", [(59, False), (60, True)])
def test_milestone_60_boundary(dani_pre, ocekivano):
    service, automation, survey, event = _service()
    survey.seed_survey(make_anketa())
    automation.seed_rule(make_pravilo(dani_od_zaposlenja=60, rok_dana=7))
    automation.seed_user(make_korisnik(datum_zaposlenja=(NOW - datetime.timedelta(days=dani_pre)).date()))
    result = service.assign_due_surveys(NOW)
    assert (result["assigned"] == 1) is ocekivano


@pytest.mark.parametrize("dani_pre,ocekivano", [(89, False), (90, True)])
def test_milestone_90_boundary(dani_pre, ocekivano):
    service, automation, survey, event = _service()
    survey.seed_survey(make_anketa())
    automation.seed_rule(make_pravilo(dani_od_zaposlenja=90, rok_dana=7))
    automation.seed_user(make_korisnik(datum_zaposlenja=(NOW - datetime.timedelta(days=dani_pre)).date()))
    result = service.assign_due_surveys(NOW)
    assert (result["assigned"] == 1) is ocekivano


# ================================================================= rok (7 dana) istek
def test_window_still_open_on_day_7_of_availability():
    """Dan 7 od DATUM_DOSTUPNOSTI (rok_dana=7) je JOS dostupan - [dostupnost, dostupnost+7)."""
    service, automation, survey, event = _service()
    survey.seed_survey(make_anketa())
    automation.seed_rule(make_pravilo(dani_od_zaposlenja=7, rok_dana=7))
    # DATUM_ZAPOSLENJA je 13 dana pre NOW -> dostupnost je 6 dana pre NOW -> tacno 7. dan prozora
    # (dostupnost = dan 1, ..., dostupnost+6 = dan 7 - jos u [dostupnost, dostupnost+7)).
    automation.seed_user(make_korisnik(datum_zaposlenja=(NOW - datetime.timedelta(days=13)).date()))
    result = service.assign_due_surveys(NOW)
    assert result["assigned"] == 1


def test_window_closed_on_day_8_of_availability():
    service, automation, survey, event = _service()
    survey.seed_survey(make_anketa())
    automation.seed_rule(make_pravilo(dani_od_zaposlenja=7, rok_dana=7))
    # dostupnost = 7 dana pre NOW -> danas je dan 8 (dostupnost+7) - VAN prozora.
    automation.seed_user(make_korisnik(datum_zaposlenja=(NOW - datetime.timedelta(days=14)).date()))
    result = service.assign_due_surveys(NOW)
    assert result["assigned"] == 0


# ================================================================= DATUM_PRIMENE_OD
def test_datum_primene_od_excludes_earlier_hires():
    service, automation, survey, event = _service()
    survey.seed_survey(make_anketa())
    automation.seed_rule(
        make_pravilo(dani_od_zaposlenja=7, rok_dana=7, datum_primene_od=datetime.date(2026, 5, 20))
    )
    # Zaposlen tacno na granici milestone-a, ali PRE DATUM_PRIMENE_OD.
    automation.seed_user(make_korisnik(datum_zaposlenja=datetime.date(2026, 5, 19)))
    result = service.assign_due_surveys(NOW)
    assert result["assigned"] == 0


def test_datum_primene_od_includes_hire_on_boundary():
    service, automation, survey, event = _service()
    survey.seed_survey(make_anketa())
    automation.seed_rule(
        make_pravilo(dani_od_zaposlenja=7, rok_dana=7, datum_primene_od=datetime.date(2026, 5, 25))
    )
    automation.seed_user(make_korisnik(datum_zaposlenja=datetime.date(2026, 5, 25)))
    result = service.assign_due_surveys(NOW)
    assert result["assigned"] == 1


# ================================================================= status filteri
def test_inactive_employment_status_excluded():
    service, automation, survey, event = _service()
    survey.seed_survey(make_anketa())
    automation.seed_rule(make_pravilo(dani_od_zaposlenja=7, rok_dana=7))
    automation.seed_user(
        make_korisnik(
            status_zaposlenja="NEAKTIVAN", datum_zaposlenja=(NOW - datetime.timedelta(days=7)).date()
        )
    )
    result = service.assign_due_surveys(NOW)
    assert result["assigned"] == 0


def test_disabled_account_excluded():
    service, automation, survey, event = _service()
    survey.seed_survey(make_anketa())
    automation.seed_rule(make_pravilo(dani_od_zaposlenja=7, rok_dana=7))
    automation.seed_user(
        make_korisnik(
            status_naloga="ONEMOGUCEN", datum_zaposlenja=(NOW - datetime.timedelta(days=7)).date()
        )
    )
    result = service.assign_due_surveys(NOW)
    assert result["assigned"] == 0


def test_locked_user_is_still_assigned():
    """ZAKLJUCAN nije deo filtera dodele - samo STATUS_ZAPOSLENJA/STATUS_NALOGA."""
    service, automation, survey, event = _service()
    survey.seed_survey(make_anketa())
    automation.seed_rule(make_pravilo(dani_od_zaposlenja=7, rok_dana=7))
    automation.seed_user(
        make_korisnik(zakljucan="D", datum_zaposlenja=(NOW - datetime.timedelta(days=7)).date())
    )
    result = service.assign_due_surveys(NOW)
    assert result["assigned"] == 1


def test_missed_entire_window_when_worker_delayed_not_assigned():
    """Worker kasnio preko roka - ceo prozor propusten, ne dodeljuje se naknadno."""
    service, automation, survey, event = _service()
    survey.seed_survey(make_anketa())
    automation.seed_rule(make_pravilo(dani_od_zaposlenja=7, rok_dana=7))
    automation.seed_user(make_korisnik(datum_zaposlenja=(NOW - datetime.timedelta(days=100)).date()))
    result = service.assign_due_surveys(NOW)
    assert result["assigned"] == 0


# ================================================================= idempotentnost
def test_duplicate_run_does_not_duplicate_participation_or_event():
    service, automation, survey, event = _service()
    survey.seed_survey(make_anketa())
    automation.seed_rule(make_pravilo(dani_od_zaposlenja=7, rok_dana=7))
    automation.seed_user(make_korisnik(datum_zaposlenja=(NOW - datetime.timedelta(days=7)).date()))

    result1 = service.assign_due_surveys(NOW)
    assert result1["assigned"] == 1
    assert len(survey.ucesca) == 1
    assert len(event.events) == 1

    # Simuliraj da je ucesce vec postoji za drugi prolaz (kao sto bi ga UNIQUE/upit video).
    automation.seed_participation(10, survey.ucesca[0].korisnik_id)
    result2 = service.assign_due_surveys(NOW)
    assert result2["assigned"] == 0
    assert len(survey.ucesca) == 1
    assert len(event.events) == 1


def test_already_existing_participation_is_skipped_without_new_ucesce():
    service, automation, survey, event = _service()
    survey.seed_survey(make_anketa())
    automation.seed_rule(make_pravilo(dani_od_zaposlenja=7, rok_dana=7))
    korisnik = automation.seed_user(make_korisnik(datum_zaposlenja=(NOW - datetime.timedelta(days=7)).date()))
    automation.seed_participation(10, korisnik.id)

    result = service.assign_due_surveys(NOW)
    assert result["assigned"] == 0
    assert survey.ucesca == []
    assert event.events == []


# ================================================================= rollback
def test_error_mid_batch_propagates_without_swallowing():
    """Servis ne hvata izuzetke - poziva TRANSAKCIJA (discover_events) mora rollback-ovati
    ceo batch. Ovde proveravamo da se izuzetak iz enqueue_if_absent NE guta."""
    service, automation, survey, event = _service()
    survey.seed_survey(make_anketa())
    automation.seed_rule(make_pravilo(dani_od_zaposlenja=7, rok_dana=7))
    automation.seed_user(make_korisnik(datum_zaposlenja=(NOW - datetime.timedelta(days=7)).date()))
    korisnik2 = automation.seed_user(make_korisnik(datum_zaposlenja=(NOW - datetime.timedelta(days=7)).date()))
    failing_kljuc = f"ONBOARDING_SURVEY_AVAILABLE:10:{korisnik2.id}:{korisnik2.datum_zaposlenja.isoformat()}"
    event.fail_on_key = failing_kljuc

    with pytest.raises(RuntimeError):
        service.assign_due_surveys(NOW)
    # Nema commit-a u servisu samom - pozivalac (discover_events) je taj koji rollback-uje;
    # ovde samo potvrdjujemo da izuzetak stize do pozivaoca netaknut.


# ================================================================= ciljanje (bez SVI/ORGJED)
def test_automatic_survey_gets_no_broad_targets():
    """Onboarding dodela NIKAD ne zove _materialize_targets/AnketaCilj - dodeljuje se
    iskljucivo kroz PULS_ANKETA_UCESCA po korisniku."""
    service, automation, survey, event = _service()
    survey.seed_survey(make_anketa())
    automation.seed_rule(make_pravilo(dani_od_zaposlenja=7, rok_dana=7))
    automation.seed_user(make_korisnik(datum_zaposlenja=(NOW - datetime.timedelta(days=7)).date()))

    service.assign_due_surveys(NOW)
    assert not hasattr(survey, "targets")
    assert not any(hasattr(survey, attr) for attr in ("add_target", "cilj", "ciljevi"))


# ================================================================= preskoci neispravnu anketu
def test_survey_not_active_is_skipped_without_error():
    service, automation, survey, event = _service()
    survey.seed_survey(make_anketa(status="DRAFT"))
    automation.seed_rule(make_pravilo(dani_od_zaposlenja=7, rok_dana=7))
    automation.seed_user(make_korisnik(datum_zaposlenja=(NOW - datetime.timedelta(days=7)).date()))

    result = service.assign_due_surveys(NOW)
    assert result["assigned"] == 0
    assert survey.ucesca == []


def test_anonymous_survey_is_skipped_without_error():
    service, automation, survey, event = _service()
    survey.seed_survey(make_anketa(anonimna="D"))
    automation.seed_rule(make_pravilo(dani_od_zaposlenja=7, rok_dana=7))
    automation.seed_user(make_korisnik(datum_zaposlenja=(NOW - datetime.timedelta(days=7)).date()))

    result = service.assign_due_surveys(NOW)
    assert result["assigned"] == 0
    assert survey.ucesca == []


def test_missing_survey_is_skipped_without_error():
    service, automation, survey, event = _service()
    automation.seed_rule(make_pravilo(anketa_id=999, dani_od_zaposlenja=7, rok_dana=7))
    automation.seed_user(make_korisnik(datum_zaposlenja=(NOW - datetime.timedelta(days=7)).date()))

    result = service.assign_due_surveys(NOW)
    assert result["assigned"] == 0


def test_assignment_accepts_oracle_decimal_day_values():
    from decimal import Decimal

    service, automation, survey, event = _service()
    survey.seed_survey(make_anketa())
    automation.seed_rule(make_pravilo(dani_od_zaposlenja=Decimal("7"), rok_dana=Decimal("7")))
    automation.seed_user(make_korisnik(datum_zaposlenja=(NOW - datetime.timedelta(days=7)).date()))

    assert service.assign_due_surveys(NOW)["assigned"] == 1
    u = survey.ucesca[0]
    assert u.datum_isteka - u.datum_dostupnosti == datetime.timedelta(days=7)
