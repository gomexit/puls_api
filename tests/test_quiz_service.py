"""Servisni testovi za PULS IZAZOV (admin + zaposleni), bez baze."""

import datetime

import pytest

from app.core.config import Settings
from app.core.exceptions import (
    InvalidQuizAnswerError,
    InvalidQuizStatusTransitionError,
    QuizAlreadyPlayedError,
    QuizArchivedError,
    QuizAttemptFinishedError,
    QuizAttemptInProgressError,
    QuizAttemptNotFoundError,
    QuizCategoryAlreadyExistsError,
    QuizLockedError,
    QuizNotFoundError,
    QuizNotReadyError,
    QuizPeriodOverlapError,
    QuizQuestionAlreadyAnsweredError,
    QuizTimeExpiredError,
    ValidationBusinessError,
)
from app.models.kviz import KVIZ_STATUS_ARHIVIRAN, KVIZ_STATUS_DRAFT
from app.services.quiz_admin_service import QuizAdminService
from app.services.quiz_service import QuizService
from tests.fakes import FakeAuditService, FakeSystemNotificationService, make_korisnik
from tests.quiz_fakes import (
    FIXED_NOW,
    FakeAccessRepo,
    FakeModuleAccess,
    FakeQuizDb,
    FakeQuizRepo,
    question_payload,
    quiz_payload,
    seed_quiz,
)


class Clock:
    def __init__(self, now=FIXED_NOW):
        self.now = now

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += datetime.timedelta(seconds=seconds)


@pytest.fixture
def env():
    class Env:
        db = FakeQuizDb()
        repo = FakeQuizRepo()
        audit = FakeAuditService()
        notif = FakeSystemNotificationService()
        clock = Clock()
        access = FakeAccessRepo()
        module = FakeModuleAccess()

        def admin(self):
            return QuizAdminService(
                db=self.db,
                repository=self.repo,
                audit_service=self.audit,
                system_notification_service=self.notif,
                settings=Settings(_env_file=None),
                now_fn=self.clock,
            )

        def employee(self):
            return QuizService(
                db=self.db,
                repository=self.repo,
                module_access=self.module,
                access_repository=self.access,
                now_fn=self.clock,
            )

    return Env()


ADMIN = make_korisnik(id=1, platni_broj="admin1")


def _emp(id=10, pb="1010"):
    return make_korisnik(id=id, platni_broj=pb)


# ============================================================ kategorije
def test_category_create_update_and_duplicate(env):
    svc = env.admin()
    out = svc.create_category(ADMIN, " akcije_2 ", "Akcije", 5, True)
    assert out["sifra"] == "AKCIJE_2" and out["aktivna"] is True
    with pytest.raises(QuizCategoryAlreadyExistsError):
        svc.create_category(ADMIN, "AKCIJE_2", "X", 1, True)
    with pytest.raises(ValidationBusinessError):
        svc.create_category(ADMIN, "loš kod", "X", 1, True)
    svc.update_category(ADMIN, "AKCIJE_2", "Akcije", 5, True)  # no-op
    svc.update_category(ADMIN, "AKCIJE_2", "Akcije meseca", 5, False)
    assert [e["sifra_akcije"] for e in env.audit.entries] == [
        "ADMIN_QUIZ_CATEGORY_CREATED",
        "ADMIN_QUIZ_CATEGORY_UPDATED",
    ]
    assert [k["sifra"] for k in svc.list_categories(aktivna=False)] == ["AKCIJE_2"]


