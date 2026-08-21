import datetime

import pytest

from app.core.exceptions import (
    InvalidSurveyStatusTransitionError,
    SurveyStructureLockedError,
    ValidationBusinessError,
)
from app.services.survey_admin_service import SurveyAdminService
from tests.fakes import FakeAuditService, FakeSystemNotificationService, make_korisnik
from tests.survey_fakes import (
    FakeSurveyDb,
    FakeSurveyRepo,
    FakeTargetingRepo,
    add_cilj,
    add_pitanje,
    add_sekcija,
    add_uslov,
    make_anketa,
    make_tip,
)


def make_service(repo=None, targeting=None):
    repo = repo or FakeSurveyRepo()
    if "PULS" not in repo.types:
        repo.add_type(make_tip())
    targeting = targeting or FakeTargetingRepo(all_ids={1, 2, 3})
    db = FakeSurveyDb()
    service = SurveyAdminService(
        db=db,
        repository=repo,
        targeting_repository=targeting,
        audit_service=FakeAuditService(),
        system_notification_service=FakeSystemNotificationService(),
    )
    return service, repo, db


def _actor():
    return make_korisnik(id=1, platni_broj="admin1")


def _valid_draft(repo, anonimna="N"):
    a = make_anketa(repo, status="DRAFT", anonimna=anonimna)
    sec = add_sekcija(repo, a.id, 1)
    add_pitanje(repo, sec.id, "BOOLEAN", redosled=1, obavezno="D")
    add_cilj(repo, a.id, "SVI")
    return a


def test_activation_materializes_all_active():
    service, repo, db = make_service(targeting=FakeTargetingRepo(all_ids={1, 2, 3}))
    a = _valid_draft(repo)

    service.change_status(_actor(), a.id, "ACTIVE")

    assert a.status == "ACTIVE"
    assert repo.count_participants(a.id) == 3


def test_two_rules_produce_single_participation():
    targeting = FakeTargetingRepo(all_ids={1, 2}, by_orgjed={"409": {2, 3}})
    service, repo, db = make_service(targeting=targeting)
    a = make_anketa(repo, status="DRAFT")
    sec = add_sekcija(repo, a.id, 1)
    add_pitanje(repo, sec.id, "BOOLEAN", redosled=1)
    add_cilj(repo, a.id, "SVI")
    add_cilj(repo, a.id, "ORGJED", "409")

    service.change_status(_actor(), a.id, "ACTIVE")

    # distinct {1,2,3} -> 3 ucesca, po jedan red
    assert repo.count_participants(a.id) == 3
    assert sorted(u.korisnik_id for u in repo.ucesca) == [1, 2, 3]


def test_centrala_target_is_blocked():
    service, repo, db = make_service()
    a = make_anketa(repo, status="DRAFT")
    sec = add_sekcija(repo, a.id, 1)
    add_pitanje(repo, sec.id, "BOOLEAN", redosled=1)
    add_cilj(repo, a.id, "CENTRALA")

    with pytest.raises(ValidationBusinessError):
        service.change_status(_actor(), a.id, "ACTIVE")


def test_invalid_status_transition():
    service, repo, db = make_service()
    a = make_anketa(repo, status="ACTIVE")

    with pytest.raises(InvalidSurveyStatusTransitionError):
        service.change_status(_actor(), a.id, "DRAFT")


def test_choice_question_without_options_cannot_activate():
    service, repo, db = make_service()
    a = make_anketa(repo, status="DRAFT")
    sec = add_sekcija(repo, a.id, 1)
    add_pitanje(repo, sec.id, "SINGLE_CHOICE", redosled=1)  # bez opcija
    add_cilj(repo, a.id, "SVI")

    with pytest.raises(ValidationBusinessError):
        service.change_status(_actor(), a.id, "ACTIVE")


def test_condition_cannot_reference_later_question():
    service, repo, db = make_service()
    a = make_anketa(repo, status="DRAFT")
    sec = add_sekcija(repo, a.id, 1)
    q1 = add_pitanje(repo, sec.id, "BOOLEAN", redosled=1, uslov_pitanje_id=None)
    q2 = add_pitanje(repo, sec.id, "BOOLEAN", redosled=2)
    # q1 zavisi od q2 (kasnije pitanje) -> nevalidno
    q1.uslov_pitanje_id = q2.id
    q1.uslov_operator = "EQUALS"
    add_uslov(repo, q1.id, "true")
    add_cilj(repo, a.id, "SVI")

    with pytest.raises(ValidationBusinessError):
        service.change_status(_actor(), a.id, "ACTIVE")


def test_invalid_condition_value_rejected():
    service, repo, db = make_service()
    a = make_anketa(repo, status="DRAFT")
    sec = add_sekcija(repo, a.id, 1)
    q1 = add_pitanje(repo, sec.id, "BOOLEAN", redosled=1)
    q2 = add_pitanje(repo, sec.id, "TEXT", redosled=2, uslov_pitanje_id=q1.id, uslov_operator="EQUALS")
    add_uslov(repo, q2.id, "mozda")  # BOOLEAN dozvoljava samo true/false
    add_cilj(repo, a.id, "SVI")

    with pytest.raises(ValidationBusinessError):
        service.change_status(_actor(), a.id, "ACTIVE")


