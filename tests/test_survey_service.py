import pytest

from app.core.exceptions import (
    SurveyAlreadySubmittedError,
    SurveyNotTargetedError,
    ValidationBusinessError,
)
from app.schemas.survey import OdgovorIn
from app.services.survey_service import SurveyService
from tests.fakes import FakeAuditService, make_korisnik
from tests.survey_fakes import (
    FakeSurveyDb,
    FakeSurveyRepo,
    add_opcija,
    add_pitanje,
    add_sekcija,
    add_ucesce,
    add_uslov,
    make_anketa,
    make_tip,
)

USER_ID = 7


def make_service(repo):
    if "PULS" not in repo.types:
        repo.add_type(make_tip())
    db = FakeSurveyDb()
    return SurveyService(db=db, repository=repo, audit_service=FakeAuditService()), db


def _user():
    return make_korisnik(id=USER_ID, platni_broj="55", obavezna_promena_lozinke="N", telefon_potvrdjen="D")


def _conditional_survey(repo, anonimna="N"):
    """q1 BOOLEAN (obavezno); q2 TEXT (obavezno) vidljivo kada je q1 = false."""
    a = make_anketa(repo, status="ACTIVE", anonimna=anonimna)
    sec = add_sekcija(repo, a.id, 1)
    q1 = add_pitanje(repo, sec.id, "BOOLEAN", redosled=1, obavezno="D")
    q2 = add_pitanje(
        repo, sec.id, "TEXT", redosled=2, obavezno="D", uslov_pitanje_id=q1.id, uslov_operator="EQUALS"
    )
    add_uslov(repo, q2.id, "false")
    add_ucesce(repo, a.id, USER_ID, "NOT_STARTED")
    return a, q1, q2


def test_draft_does_not_require_all_and_sets_in_progress():
    repo = FakeSurveyRepo()
    a, q1, q2 = _conditional_survey(repo)
    service, db = make_service(repo)

    status = service.save_draft(_user(), a.id, [OdgovorIn(pitanje_id=q1.id, logicka=True)])

    assert status == "IN_PROGRESS"
    assert repo.get_ucesce(a.id, USER_ID).status == "IN_PROGRESS"


def test_draft_does_not_store_hidden_answers():
    repo = FakeSurveyRepo()
    a, q1, q2 = _conditional_survey(repo)
    service, db = make_service(repo)

    # q1 = true -> q2 skriveno; iako saljemo q2, ne sme se sacuvati
    service.save_draft(
        _user(),
        a.id,
        [OdgovorIn(pitanje_id=q1.id, logicka=True), OdgovorIn(pitanje_id=q2.id, tekst="skriveno")],
    )
    saved = repo.get_draft_answers(a.id, USER_ID)
    assert [d.pitanje_id for d in saved] == [q1.id]


def test_draft_replacement_removes_previous():
    repo = FakeSurveyRepo()
    a, q1, q2 = _conditional_survey(repo)
    service, db = make_service(repo)

    service.save_draft(
        _user(),
        a.id,
        [OdgovorIn(pitanje_id=q1.id, logicka=False), OdgovorIn(pitanje_id=q2.id, tekst="razlog")],
    )
    assert len(repo.get_draft_answers(a.id, USER_ID)) == 2
    # ponovni draft samo sa q1=true -> q2 nestaje
    service.save_draft(_user(), a.id, [OdgovorIn(pitanje_id=q1.id, logicka=True)])
    assert [d.pitanje_id for d in repo.get_draft_answers(a.id, USER_ID)] == [q1.id]


def test_submit_requires_visible_mandatory():
    repo = FakeSurveyRepo()
    a, q1, q2 = _conditional_survey(repo)
    service, db = make_service(repo)

    # q1=false -> q2 vidljivo i obavezno, a nije poslato
    with pytest.raises(ValidationBusinessError):
        service.submit(_user(), a.id, [OdgovorIn(pitanje_id=q1.id, logicka=False)])


def test_submit_hidden_mandatory_does_not_block():
    repo = FakeSurveyRepo()
    a, q1, q2 = _conditional_survey(repo)
    service, db = make_service(repo)

    ucesce = service.submit(_user(), a.id, [OdgovorIn(pitanje_id=q1.id, logicka=True)])
    assert ucesce.status == "SUBMITTED"