# ================================================================ kreiranje
def test_create_quiz_validates_questions(env):
    svc = env.admin()
    out = svc.create_quiz(ADMIN, quiz_payload())
    assert out["status"] == KVIZ_STATUS_DRAFT and out["broj_pitanja"] == 5
    assert all(sum(o["tacna"] for o in p["opcije"]) == 1 for p in out["pitanja"])
    assert env.audit.entries[-1]["sifra_akcije"] == "ADMIN_QUIZ_CREATED"
    assert "Pitanje" not in env.audit.entries[-1]["detalji"]

    bad_cases = [
        quiz_payload(pitanja=[question_payload(tacna=99)]),  # nijedan tacan
        quiz_payload(pitanja=[question_payload(n=1)]),  # premalo opcija
        quiz_payload(pitanja=[question_payload(kategorija="NEMA")]),
        quiz_payload(pitanja=[question_payload(slika_id=77)]),  # slika nije aktivna
        quiz_payload(pitanja=[question_payload()] * 11),
        quiz_payload(datum_do=FIXED_NOW - datetime.timedelta(days=1)),
        quiz_payload(trajanje_sekundi=5),
        quiz_payload(ciljevi=[{"tip": "SVI", "vrednost": "x"}]),
    ]
    for payload in bad_cases:
        with pytest.raises(ValidationBusinessError):
            svc.create_quiz(ADMIN, payload)

    env.repo.images_active.add(77)
    out = svc.create_quiz(ADMIN, quiz_payload(pitanja=[question_payload(slika_id=77)]))
    assert out["pitanja"][0]["slika_url"] == "/api/v1/images/77"


def test_create_dedupes_targets(env):
    out = env.admin().create_quiz(
        ADMIN,
        quiz_payload(ciljevi=[{"tip": "orgjed", "vrednost": "318"}, {"tip": "ORGJED", "vrednost": " 318 "}]),
    )
    assert out["ciljevi"] == [{"tip": "ORGJED", "vrednost": "318"}]


# ================================================================ status
def test_publish_rules_and_push(env):
    svc = env.admin()
    q = svc.create_quiz(ADMIN, quiz_payload())
    pub = svc.change_status(ADMIN, q["id"], "objavljen")
    assert pub["status"] == "OBJAVLJEN" and pub["datum_objave"] == FIXED_NOW
    assert env.notif.calls == [("enqueue_quiz_activated", (q["id"],))]
    # idempotentno
    svc.change_status(ADMIN, q["id"], "OBJAVLJEN")
    assert len(env.notif.calls) == 1

    # preklapanje
    q2 = svc.create_quiz(ADMIN, quiz_payload())
    with pytest.raises(QuizPeriodOverlapError):
        svc.change_status(ADMIN, q2["id"], "OBJAVLJEN")

    # buduci kviz: bez push-a odmah (salje worker kad pocne)
    future = quiz_payload(
        datum_od=FIXED_NOW + datetime.timedelta(days=7), datum_do=FIXED_NOW + datetime.timedelta(days=14)
    )
    q3 = svc.create_quiz(ADMIN, future)
    svc.change_status(ADMIN, q3["id"], "OBJAVLJEN")
    assert len(env.notif.calls) == 1

    with pytest.raises(InvalidQuizStatusTransitionError):
        svc.change_status(ADMIN, q3["id"], "DRAFT")
    svc.change_status(ADMIN, q3["id"], "ARHIVIRAN")
    with pytest.raises(InvalidQuizStatusTransitionError):
        svc.change_status(ADMIN, q3["id"], "OBJAVLJEN")


def test_publish_requires_questions_and_future_end(env):
    svc = env.admin()
    empty = svc.create_quiz(ADMIN, quiz_payload(n_questions=0))
    with pytest.raises(QuizNotReadyError):
        svc.change_status(ADMIN, empty["id"], "OBJAVLJEN")
    q = svc.create_quiz(ADMIN, quiz_payload())
    env.clock.now = FIXED_NOW + datetime.timedelta(days=10)
    with pytest.raises(QuizNotReadyError):
        svc.change_status(ADMIN, q["id"], "OBJAVLJEN")