def test_update_locked_when_not_draft():
    service, repo, db = make_service()
    a = make_anketa(repo, status="ACTIVE")

    class _P:
        naziv = "x"
        opis = None
        tip_sifra = "PULS"
        anonimna = False
        datum_pocetka = datetime.datetime.now()
        datum_zavrsetka = datetime.datetime.now() + datetime.timedelta(days=1)
        sekcije = []
        ciljevi = []

    with pytest.raises(SurveyStructureLockedError):
        service.update_survey(_actor(), a.id, _P())


def test_extend_deadline_rejects_shortening():
    service, repo, db = make_service()
    now = datetime.datetime.now()
    a = make_anketa(repo, status="ACTIVE", datum_zavrsetka=now + datetime.timedelta(days=5))

    with pytest.raises(ValidationBusinessError):
        service.extend_deadline(_actor(), a.id, now + datetime.timedelta(days=1))


def test_extend_deadline_ok():
    service, repo, db = make_service()
    now = datetime.datetime.now()
    a = make_anketa(repo, status="ACTIVE", datum_zavrsetka=now + datetime.timedelta(days=5))

    service.extend_deadline(_actor(), a.id, now + datetime.timedelta(days=10))
    assert a.datum_zavrsetka > now + datetime.timedelta(days=9)


def _create_payload(**overrides):
    from app.schemas.survey import AdminCiljIn, AdminSurveyCreateRequest

    now = datetime.datetime.now()
    defaults = dict(
        naziv="Anketa",
        tip_sifra="PULS",
        anonimna=False,
        datum_pocetka=now - datetime.timedelta(days=1),
        datum_zavrsetka=now + datetime.timedelta(days=5),
        sekcije=[],
        ciljevi=[AdminCiljIn(tip_cilja="SVI")],
    )
    defaults.update(overrides)
    return AdminSurveyCreateRequest(**defaults)


def test_create_bad_date_range_is_validation_error():
    service, repo, db = make_service()
    now = datetime.datetime.now()
    payload = _create_payload(datum_pocetka=now, datum_zavrsetka=now - datetime.timedelta(days=1))
    with pytest.raises(ValidationBusinessError):
        service.create_survey(_actor(), payload)


def test_create_duplicate_section_redosled_rejected():
    from app.schemas.survey import AdminSekcijaIn

    service, repo, db = make_service()
    payload = _create_payload(
        sekcije=[
            AdminSekcijaIn(naziv="S1", redosled=1, pitanja=[]),
            AdminSekcijaIn(naziv="S2", redosled=1, pitanja=[]),
        ]
    )
    with pytest.raises(ValidationBusinessError):
        service.create_survey(_actor(), payload)


def test_create_duplicate_question_keys_rejected():
    from app.schemas.survey import AdminPitanjeIn, AdminSekcijaIn

    service, repo, db = make_service()
    payload = _create_payload(
        sekcije=[
            AdminSekcijaIn(
                naziv="S1",
                redosled=1,
                pitanja=[
                    AdminPitanjeIn(kljuc="q", tekst="A", tip="BOOLEAN", redosled=1),
                    AdminPitanjeIn(kljuc="q", tekst="B", tip="BOOLEAN", redosled=2),
                ],
            )
        ]
    )
    with pytest.raises(ValidationBusinessError):
        service.create_survey(_actor(), payload)


def test_create_duplicate_targets_rejected():
    from app.schemas.survey import AdminCiljIn

    service, repo, db = make_service()
    payload = _create_payload(ciljevi=[AdminCiljIn(tip_cilja="SVI"), AdminCiljIn(tip_cilja="SVI")])
    with pytest.raises(ValidationBusinessError):
        service.create_survey(_actor(), payload)


def test_condition_option_from_other_question_rejected():
    from app.schemas.survey import (
        AdminOpcijaIn,
        AdminPitanjeIn,
        AdminSekcijaIn,
        AdminUslovIn,
    )

    service, repo, db = make_service()
    payload = _create_payload(
        sekcije=[
            AdminSekcijaIn(
                naziv="S1",
                redosled=1,
                pitanja=[
                    AdminPitanjeIn(
                        kljuc="q1", tekst="A", tip="SINGLE_CHOICE", redosled=1,
                        opcije=[AdminOpcijaIn(kljuc="a1", tekst="A1", redosled=1)],
                    ),
                    AdminPitanjeIn(
                        kljuc="q2", tekst="B", tip="SINGLE_CHOICE", redosled=2,
                        opcije=[AdminOpcijaIn(kljuc="b1", tekst="B1", redosled=1)],
                    ),
                    AdminPitanjeIn(
                        tekst="C", tip="TEXT", redosled=3,
                        # uslov referencira q1 ali koristi opciju b1 (pripada q2) -> odbij
                        uslov=AdminUslovIn(pitanje_kljuc="q1", operator="EQUALS", vrednosti=["b1"]),
                    ),
                ],
            )
        ]
    )
    with pytest.raises(ValidationBusinessError):
        service.create_survey(_actor(), payload)