def test_resubmit_rejected():
    repo = FakeSurveyRepo()
    a, q1, q2 = _conditional_survey(repo)
    service, db = make_service(repo)

    service.submit(_user(), a.id, [OdgovorIn(pitanje_id=q1.id, logicka=True)])
    with pytest.raises(SurveyAlreadySubmittedError):
        service.submit(_user(), a.id, [OdgovorIn(pitanje_id=q1.id, logicka=True)])


def test_non_anonymous_submission_links_user_and_shows_answers():
    repo = FakeSurveyRepo()
    a, q1, q2 = _conditional_survey(repo, anonimna="N")
    service, db = make_service(repo)

    service.submit(_user(), a.id, [OdgovorIn(pitanje_id=q1.id, logicka=True)])
    predaja = repo.submissions[0]
    assert predaja.korisnik_id == USER_ID and predaja.anonimna == "N"

    detail = service.get_detail(_user(), a.id)
    assert detail["odgovori_dostupni"] is True
    assert any(o.pitanje_id == q1.id for o in detail["moji_odgovori"])


def test_anonymous_submission_hides_user_and_answers():
    repo = FakeSurveyRepo()
    a, q1, q2 = _conditional_survey(repo, anonimna="D")
    service, db = make_service(repo)

    service.submit(_user(), a.id, [OdgovorIn(pitanje_id=q1.id, logicka=True)])
    predaja = repo.submissions[0]
    assert predaja.anonimna == "D" and predaja.korisnik_id is None
    # nacrti obrisani
    assert repo.get_draft_answers(a.id, USER_ID) == []
    # finalni odgovori postoje ali bez veze ka korisniku
    assert len(repo.answers) == 1

    detail = service.get_detail(_user(), a.id)
    assert detail["odgovori_dostupni"] is False
    assert detail["moji_odgovori"] == []


def test_multi_choice_stores_multiple_options():
    repo = FakeSurveyRepo()
    a = make_anketa(repo, status="ACTIVE")
    sec = add_sekcija(repo, a.id, 1)
    q = add_pitanje(repo, sec.id, "MULTI_CHOICE", redosled=1, obavezno="D")
    o1 = add_opcija(repo, q.id, 1)
    o2 = add_opcija(repo, q.id, 2)
    add_ucesce(repo, a.id, USER_ID, "NOT_STARTED")
    service, db = make_service(repo)

    service.submit(_user(), a.id, [OdgovorIn(pitanje_id=q.id, opcija_ids=[o1.id, o2.id])])
    assert len(repo.answer_options) == 2


def test_option_must_belong_to_question():
    repo = FakeSurveyRepo()
    a = make_anketa(repo, status="ACTIVE")
    sec = add_sekcija(repo, a.id, 1)
    q = add_pitanje(repo, sec.id, "SINGLE_CHOICE", redosled=1, obavezno="D")
    add_opcija(repo, q.id, 1)
    add_ucesce(repo, a.id, USER_ID, "NOT_STARTED")
    service, db = make_service(repo)

    with pytest.raises(ValidationBusinessError):
        service.submit(_user(), a.id, [OdgovorIn(pitanje_id=q.id, opcija_ids=[999999])])


def test_rating_range_enforced():
    repo = FakeSurveyRepo()
    a = make_anketa(repo, status="ACTIVE")
    sec = add_sekcija(repo, a.id, 1)
    q = add_pitanje(repo, sec.id, "RATING_1_5", redosled=1, obavezno="D")
    add_ucesce(repo, a.id, USER_ID, "NOT_STARTED")
    service, db = make_service(repo)

    with pytest.raises(ValidationBusinessError):
        service.submit(_user(), a.id, [OdgovorIn(pitanje_id=q.id, broj=7)])


def test_duplicate_question_rejected():
    repo = FakeSurveyRepo()
    a, q1, q2 = _conditional_survey(repo)
    service, db = make_service(repo)

    with pytest.raises(ValidationBusinessError):
        service.submit(
            _user(),
            a.id,
            [OdgovorIn(pitanje_id=q1.id, logicka=True), OdgovorIn(pitanje_id=q1.id, logicka=False)],
        )


def test_user_not_targeted_cannot_access():
    repo = FakeSurveyRepo()
    a = make_anketa(repo, status="ACTIVE")
    service, db = make_service(repo)

    with pytest.raises(SurveyNotTargetedError):
        service.get_detail(_user(), a.id)