def test_update_draft_replaces_questions_and_published_is_locked(env):
    svc = env.admin()
    q = svc.create_quiz(ADMIN, quiz_payload())
    out = svc.update_quiz(ADMIN, q["id"], {"pitanja": [question_payload(tekst="Novo")]})
    assert [p["tekst"] for p in out["pitanja"]] == ["Novo"]
    out = svc.update_quiz(ADMIN, q["id"], {"pitanja": [question_payload()] * 5, "naziv": "Nov naziv"})
    svc.change_status(ADMIN, q["id"], "OBJAVLJEN")

    for locked in ({"pitanja": []}, {"ciljevi": []}, {"trajanje_sekundi": 60}, {"datum_od": FIXED_NOW}):
        with pytest.raises(QuizLockedError):
            svc.update_quiz(ADMIN, q["id"], locked)
    with pytest.raises(QuizLockedError):
        svc.update_quiz(ADMIN, q["id"], {"datum_do": FIXED_NOW + datetime.timedelta(days=1)})

    novi_do = FIXED_NOW + datetime.timedelta(days=8)
    out = svc.update_quiz(ADMIN, q["id"], {"naziv": "Drugi naziv", "opis": None, "datum_do": novi_do})
    assert out["naziv"] == "Drugi naziv" and out["opis"] is None and out["datum_do"] == novi_do

    svc.change_status(ADMIN, q["id"], "ARHIVIRAN")
    with pytest.raises(QuizArchivedError):
        svc.update_quiz(ADMIN, q["id"], {"naziv": "x"})


# ================================================================ zaposleni
def _correct(env, kviz_id):
    return {int(p.id): next(int(o.id) for o in env.repo.options[int(p.id)] if o.tacna == "D")
            for p in env.repo.get_questions(kviz_id)}


def _wrong(env, pitanje_id):
    return next(int(o.id) for o in env.repo.options[pitanje_id] if o.tacna == "N")


def test_current_and_visibility(env):
    svc = env.employee()
    assert svc.current(_emp()) == {"kviz": None, "pokusaj": None}
    kviz = seed_quiz(env.repo, targets=[("ORGJED", "318"), ("PLATNI_BROJ", "2020")])
    assert svc.current(_emp())["kviz"] is None  # nije ciljan
    assert svc.current(_emp(id=20, pb="2020"))["kviz"]["id"] == kviz.id
    env.access.orgjed[10] = {"318"}
    state = svc.current(_emp())
    assert state["kviz"]["broj_pitanja"] == 5 and state["pokusaj"] is None
    assert svc.badge_count(_emp()) == 1
    env.module.enabled = False
    assert svc.current(_emp())["kviz"] is None
    with pytest.raises(QuizNotFoundError):
        svc.start(_emp(), int(kviz.id))


def test_full_play_flow_never_leaks_correct_answer(env):
    svc = env.employee()
    kviz = seed_quiz(env.repo)
    env.repo.primary[10] = "318"
    play = svc.start(_emp(), int(kviz.id))
    assert play["preostalo_sekundi"] == 120 and play["broj_pitanja"] == 5
    for p in play["pitanja"]:
        assert p["odgovor"] is None
        assert all(set(o) == {"id", "tekst"} for o in p["opcije"])

    correct = _correct(env, int(kviz.id))
    pitanja = [p["id"] for p in play["pitanja"]]
    r = svc.answer(_emp(), play["pokusaj_id"], pitanja[0], correct[pitanja[0]])
    assert r["tacan"] is True and r["tacna_opcija_id"] == correct[pitanja[0]] and r["objasnjenje"]
    with pytest.raises(QuizQuestionAlreadyAnsweredError):
        svc.answer(_emp(), play["pokusaj_id"], pitanja[0], correct[pitanja[0]])
    with pytest.raises(InvalidQuizAnswerError):
        svc.answer(_emp(), play["pokusaj_id"], pitanja[1], correct[pitanja[0]])  # opcija drugog pitanja
    with pytest.raises(QuizAttemptNotFoundError):
        svc.answer(_emp(id=99, pb="9"), play["pokusaj_id"], pitanja[1], correct[pitanja[1]])

    # nastavak vraca isti pokusaj sa vec datim odgovorom
    env.clock.advance(30)
    resumed = svc.start(_emp(), int(kviz.id))
    assert resumed["pokusaj_id"] == play["pokusaj_id"] and resumed["preostalo_sekundi"] == 90
    assert resumed["pitanja"][0]["odgovor"]["tacan"] is True
    with pytest.raises(QuizAttemptInProgressError):
        svc.result(_emp(), play["pokusaj_id"])

    svc.answer(_emp(), play["pokusaj_id"], pitanja[1], _wrong(env, pitanja[1]))
    for pid in pitanja[2:-1]:
        svc.answer(_emp(), play["pokusaj_id"], pid, correct[pid])
    env.clock.advance(10)
    last = svc.answer(_emp(), play["pokusaj_id"], pitanja[-1], correct[pitanja[-1]])
    assert last["zavrsen"] is True and last["broj_tacnih"] == 4

    result = svc.result(_emp(), play["pokusaj_id"])
    assert result["broj_tacnih"] == 4 and result["trajanje_ms"] == 40_000
    assert result["prosek_orgjed"] is None  # manje od 3 ucesnika
    assert result["pitanja"][1]["tacan"] is False and result["pitanja"][1]["moja_opcija_id"] is not None
    with pytest.raises(QuizAttemptFinishedError):
        svc.answer(_emp(), play["pokusaj_id"], pitanja[0], correct[pitanja[0]])
    with pytest.raises(QuizAlreadyPlayedError):
        svc.start(_emp(), int(kviz.id))
    assert svc.badge_count(_emp()) == 0


