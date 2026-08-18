import datetime

import pytest

from app.core.exceptions import (
    IdeaEditNotAllowedError,
    IdeaLimitReachedError,
    IdeaNotFoundError,
    NoActiveIdeaCycleError,
)
from app.services.idea_service import IdeaService
from tests.fakes import (
    FakeAuditService,
    FakeConfigurationService,
    FakeDb,
    FakeIdeaCycleRepository,
    FakeIdeaKorisnikRepository,
    FakeIdeaRepository,
    make_ciklus,
    make_ideja,
    make_korisnik,
)


def make_service(
    korisnik,
    cycles=None,
    ideje=None,
    config=None,
    rasporedi=None,
):
    db = FakeDb()
    idea_repo = FakeIdeaRepository(ideje)
    cycle_repo = FakeIdeaCycleRepository(cycles)
    korisnik_repo = FakeIdeaKorisnikRepository([korisnik], rasporedi=rasporedi)
    audit = FakeAuditService()
    service = IdeaService(
        db=db,
        idea_repository=idea_repo,
        cycle_repository=cycle_repo,
        korisnik_repository=korisnik_repo,
        configuration_service=FakeConfigurationService(config or {}),
        audit_service=audit,
    )
    return service, db, idea_repo, cycle_repo, audit


def _ready_user(**overrides):
    return make_korisnik(obavezna_promena_lozinke="N", telefon_potvrdjen="D", **overrides)


def test_create_idea_in_active_cycle():
    korisnik = _ready_user()
    ciklus = make_ciklus()
    service, db, idea_repo, _, audit = make_service(
        korisnik, cycles=[ciklus], rasporedi={korisnik.id: "ORG-1"}
    )

    ideja = service.create_idea(korisnik, "Naslov", "Opis ideje")

    assert ideja.ciklus_id == ciklus.id
    assert ideja.status == "POSLATA"
    assert ideja.orgjed_sifra == "ORG-1"
    assert db.committed == 1
    assert any(e["sifra_akcije"] == "IDEA_CREATED" for e in audit.entries)


def test_author_is_taken_from_token_not_request():
    korisnik = _ready_user(id=99, platni_broj="55555", ime="Ana", prezime="Anic")
    service, _, _, _, _ = make_service(korisnik, cycles=[make_ciklus()])

    ideja = service.create_idea(korisnik, "N", "O")

    assert ideja.korisnik_id == 99
    assert ideja.platni_broj == "55555"
    assert ideja.ime_autora == "Ana"
    assert ideja.prezime_autora == "Anic"


def test_create_without_active_cycle_raises():
    korisnik = _ready_user()
    service, db, _, _, _ = make_service(korisnik, cycles=[])

    with pytest.raises(NoActiveIdeaCycleError):
        service.create_idea(korisnik, "N", "O")
    assert db.rolled_back == 1


def test_create_outside_time_window_raises():
    korisnik = _ready_user()
    now = datetime.datetime.now()
    past = make_ciklus(
        datum_pocetka=now - datetime.timedelta(days=10),
        datum_zavrsetka=now - datetime.timedelta(days=1),
    )
    service, _, _, _, _ = make_service(korisnik, cycles=[past])

    with pytest.raises(NoActiveIdeaCycleError):
        service.create_idea(korisnik, "N", "O")


def test_limit_reached_raises():
    korisnik = _ready_user(id=7)
    ciklus = make_ciklus(id=1)
    existing = [make_ideja(korisnik_id=7, ciklus_id=1) for _ in range(3)]
    service, _, _, _, _ = make_service(
        korisnik, cycles=[ciklus], ideje=existing, config={"MAX_IDEJA_PO_CIKLUSU": 3}
    )

    with pytest.raises(IdeaLimitReachedError):
        service.create_idea(korisnik, "N", "O")


def test_rejected_idea_still_counts_toward_limit():
    korisnik = _ready_user(id=7)
    ciklus = make_ciklus(id=1)
    # 2 odbijene + 1 poslata = 3 -> limit dostignut
    existing = [
        make_ideja(korisnik_id=7, ciklus_id=1, status="ODBIJENA"),
        make_ideja(korisnik_id=7, ciklus_id=1, status="ODBIJENA"),
        make_ideja(korisnik_id=7, ciklus_id=1, status="POSLATA"),
    ]
    service, _, _, _, _ = make_service(
        korisnik, cycles=[ciklus], ideje=existing, config={"MAX_IDEJA_PO_CIKLUSU": 3}
    )

    with pytest.raises(IdeaLimitReachedError):
        service.create_idea(korisnik, "N", "O")


