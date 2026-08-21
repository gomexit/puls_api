import datetime

import pytest

from app.core.exceptions import AnonymousSurveyResponsesNotAvailableError, SurveyNotFoundError
from app.services.survey_results_service import SurveyResultsService, _median_from_counts
from tests.fakes import make_korisnik
from tests.survey_fakes import (
    FakeSurveyRepo,
    add_opcija,
    add_pitanje,
    add_sekcija,
    add_ucesce,
    make_anketa,
)
from tests.survey_results_fakes import (
    FakeSurveyResultsRepo,
    make_odgovor,
    make_odgovor_opcija,
    make_predaja,
    make_raspored,
)


def _service(survey_repo=None, korisnici=None, rasporedi=None):
    survey_repo = survey_repo or FakeSurveyRepo()
    results_repo = FakeSurveyResultsRepo(survey_repo, korisnici=korisnici, rasporedi=rasporedi)
    service = SurveyResultsService(db=None, results_repository=results_repo, survey_repository=survey_repo)
    return service, survey_repo, results_repo


# ============================================================== OPSTA STATISTIKA
def test_statistics_survey_not_found():
    service, _, _ = _service()
    with pytest.raises(SurveyNotFoundError):
        service.get_statistics(999)


def test_statistics_zero_targeted():
    service, repo, _ = _service()
    a = make_anketa(repo, status="CLOSED")
    stats = service.get_statistics(a.id)
    assert stats["odziv"] == {
        "ukupno_ciljanih": 0,
        "nije_zapocelo": 0,
        "u_toku": 0,
        "predato": 0,
        "nije_predato": 0,
        "procenat_odziva": 0.0,
    }
    assert stats["pitanja"] == []


def test_statistics_status_counts_and_percentage():
    service, repo, _ = _service()
    a = make_anketa(repo, status="CLOSED")
    add_ucesce(repo, a.id, 1, status="NOT_STARTED")
    add_ucesce(repo, a.id, 2, status="NOT_STARTED")
    add_ucesce(repo, a.id, 3, status="IN_PROGRESS")
    add_ucesce(repo, a.id, 4, status="SUBMITTED")
    add_ucesce(repo, a.id, 5, status="SUBMITTED")
    add_ucesce(repo, a.id, 6, status="SUBMITTED")
    stats = service.get_statistics(a.id)
    odziv = stats["odziv"]
    assert odziv["ukupno_ciljanih"] == 6
    assert odziv["nije_zapocelo"] == 2
    assert odziv["u_toku"] == 1
    assert odziv["predato"] == 3
    assert odziv["nije_predato"] == 3
    assert odziv["procenat_odziva"] == 50.0


def test_statistics_response_percentage_rounded():
    service, repo, _ = _service()
    a = make_anketa(repo, status="CLOSED")
    for i in range(3):
        add_ucesce(repo, a.id, i, status="SUBMITTED")
    add_ucesce(repo, a.id, 100, status="NOT_STARTED")
    stats = service.get_statistics(a.id)
    # 3/4 * 100 = 75.0 (deterministicki, tacna vrednost)
    assert stats["odziv"]["procenat_odziva"] == 75.0


# --------------------------------------------------------------- SINGLE_CHOICE
def test_single_choice_statistics_and_zero_option():
    service, repo, _ = _service()
    a = make_anketa(repo, status="CLOSED")
    sec = add_sekcija(repo, a.id, redosled=1, naziv="Sekcija A")
    q = add_pitanje(repo, sec.id, "SINGLE_CHOICE", redosled=1, tekst="Da li ste zadovoljni?")
    o1 = add_opcija(repo, q.id, redosled=1, tekst="Zadovoljan")
    o2 = add_opcija(repo, q.id, redosled=2, tekst="Nezadovoljan")

    p1 = make_predaja(repo, a.id, korisnik_id=1)
    od1 = make_odgovor(repo, p1.id, q.id)
    make_odgovor_opcija(repo, od1.id, o1.id)
    p2 = make_predaja(repo, a.id, korisnik_id=2)
    od2 = make_odgovor(repo, p2.id, q.id)
    make_odgovor_opcija(repo, od2.id, o1.id)

    stats = service.get_statistics(a.id)
    pitanje = stats["pitanja"][0]
    assert pitanje["pitanje_id"] == q.id
    assert pitanje["sekcija_naziv"] == "Sekcija A"
    assert pitanje["broj_odgovora"] == 2
    opcije = {o["opcija_id"]: o for o in pitanje["opcije"]}
    assert opcije[o1.id]["broj_izbora"] == 2
    assert opcije[o1.id]["procenat"] == 100.0
    # opcija bez odgovora vraca 0 i 0.00
    assert opcije[o2.id]["broj_izbora"] == 0
    assert opcije[o2.id]["procenat"] == 0.0


