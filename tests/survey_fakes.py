"""In-memory fake repozitorijumi za servisne testove modula ANKETE (bez prave baze)."""

import datetime
import itertools

from app.models.anketa import Anketa, AnketaTip
from app.models.anketa_predaja import AnketaOdgovor, AnketaOdgovorOpcija, AnketaPredaja
from app.models.anketa_struktura import (
    AnketaCilj,
    AnketaOpcija,
    AnketaPitanje,
    AnketaSekcija,
    AnketaUslovVrednost,
)
from app.models.anketa_ucesce import AnketaNacrtOdgovor, AnketaNacrtOpcija, AnketaUcesce

_ids = itertools.count(1)


def _next_id() -> int:
    return next(_ids)


class FakeSurveyDb:
    def __init__(self):
        self.committed = 0
        self.rolled_back = 0
        self.flushed = 0

    def commit(self) -> None:
        self.committed += 1

    def rollback(self) -> None:
        self.rolled_back += 1

    def flush(self) -> None:
        self.flushed += 1


class FakeTargetingRepo:
    def __init__(self, all_ids=None, by_orgjed=None, by_platni=None):
        self._all = set(all_ids or [])
        self._by_orgjed = by_orgjed or {}
        self._by_platni = by_platni or {}

    def all_active_user_ids(self):
        return set(self._all)

    def user_ids_by_orgjed(self, orgjed):
        return set(self._by_orgjed.get(orgjed, set()))

    def user_id_by_platni_broj(self, platni):
        return self._by_platni.get(platni)


class FakeAutomationRepo:
    """Fake OnboardingAutomationRepository - koristi se u SurveyAdminService testovima
    da simulira prisustvo/odsustvo PULS_ANKETA_AUTOMATIKA reda za anketu."""

    def __init__(self):
        self.by_survey: dict[int, object] = {}

    def get_by_survey_id(self, anketa_id):
        return self.by_survey.get(anketa_id)

    def mark_automatska(self, anketa_id: int) -> None:
        self.by_survey[anketa_id] = object()


class FakeSurveyRepo:
    def __init__(self):
        self.types: dict[str, AnketaTip] = {}
        self.surveys: dict[int, Anketa] = {}
        self.sections: list[AnketaSekcija] = []
        self.questions: list[AnketaPitanje] = []
        self.options: list[AnketaOpcija] = []
        self.uslov_values: list[AnketaUslovVrednost] = []
        self.targets: list[AnketaCilj] = []
        self.ucesca: list[AnketaUcesce] = []
        self.draft_answers: list[AnketaNacrtOdgovor] = []
        self.draft_options: list[AnketaNacrtOpcija] = []
        self.submissions: list[AnketaPredaja] = []
        self.answers: list[AnketaOdgovor] = []
        self.answer_options: list[AnketaOdgovorOpcija] = []

    # tipovi
    def get_type(self, sifra):
        return self.types.get(sifra)

    def list_types(self):
        return sorted(self.types.values(), key=lambda t: t.sifra)

    def add_type(self, tip):
        self.types[tip.sifra] = tip
        return tip

    # anketa
    def get_survey(self, sid):
        return self.surveys.get(sid)

    def add_survey(self, a):
        a.id = _next_id()
        self.surveys[a.id] = a
        return a

    def list_surveys(self, status, tip, datum_od, datum_do, page, page_size):
        items = list(self.surveys.values())
        if status:
            items = [a for a in items if a.status == status]
        if tip:
            items = [a for a in items if a.tip_sifra == tip]
        total = len(items)
        start = (page - 1) * page_size
        return items[start : start + page_size], total

    # struktura citanje
    def get_sections(self, aid):
        return sorted([s for s in self.sections if s.anketa_id == aid], key=lambda s: s.redosled)

    def get_questions_for_survey(self, aid):
        sec = {s.id: s for s in self.sections if s.anketa_id == aid}
        qs = [q for q in self.questions if q.sekcija_id in sec]
        return sorted(qs, key=lambda q: (sec[q.sekcija_id].redosled, q.redosled))

    def get_options_for_survey(self, aid):
        qids = {q.id for q in self.get_questions_for_survey(aid)}
        return sorted(
            [o for o in self.options if o.pitanje_id in qids],
            key=lambda o: (o.pitanje_id, o.redosled),
        )

    def get_uslov_values_for_survey(self, aid):
        qids = {q.id for q in self.get_questions_for_survey(aid)}
        return sorted(
            [u for u in self.uslov_values if u.pitanje_id in qids],
            key=lambda u: (u.pitanje_id, u.redosled),
        )

    def get_targets(self, aid):
        return [c for c in self.targets if c.anketa_id == aid]

    # struktura pisanje
    def add_section(self, s):
        s.id = _next_id()
        self.sections.append(s)
        return s

    def add_question(self, q):
        q.id = _next_id()
        self.questions.append(q)
        return q

    def add_option(self, o):
        o.id = _next_id()
        self.options.append(o)
        return o

    def add_uslov_value(self, u):
        u.id = _next_id()
        self.uslov_values.append(u)
        return u

    def add_target(self, c):
        c.id = _next_id()
        self.targets.append(c)
        return c

    def delete_structure(self, aid):
        sec_ids = {s.id for s in self.sections if s.anketa_id == aid}
        q_ids = {q.id for q in self.questions if q.sekcija_id in sec_ids}
        self.uslov_values = [u for u in self.uslov_values if u.pitanje_id not in q_ids]
        self.options = [o for o in self.options if o.pitanje_id not in q_ids]
        self.questions = [q for q in self.questions if q.sekcija_id not in sec_ids]
        self.sections = [s for s in self.sections if s.anketa_id != aid]
        self.targets = [c for c in self.targets if c.anketa_id != aid]

    # ucesce
    def get_ucesce(self, aid, kid):
        return next(
            (u for u in self.ucesca if u.anketa_id == aid and u.korisnik_id == kid), None
        )

    def get_ucesce_for_update(self, aid, kid):
        return self.get_ucesce(aid, kid)

    def add_ucesce(self, u):
        u.id = _next_id()
        self.ucesca.append(u)
        return u

    def existing_participant_ids(self, aid):
        return {u.korisnik_id for u in self.ucesca if u.anketa_id == aid}

    def list_user_surveys(self, kid):
        result = []
        for u in self.ucesca:
            if u.korisnik_id != kid:
                continue
            a = self.surveys.get(u.anketa_id)
            if a is not None and a.status != "ARCHIVED":
                result.append((a, u))
        return result

    def count_participants(self, aid):
        return sum(1 for u in self.ucesca if u.anketa_id == aid)

    def count_submitted(self, aid):
        return sum(1 for u in self.ucesca if u.anketa_id == aid and u.status == "SUBMITTED")

    def count_questions(self, aid):
        return len(self.get_questions_for_survey(aid))

    # nacrt
    def get_draft_answers(self, aid, kid):
        return [d for d in self.draft_answers if d.anketa_id == aid and d.korisnik_id == kid]

    def get_draft_options(self, ids):
        return [o for o in self.draft_options if o.nacrt_odgovor_id in set(ids)]

    def delete_draft(self, aid, kid):
        keep_ids = {d.id for d in self.draft_answers if d.anketa_id == aid and d.korisnik_id == kid}
        self.draft_options = [o for o in self.draft_options if o.nacrt_odgovor_id not in keep_ids]
        self.draft_answers = [
            d for d in self.draft_answers if not (d.anketa_id == aid and d.korisnik_id == kid)
        ]

    def add_draft_answer(self, d):
        d.id = _next_id()
        self.draft_answers.append(d)
        return d

    def add_draft_option(self, o):
        o.id = _next_id()
        self.draft_options.append(o)
        return o

    # predaja
    def add_submission(self, p):
        p.id = _next_id()
        self.submissions.append(p)
        return p

    def add_answer(self, a):
        a.id = _next_id()
        self.answers.append(a)
        return a

    def add_answer_option(self, o):
        o.id = _next_id()
        self.answer_options.append(o)
        return o

    def get_user_submission(self, aid, kid):
        return next(
            (p for p in self.submissions if p.anketa_id == aid and p.korisnik_id == kid), None
        )

    def get_final_answers(self, pid):
        return [a for a in self.answers if a.predaja_id == pid]

    def get_final_answer_options(self, ids):
        return [o for o in self.answer_options if o.odgovor_id in set(ids)]