def test_user_sees_only_own_ideas():
    korisnik = _ready_user(id=7)
    ideje = [
        make_ideja(korisnik_id=7, ciklus_id=1),
        make_ideja(korisnik_id=8, ciklus_id=1),
    ]
    service, _, _, _, _ = make_service(korisnik, ideje=ideje)

    mine = service.list_my_ideas(korisnik)
    assert all(i.korisnik_id == 7 for i in mine)
    assert len(mine) == 1


def test_get_other_users_idea_raises_not_found():
    korisnik = _ready_user(id=7)
    tudja = make_ideja(korisnik_id=8, ciklus_id=1)
    service, _, _, _, _ = make_service(korisnik, ideje=[tudja])

    with pytest.raises(IdeaNotFoundError):
        service.get_my_idea(korisnik, tudja.id)


def test_update_other_users_idea_raises_not_found():
    korisnik = _ready_user(id=7)
    tudja = make_ideja(korisnik_id=8, ciklus_id=1)
    service, _, _, _, _ = make_service(korisnik, cycles=[make_ciklus(id=1)], ideje=[tudja])

    with pytest.raises(IdeaNotFoundError):
        service.update_my_idea(korisnik, tudja.id, "X", "Y")


def test_poslata_idea_can_be_updated():
    korisnik = _ready_user(id=7)
    ciklus = make_ciklus(id=1)
    ideja = make_ideja(korisnik_id=7, ciklus_id=1, status="POSLATA")
    service, db, _, _, audit = make_service(korisnik, cycles=[ciklus], ideje=[ideja])

    updated = service.update_my_idea(korisnik, ideja.id, "Novi naslov", "Novi opis")

    assert updated.naslov == "Novi naslov"
    assert updated.opis == "Novi opis"
    assert db.committed == 1
    assert any(e["sifra_akcije"] == "IDEA_UPDATED" for e in audit.entries)


def test_u_obradi_idea_cannot_be_updated():
    korisnik = _ready_user(id=7)
    ciklus = make_ciklus(id=1)
    ideja = make_ideja(korisnik_id=7, ciklus_id=1, status="U_OBRADI")
    service, db, _, _, _ = make_service(korisnik, cycles=[ciklus], ideje=[ideja])

    with pytest.raises(IdeaEditNotAllowedError):
        service.update_my_idea(korisnik, ideja.id, "X", "Y")
    assert db.rolled_back == 1


def test_idea_cannot_be_updated_after_cycle_end():
    korisnik = _ready_user(id=7)
    now = datetime.datetime.now()
    zatvoren = make_ciklus(
        id=1,
        status="ZATVOREN",
        datum_pocetka=now - datetime.timedelta(days=10),
        datum_zavrsetka=now - datetime.timedelta(days=1),
    )
    ideja = make_ideja(korisnik_id=7, ciklus_id=1, status="POSLATA")
    service, _, _, _, _ = make_service(korisnik, cycles=[zatvoren], ideje=[ideja])

    with pytest.raises(IdeaEditNotAllowedError):
        service.update_my_idea(korisnik, ideja.id, "X", "Y")


def test_current_cycle_overview_counts():
    korisnik = _ready_user(id=7)
    ciklus = make_ciklus(id=1)
    ideje = [make_ideja(korisnik_id=7, ciklus_id=1)]
    service, _, _, _, _ = make_service(
        korisnik, cycles=[ciklus], ideje=ideje, config={"MAX_IDEJA_PO_CIKLUSU": 3}
    )

    overview = service.get_current_cycle_overview(korisnik)
    assert overview.submission_open is True
    assert overview.max_ideas == 3
    assert overview.used_ideas == 1
    assert overview.remaining_ideas == 2


def test_current_cycle_overview_without_active_cycle():
    korisnik = _ready_user()
    service, _, _, _, _ = make_service(korisnik, cycles=[])

    overview = service.get_current_cycle_overview(korisnik)
    assert overview.cycle is None
    assert overview.submission_open is False
    assert overview.remaining_ideas == 0