def test_multi_choice_percentage_can_exceed_100():
    service, repo, _ = _service()
    a = make_anketa(repo, status="CLOSED")
    sec = add_sekcija(repo, a.id)
    q = add_pitanje(repo, sec.id, "MULTI_CHOICE", redosled=1)
    o1 = add_opcija(repo, q.id, redosled=1, tekst="A")
    o2 = add_opcija(repo, q.id, redosled=2, tekst="B")

    p1 = make_predaja(repo, a.id, korisnik_id=1)
    od1 = make_odgovor(repo, p1.id, q.id)
    make_odgovor_opcija(repo, od1.id, o1.id)
    make_odgovor_opcija(repo, od1.id, o2.id)
    p2 = make_predaja(repo, a.id, korisnik_id=2)
    od2 = make_odgovor(repo, p2.id, q.id)
    make_odgovor_opcija(repo, od2.id, o1.id)

    stats = service.get_statistics(a.id)
    pitanje = stats["pitanja"][0]
    assert pitanje["broj_odgovora"] == 2
    opcije = {o["opcija_id"]: o for o in pitanje["opcije"]}
    assert opcije[o1.id]["broj_izbora"] == 2
    assert opcije[o1.id]["procenat"] == 100.0
    assert opcije[o2.id]["broj_izbora"] == 1
    assert opcije[o2.id]["procenat"] == 50.0
    # zbir procenata (150%) veci od 100% jer jedan odgovor moze imati vise opcija
    assert sum(o["procenat"] for o in pitanje["opcije"]) > 100.0


# --------------------------------------------------------------------- BOOLEAN
def test_boolean_d_n_counts():
    service, repo, _ = _service()
    a = make_anketa(repo, status="CLOSED")
    sec = add_sekcija(repo, a.id)
    q = add_pitanje(repo, sec.id, "BOOLEAN", redosled=1)

    for kid in range(4):
        p = make_predaja(repo, a.id, korisnik_id=kid)
        make_odgovor(repo, p.id, q.id, logicka="D")
    p5 = make_predaja(repo, a.id, korisnik_id=5)
    make_odgovor(repo, p5.id, q.id, logicka="N")

    stats = service.get_statistics(a.id)
    pitanje = stats["pitanja"][0]
    assert pitanje["da"] == {"broj": 4, "procenat": 80.0}
    assert pitanje["ne"] == {"broj": 1, "procenat": 20.0}
    assert pitanje["broj_odgovora"] == 5


# --------------------------------------------------------------------- RATING
def test_rating_average_and_distribution():
    service, repo, _ = _service()
    a = make_anketa(repo, status="CLOSED")
    sec = add_sekcija(repo, a.id)
    q = add_pitanje(repo, sec.id, "RATING_1_5", redosled=1)

    values = [1, 5, 4, 4, 5]
    for i, v in enumerate(values):
        p = make_predaja(repo, a.id, korisnik_id=i)
        make_odgovor(repo, p.id, q.id, broj=v)

    stats = service.get_statistics(a.id)
    pitanje = stats["pitanja"][0]
    assert pitanje["broj_odgovora"] == 5
    assert pitanje["prosek"] == round(sum(values) / len(values), 2)
    assert pitanje["minimum"] == 1
    assert pitanje["maksimum"] == 5
    raspodela = {r["vrednost"]: r for r in pitanje["raspodela"]}
    assert set(raspodela.keys()) == {1, 2, 3, 4, 5}  # ceo raspon, uklj. nule
    assert raspodela[2]["broj"] == 0 and raspodela[2]["procenat"] == 0.0
    assert raspodela[4]["broj"] == 2