# --------------------------------------------------------------------- fabrike
def make_tip(sifra="PULS", naziv="Pulse anketa", aktivan="D") -> AnketaTip:
    return AnketaTip(sifra=sifra, naziv=naziv, aktivan=aktivan, datum_kreiranja=datetime.datetime.now())


def make_anketa(repo: FakeSurveyRepo, **overrides) -> Anketa:
    now = datetime.datetime.now()
    defaults = dict(
        tip_sifra="PULS",
        naziv="Test anketa",
        opis=None,
        anonimna="N",
        status="ACTIVE",
        datum_pocetka=now - datetime.timedelta(days=1),
        datum_zavrsetka=now + datetime.timedelta(days=6),
        datum_kreiranja=now,
    )
    defaults.update(overrides)
    a = Anketa(**defaults)
    return repo.add_survey(a)


def add_sekcija(repo, anketa_id, redosled=1, naziv="Sekcija"):
    return repo.add_section(
        AnketaSekcija(anketa_id=anketa_id, naziv=naziv, redosled=redosled, datum_kreiranja=datetime.datetime.now())
    )


def add_pitanje(repo, sekcija_id, tip, redosled=1, obavezno="N", uslov_pitanje_id=None, uslov_operator=None, tekst="P"):
    return repo.add_question(
        AnketaPitanje(
            sekcija_id=sekcija_id,
            tekst=tekst,
            tip_pitanja=tip,
            obavezno=obavezno,
            redosled=redosled,
            uslov_pitanje_id=uslov_pitanje_id,
            uslov_operator=uslov_operator,
            datum_kreiranja=datetime.datetime.now(),
        )
    )


def add_opcija(repo, pitanje_id, redosled=1, tekst="O"):
    return repo.add_option(
        AnketaOpcija(pitanje_id=pitanje_id, tekst=tekst, redosled=redosled, datum_kreiranja=datetime.datetime.now())
    )


def add_uslov(repo, pitanje_id, vrednost, redosled=1):
    return repo.add_uslov_value(
        AnketaUslovVrednost(pitanje_id=pitanje_id, vrednost=vrednost, redosled=redosled)
    )


def add_cilj(repo, anketa_id, tip_cilja, vrednost=None):
    return repo.add_target(
        AnketaCilj(anketa_id=anketa_id, tip_cilja=tip_cilja, vrednost=vrednost, datum_kreiranja=datetime.datetime.now())
    )


def add_ucesce(
    repo,
    anketa_id,
    korisnik_id,
    status="NOT_STARTED",
    automatika_id=None,
    datum_dostupnosti=None,
    datum_isteka=None,
    datum_zaposlenja_snapshot=None,
):
    return repo.add_ucesce(
        AnketaUcesce(
            anketa_id=anketa_id,
            korisnik_id=korisnik_id,
            status=status,
            datum_kreiranja=datetime.datetime.now(),
            automatika_id=automatika_id,
            datum_dostupnosti=datum_dostupnosti,
            datum_isteka=datum_isteka,
            datum_zaposlenja_snapshot=datum_zaposlenja_snapshot,
        )
    )