def _service_with_audit(repo):
    if "PULS" not in repo.types:
        repo.add_type(make_tip())
    audit = FakeAuditService()
    return SurveyService(db=FakeSurveyDb(), repository=repo, audit_service=audit), audit


def test_anonymous_submit_audit_has_no_user():
    repo = FakeSurveyRepo()
    a, q1, q2 = _conditional_survey(repo, anonimna="D")
    service, audit = _service_with_audit(repo)

    service.submit(_user(), a.id, [OdgovorIn(pitanje_id=q1.id, logicka=True)])

    entry = next(e for e in audit.entries if e["sifra_akcije"] == "SURVEY_SUBMITTED")
    assert entry["korisnik_id"] is None
    assert entry["platni_broj"] is None
    assert "predaja_id" not in entry
    assert entry["entitet_id"] == str(a.id)


def test_anonymous_submission_datum_predaje_is_null():
    repo = FakeSurveyRepo()
    a, q1, q2 = _conditional_survey(repo, anonimna="D")
    service, db = make_service(repo)

    service.submit(_user(), a.id, [OdgovorIn(pitanje_id=q1.id, logicka=True)])
    predaja = repo.submissions[0]
    assert predaja.korisnik_id is None
    assert predaja.datum_predaje is None
    # Ucesce i dalje cuva stvarno vreme (evidencija ucesca).
    assert repo.get_ucesce(a.id, USER_ID).datum_predaje is not None


def test_non_anonymous_submission_has_real_datum():
    repo = FakeSurveyRepo()
    a, q1, q2 = _conditional_survey(repo, anonimna="N")
    service, audit = _service_with_audit(repo)

    service.submit(_user(), a.id, [OdgovorIn(pitanje_id=q1.id, logicka=True)])
    predaja = repo.submissions[0]
    assert predaja.korisnik_id == USER_ID
    assert predaja.datum_predaje is not None
    entry = next(e for e in audit.entries if e["sifra_akcije"] == "SURVEY_SUBMITTED")
    assert entry["korisnik_id"] == USER_ID
    assert entry["platni_broj"] == "55"


def test_list_excludes_future_scheduled():
    import datetime

    repo = FakeSurveyRepo()
    a = make_anketa(
        repo,
        status="SCHEDULED",
        datum_pocetka=datetime.datetime.now() + datetime.timedelta(days=2),
        datum_zavrsetka=datetime.datetime.now() + datetime.timedelta(days=5),
    )
    add_ucesce(repo, a.id, USER_ID, "NOT_STARTED")
    service, db = make_service(repo)

    items, za = service.list_surveys(_user())
    assert items == [] and za == 0


def test_list_excludes_expired_unsubmitted():
    import datetime

    repo = FakeSurveyRepo()
    a = make_anketa(
        repo,
        status="CLOSED",
        datum_pocetka=datetime.datetime.now() - datetime.timedelta(days=5),
        datum_zavrsetka=datetime.datetime.now() - datetime.timedelta(days=1),
    )
    add_ucesce(repo, a.id, USER_ID, "NOT_STARTED")
    service, db = make_service(repo)

    items, za = service.list_surveys(_user())
    assert items == [] and za == 0


def test_list_includes_closed_but_submitted():
    import datetime

    repo = FakeSurveyRepo()
    a = make_anketa(
        repo,
        status="CLOSED",
        datum_pocetka=datetime.datetime.now() - datetime.timedelta(days=5),
        datum_zavrsetka=datetime.datetime.now() - datetime.timedelta(days=1),
    )
    add_ucesce(repo, a.id, USER_ID, "SUBMITTED")
    service, db = make_service(repo)

    items, za = service.list_surveys(_user())
    assert len(items) == 1 and za == 0


def test_submit_uses_ucesce_for_update():
    repo = FakeSurveyRepo()
    a, q1, q2 = _conditional_survey(repo)
    calls = {"for_update": 0}
    orig = repo.get_ucesce_for_update

    def spy(aid, kid):
        calls["for_update"] += 1
        return orig(aid, kid)

    repo.get_ucesce_for_update = spy
    service, db = make_service(repo)

    service.submit(_user(), a.id, [OdgovorIn(pitanje_id=q1.id, logicka=True)])
    assert calls["for_update"] == 1