def test_rating_median_odd_count():
    assert _median_from_counts({1: 1, 3: 1, 5: 1}) == 3.0  # neparan broj: 1,3,5 -> 3


def test_rating_median_even_count():
    assert _median_from_counts({1: 1, 2: 1, 3: 1, 4: 1}) == 2.5  # paran: (2+3)/2


def test_rating_without_answers_is_null_but_distribution_present():
    service, repo, _ = _service()
    a = make_anketa(repo, status="CLOSED")
    sec = add_sekcija(repo, a.id)
    add_pitanje(repo, sec.id, "RATING_1_10", redosled=1)
    stats = service.get_statistics(a.id)
    pitanje = stats["pitanja"][0]
    assert pitanje["prosek"] is None
    assert pitanje["medijana"] is None
    assert pitanje["minimum"] is None
    assert pitanje["maksimum"] is None
    assert len(pitanje["raspodela"]) == 10
    assert all(r["broj"] == 0 for r in pitanje["raspodela"])


# ------------------------------------------------------------------------ TEXT
def test_text_question_returns_only_count():
    service, repo, _ = _service()
    a = make_anketa(repo, status="CLOSED")
    sec = add_sekcija(repo, a.id)
    q = add_pitanje(repo, sec.id, "TEXT", redosled=1)
    p = make_predaja(repo, a.id, korisnik_id=1)
    make_odgovor(repo, p.id, q.id, tekst="TAJNI ODGOVOR")

    stats = service.get_statistics(a.id)
    pitanje = stats["pitanja"][0]
    assert pitanje["broj_odgovora"] == 1
    assert pitanje.get("opcije") is None
    assert pitanje.get("da") is None
    assert pitanje.get("prosek") is None
    # sirovi tekst se NIKADA ne pojavljuje u statistickom odgovoru
    assert "TAJNI ODGOVOR" not in str(pitanje)


# ------------------------------------------------------------------- USLOVNA
def test_conditional_question_denominator_is_actual_answers():
    service, repo, _ = _service()
    a = make_anketa(repo, status="CLOSED")
    sec = add_sekcija(repo, a.id)
    control = add_pitanje(repo, sec.id, "BOOLEAN", redosled=1)
    conditional = add_pitanje(
        repo, sec.id, "SINGLE_CHOICE", redosled=2, uslov_pitanje_id=control.id, uslov_operator="EQUALS"
    )
    opt = add_opcija(repo, conditional.id, redosled=1, tekst="X")

    # 3 korisnika odgovore na kontrolno pitanje, samo 1 vidi/odgovori na uslovno.
    for kid in range(3):
        p = make_predaja(repo, a.id, korisnik_id=kid)
        make_odgovor(repo, p.id, control.id, logicka="D")
    p_cond = make_predaja(repo, a.id, korisnik_id=99)
    od = make_odgovor(repo, p_cond.id, conditional.id)
    make_odgovor_opcija(repo, od.id, opt.id)

    stats = service.get_statistics(a.id)
    cond_stat = next(p for p in stats["pitanja"] if p["pitanje_id"] == conditional.id)
    assert cond_stat["broj_odgovora"] == 1
    assert cond_stat["opcije"][0]["procenat"] == 100.0


# --------------------------------------------------------------- SORTIRANJE
def test_sections_questions_options_sorted_by_redosled():
    service, repo, _ = _service()
    a = make_anketa(repo, status="CLOSED")
    sec2 = add_sekcija(repo, a.id, redosled=2, naziv="Druga")
    sec1 = add_sekcija(repo, a.id, redosled=1, naziv="Prva")
    add_pitanje(repo, sec1.id, "TEXT", redosled=2, tekst="Q1b")
    add_pitanje(repo, sec1.id, "TEXT", redosled=1, tekst="Q1a")
    q2 = add_pitanje(repo, sec2.id, "SINGLE_CHOICE", redosled=1, tekst="Q2a")
    add_opcija(repo, q2.id, redosled=2, tekst="Druga opcija")
    add_opcija(repo, q2.id, redosled=1, tekst="Prva opcija")

    stats = service.get_statistics(a.id)
    naslovi = [p["tekst"] for p in stats["pitanja"]]
    assert naslovi == ["Q1a", "Q1b", "Q2a"]
    opts = [o["tekst"] for o in stats["pitanja"][2]["opcije"]]
    assert opts == ["Prva opcija", "Druga opcija"]