def test_scheduled_to_active_out_of_period_rejected():
    service, repo, db = make_service()
    now = datetime.datetime.now()
    a = make_anketa(
        repo,
        status="SCHEDULED",
        datum_pocetka=now + datetime.timedelta(days=2),
        datum_zavrsetka=now + datetime.timedelta(days=5),
    )
    with pytest.raises(ValidationBusinessError):
        service.change_status(_actor(), a.id, "ACTIVE")


def test_scheduled_to_active_within_period_ok():
    service, repo, db = make_service()
    now = datetime.datetime.now()
    a = make_anketa(
        repo,
        status="SCHEDULED",
        datum_pocetka=now - datetime.timedelta(days=1),
        datum_zavrsetka=now + datetime.timedelta(days=5),
    )
    service.change_status(_actor(), a.id, "ACTIVE")
    assert a.status == "ACTIVE"


def test_duplicate_survey_type_sifra_rejected():
    service, repo, db = make_service()  # tip 'PULS' vec postoji
    with pytest.raises(ValidationBusinessError):
        service.create_type(_actor(), "PULS", "Duplikat")


def test_cilj_vrednost_stored_normalized():
    from app.schemas.survey import AdminCiljIn

    service, repo, db = make_service()
    payload = _create_payload(ciljevi=[AdminCiljIn(tip_cilja="ORGJED", vrednost="  409  ")])
    anketa = service.create_survey(_actor(), payload)
    targets = repo.get_targets(anketa.id)
    assert targets[0].vrednost == "409"


def test_create_survey_resolves_condition_keys_and_activates():
    """End-to-end: kreiranje ankete sa uslovom (kljuc opcije) pa aktivacija."""
    from app.schemas.survey import (
        AdminCiljIn,
        AdminOpcijaIn,
        AdminPitanjeIn,
        AdminSekcijaIn,
        AdminSurveyCreateRequest,
        AdminUslovIn,
    )

    service, repo, db = make_service(targeting=FakeTargetingRepo(all_ids={1, 2}))
    payload = AdminSurveyCreateRequest(
        naziv="Anketa",
        tip_sifra="PULS",
        anonimna=False,
        datum_pocetka=datetime.datetime.now() - datetime.timedelta(days=1),
        datum_zavrsetka=datetime.datetime.now() + datetime.timedelta(days=5),
        sekcije=[
            AdminSekcijaIn(
                naziv="S1",
                redosled=1,
                pitanja=[
                    AdminPitanjeIn(
                        kljuc="q1",
                        tekst="Izbor?",
                        tip="SINGLE_CHOICE",
                        obavezno=True,
                        redosled=1,
                        opcije=[
                            AdminOpcijaIn(kljuc="da", tekst="Da", redosled=1),
                            AdminOpcijaIn(kljuc="ne", tekst="Ne", redosled=2),
                        ],
                    ),
                    AdminPitanjeIn(
                        tekst="Zasto ne?",
                        tip="TEXT",
                        obavezno=True,
                        redosled=2,
                        uslov=AdminUslovIn(pitanje_kljuc="q1", operator="EQUALS", vrednosti=["ne"]),
                    ),
                ],
            )
        ],
        ciljevi=[AdminCiljIn(tip_cilja="SVI")],
    )

    anketa = service.create_survey(_actor(), payload)
    # uslov vrednost "ne" je razresena na stvarni ID opcije (string)
    uslovi = repo.get_uslov_values_for_survey(anketa.id)
    assert len(uslovi) == 1
    opcije = repo.get_options_for_survey(anketa.id)
    ne_opcija = next(o for o in opcije if o.tekst == "Ne")
    assert uslovi[0].vrednost == str(ne_opcija.id)

    # struktura je validna -> aktivacija prolazi i materijalizuje ucesca
    service.change_status(_actor(), anketa.id, "ACTIVE")
    assert anketa.status == "ACTIVE"
    assert repo.count_participants(anketa.id) == 2

# ================================================== sistemska obavestenja (enqueue hook)
def test_activation_to_active_enqueues_survey_activated():
    service, repo, db = make_service(targeting=FakeTargetingRepo(all_ids={1, 2, 3}))
    a = _valid_draft(repo)

    service.change_status(_actor(), a.id, "ACTIVE")

    calls = [c for c in service.system_notifications.calls if c[0] == "enqueue_survey_activated"]
    assert calls == [("enqueue_survey_activated", (a.id,))]


def test_transition_to_scheduled_does_not_enqueue_activation():
    service, repo, db = make_service()
    now = datetime.datetime.now()
    a = make_anketa(
        repo, status="DRAFT",
        datum_pocetka=now + datetime.timedelta(days=1),
        datum_zavrsetka=now + datetime.timedelta(days=5),
    )
    sec = add_sekcija(repo, a.id, 1)
    add_pitanje(repo, sec.id, "BOOLEAN", redosled=1)
    add_cilj(repo, a.id, "SVI")

    service.change_status(_actor(), a.id, "SCHEDULED")

    assert service.system_notifications.calls == []