def test_timeout_finalizes_and_counts_unanswered_as_wrong(env):
    svc = env.employee()
    kviz = seed_quiz(env.repo)
    play = svc.start(_emp(), int(kviz.id))
    correct = _correct(env, int(kviz.id))
    first = play["pitanja"][0]["id"]
    svc.answer(_emp(), play["pokusaj_id"], first, correct[first])
    env.clock.advance(124)  # u okviru tolerancije od 5 s
    second = play["pitanja"][1]["id"]
    svc.answer(_emp(), play["pokusaj_id"], second, correct[second])
    env.clock.advance(10)
    with pytest.raises(QuizTimeExpiredError):
        svc.answer(_emp(), play["pokusaj_id"], play["pitanja"][2]["id"], correct[play["pitanja"][2]["id"]])
    result = svc.result(_emp(), play["pokusaj_id"])
    assert result["status"] == "ZAVRSEN" and result["broj_tacnih"] == 2 and result["trajanje_ms"] == 120_000
    with pytest.raises(QuizAlreadyPlayedError):
        svc.start(_emp(), int(kviz.id))


def test_finish_early_and_orgjed_average_from_three(env):
    svc = env.employee()
    kviz = seed_quiz(env.repo)
    correct = _correct(env, int(kviz.id))
    for i, score in enumerate((5, 3, 1)):
        emp = _emp(id=100 + i, pb=f"P{i}")
        env.repo.primary[emp.id] = "318"
        play = svc.start(emp, int(kviz.id))
        for p in play["pitanja"][:score]:
            svc.answer(emp, play["pokusaj_id"], p["id"], correct[p["id"]])
        res = svc.finish(emp, play["pokusaj_id"])
        assert res["broj_tacnih"] == score
    assert res["prosek_orgjed"] == 3.0 and res["broj_ucesnika_orgjed"] == 3
    assert svc.finish(emp, play["pokusaj_id"])["broj_tacnih"] == 1  # idempotentno

    results = env.admin().results(int(kviz.id))
    assert results["broj_zavrsenih"] == 3 and results["prosek_tacnih"] == 3.0
    assert results["po_orgjed"] == [{"orgjed_sifra": "318", "broj_zavrsenih": 3, "prosek_tacnih": 3.0}]
    assert results["po_pitanju"][0]["procenat_tacnih"] == 100.0
    assert results["po_pitanju"][4]["broj_odgovora"] == 1


def test_start_rejects_closed_draft_or_archived(env):
    svc = env.employee()
    draft = seed_quiz(env.repo, status=KVIZ_STATUS_DRAFT)
    arch = seed_quiz(env.repo, status=KVIZ_STATUS_ARHIVIRAN, naziv="A")
    future = seed_quiz(env.repo, naziv="B", datum_od=FIXED_NOW + datetime.timedelta(days=9),
                       datum_do=FIXED_NOW + datetime.timedelta(days=10))
    for k in (draft, arch, future):
        with pytest.raises(QuizNotFoundError):
            svc.start(_emp(), int(k.id))
    with pytest.raises(QuizNotFoundError):
        svc.start(_emp(), 123456)