# ============================================================== ANONIMNOST
def test_anonymous_statistics_no_identity_fields():
    service, repo, _ = _service()
    a = make_anketa(repo, status="CLOSED", anonimna="D")
    sec = add_sekcija(repo, a.id)
    q = add_pitanje(repo, sec.id, "TEXT", redosled=1)
    p = make_predaja(repo, a.id, korisnik_id=None, anonimna="D", datum_predaje=None)
    make_odgovor(repo, p.id, q.id, tekst="anon odgovor")

    stats = service.get_statistics(a.id)
    dump = str(stats)
    for forbidden in ("korisnik_id", "platni_broj", "predaja_id", "odgovor_id", "anon odgovor"):
        assert forbidden not in dump


def test_anonymous_responses_endpoint_returns_conflict():
    service, repo, _ = _service()
    a = make_anketa(repo, status="CLOSED", anonimna="D")
    with pytest.raises(AnonymousSurveyResponsesNotAvailableError):
        service.get_responses(a.id, 1, 20, None, None, None, None, None)


def test_anonymous_stats_never_reads_predaja_korisnik_id(monkeypatch):
    """FakeSurveyResultsRepo agregatne metode nikad ne pristupaju p.korisnik_id."""
    service, repo, results_repo = _service()
    a = make_anketa(repo, status="CLOSED", anonimna="D")
    sec = add_sekcija(repo, a.id)
    q = add_pitanje(repo, sec.id, "TEXT", redosled=1)
    p = make_predaja(repo, a.id, korisnik_id=None, anonimna="D")
    make_odgovor(repo, p.id, q.id, tekst="x")

    # get_statistics koristi samo ucesce_status_counts/answer_counts_by_question/...
    # - nijedna od njih ne prima niti cita korisnik_id predaje.
    service.get_statistics(a.id)  # ne sme baciti izuzetak niti pristupiti identitetu


# =========================================================== NEANONIMNI /responses
def _setup_responses_survey(repo):
    a = make_anketa(repo, status="CLOSED", anonimna="N")
    sec = add_sekcija(repo, a.id)
    q = add_pitanje(repo, sec.id, "SINGLE_CHOICE", redosled=1)
    opt = add_opcija(repo, q.id, redosled=1, tekst="OK")
    return a, q, opt


def test_responses_identity_and_answers():
    repo = FakeSurveyRepo()
    a, q, opt = _setup_responses_survey(repo)
    k = make_korisnik(id=1, platni_broj="12345", ime="Petar", prezime="Petrović")
    now = datetime.datetime(2026, 1, 1, 10, 0, 0)
    p = make_predaja(repo, a.id, korisnik_id=1, datum_predaje=now)
    od = make_odgovor(repo, p.id, q.id)
    make_odgovor_opcija(repo, od.id, opt.id)

    service, _, _ = _service(repo, korisnici=[k])
    result = service.get_responses(a.id, 1, 20, None, None, None, None, None)
    assert result["total"] == 1
    item = result["items"][0]
    assert item["korisnik"]["korisnik_id"] == 1
    assert item["korisnik"]["platni_broj"] == "12345"
    assert item["datum_predaje"] == now
    assert item["odgovori"][0]["opcije"][0]["opcija_id"] == opt.id


def test_responses_pagination():
    repo = FakeSurveyRepo()
    a, q, opt = _setup_responses_survey(repo)
    korisnici = []
    for i in range(5):
        k = make_korisnik(id=i, platni_broj=str(i))
        korisnici.append(k)
        make_predaja(repo, a.id, korisnik_id=i, datum_predaje=datetime.datetime(2026, 1, 1 + i))
    service, _, _ = _service(repo, korisnici=korisnici)
    page1 = service.get_responses(a.id, 1, 2, None, None, None, None, None)
    assert page1["total"] == 5 and len(page1["items"]) == 2 and page1["has_more"] is True
    page3 = service.get_responses(a.id, 3, 2, None, None, None, None, None)
    assert len(page3["items"]) == 1 and page3["has_more"] is False


def test_responses_stable_sort_datum_desc_id_desc():
    repo = FakeSurveyRepo()
    a, q, opt = _setup_responses_survey(repo)
    same = datetime.datetime(2026, 1, 1)
    korisnici = [make_korisnik(id=i, platni_broj=str(i)) for i in range(3)]
    p1 = make_predaja(repo, a.id, korisnik_id=0, datum_predaje=same)
    p2 = make_predaja(repo, a.id, korisnik_id=1, datum_predaje=same)
    make_predaja(repo, a.id, korisnik_id=2, datum_predaje=same - datetime.timedelta(days=1))
    service, _, _ = _service(repo, korisnici=korisnici)
    result = service.get_responses(a.id, 1, 20, None, None, None, None, None)
    ids_order = [it["korisnik"]["korisnik_id"] for it in result["items"]]
    # isti datum -> veci predaja.id prvi (p2 pre p1), stariji datum poslednji
    assert ids_order == [1, 0, 2]
    assert p2.id > p1.id


def test_responses_filter_platni_broj():
    repo = FakeSurveyRepo()
    a, q, opt = _setup_responses_survey(repo)
    k1 = make_korisnik(id=1, platni_broj="AAA")
    k2 = make_korisnik(id=2, platni_broj="BBB")
    make_predaja(repo, a.id, korisnik_id=1, datum_predaje=datetime.datetime(2026, 1, 1))
    make_predaja(repo, a.id, korisnik_id=2, datum_predaje=datetime.datetime(2026, 1, 2))
    service, _, _ = _service(repo, korisnici=[k1, k2])
    result = service.get_responses(a.id, 1, 20, "AAA", None, None, None, None)
    assert result["total"] == 1
    assert result["items"][0]["korisnik"]["platni_broj"] == "AAA"


def test_responses_filter_orgjed_no_duplicate_with_multiple_rasporedi():
    repo = FakeSurveyRepo()
    a, q, opt = _setup_responses_survey(repo)
    k1 = make_korisnik(id=1, platni_broj="1")
    make_predaja(repo, a.id, korisnik_id=1, datum_predaje=datetime.datetime(2026, 1, 1))
    rasporedi = [
        make_raspored(1, orgjed_sifra="001", primarni="D"),
        make_raspored(1, orgjed_sifra="001-SEC", primarni="N"),  # dupli aktivni raspored
    ]
    service, _, _ = _service(repo, korisnici=[k1], rasporedi=rasporedi)
    result = service.get_responses(a.id, 1, 20, None, "001", None, None, None)
    assert result["total"] == 1  # bez duplikata i pored dva aktivna rasporeda


def test_responses_combined_orgjed_and_radno_mesto_must_match_same_raspored():
    repo = FakeSurveyRepo()
    a, q, opt = _setup_responses_survey(repo)
    k1 = make_korisnik(id=1, platni_broj="1")
    make_predaja(repo, a.id, korisnik_id=1, datum_predaje=datetime.datetime(2026, 1, 1))
    rasporedi = [
        make_raspored(1, orgjed_sifra="OrgA", radno_mesto_sifra="Posao1", primarni="D"),
        make_raspored(1, orgjed_sifra="OrgB", radno_mesto_sifra="Posao2", primarni="N"),
    ]
    service, _, _ = _service(repo, korisnici=[k1], rasporedi=rasporedi)
    # OrgA+Posao2 ne postoji u ISTOM redu rasporeda -> ne sme vratiti korisnika.
    mismatched = service.get_responses(a.id, 1, 20, None, "OrgA", "Posao2", None, None)
    assert mismatched["total"] == 0
    # OrgA+Posao1 postoje u istom redu -> mora ga vratiti.
    matched = service.get_responses(a.id, 1, 20, None, "OrgA", "Posao1", None, None)
    assert matched["total"] == 1


def test_primary_active_raspored_selects_d_even_when_inserted_after_n():
    repo = FakeSurveyRepo()
    a, q, opt = _setup_responses_survey(repo)
    k1 = make_korisnik(id=1, platni_broj="1")
    make_predaja(repo, a.id, korisnik_id=1, datum_predaje=datetime.datetime(2026, 1, 1))
    rasporedi = [
        make_raspored(1, orgjed_sifra="N-org", primarni="N"),  # insertovano PRE 'D'
        make_raspored(1, orgjed_sifra="D-org", primarni="D"),
    ]
    service, _, _ = _service(repo, korisnici=[k1], rasporedi=rasporedi)
    result = service.get_responses(a.id, 1, 20, None, None, None, None, None)
    assert result["items"][0]["korisnik"]["orgjed_sifra"] == "D-org"


def test_responses_filter_radno_mesto():
    repo = FakeSurveyRepo()
    a, q, opt = _setup_responses_survey(repo)
    k1 = make_korisnik(id=1, platni_broj="1")
    k2 = make_korisnik(id=2, platni_broj="2")
    make_predaja(repo, a.id, korisnik_id=1, datum_predaje=datetime.datetime(2026, 1, 1))
    make_predaja(repo, a.id, korisnik_id=2, datum_predaje=datetime.datetime(2026, 1, 2))
    rasporedi = [make_raspored(1, radno_mesto_sifra="PRODAVAC", primarni="D")]
    service, _, _ = _service(repo, korisnici=[k1, k2], rasporedi=rasporedi)
    result = service.get_responses(a.id, 1, 20, None, None, "PRODAVAC", None, None)
    assert result["total"] == 1
    assert result["items"][0]["korisnik"]["korisnik_id"] == 1


def test_responses_filter_period():
    repo = FakeSurveyRepo()
    a, q, opt = _setup_responses_survey(repo)
    korisnici = [make_korisnik(id=i, platni_broj=str(i)) for i in range(3)]
    make_predaja(repo, a.id, korisnik_id=0, datum_predaje=datetime.datetime(2026, 1, 1))
    make_predaja(repo, a.id, korisnik_id=1, datum_predaje=datetime.datetime(2026, 1, 15))
    make_predaja(repo, a.id, korisnik_id=2, datum_predaje=datetime.datetime(2026, 2, 1))
    service, _, _ = _service(repo, korisnici=korisnici)
    result = service.get_responses(
        a.id, 1, 20, None, None, None, datetime.datetime(2026, 1, 10), datetime.datetime(2026, 1, 20)
    )
    assert result["total"] == 1
    assert result["items"][0]["korisnik"]["korisnik_id"] == 1


def test_responses_draft_not_included():
    """Nacrti se nikad ne pojavljuju - get_final_answers_for_predaje cita samo finalne."""
    repo = FakeSurveyRepo()
    a, q, opt = _setup_responses_survey(repo)
    k = make_korisnik(id=1, platni_broj="1")
    make_predaja(repo, a.id, korisnik_id=1, datum_predaje=datetime.datetime(2026, 1, 1))
    # Namerno NE dodajemo AnketaOdgovor - samo nacrt bi bio u drugoj tabeli i ne
    # postoji nacin da ovaj repo/servis do njega dodje.
    service, _, _ = _service(repo, korisnici=[k])
    result = service.get_responses(a.id, 1, 20, None, None, None, None, None)
    assert result["items"][0]["odgovori"] == []


def test_responses_inactive_user_historical_submission_visible():
    repo = FakeSurveyRepo()
    a, q, opt = _setup_responses_survey(repo)
    k = make_korisnik(id=1, platni_broj="1", status_zaposlenja="NEAKTIVAN")
    make_predaja(repo, a.id, korisnik_id=1, datum_predaje=datetime.datetime(2026, 1, 1))
    service, _, _ = _service(repo, korisnici=[k])
    result = service.get_responses(a.id, 1, 20, None, None, None, None, None)
    assert result["total"] == 1
