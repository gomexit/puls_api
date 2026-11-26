"""Fake-ovi za modul PULS IZAZOV (bez Oracle konekcije)."""

import datetime
import itertools

from app.models.kviz import (
    KVIZ_STATUS_DRAFT,
    KVIZ_STATUS_OBJAVLJEN,
    POKUSAJ_ZAVRSEN,
    Kviz,
    KvizCilj,
    KvizKategorija,
    KvizOpcija,
    KvizPitanje,
)

_ids = itertools.count(5000)
FIXED_NOW = datetime.datetime(2026, 12, 1, 10, 0, 0)


class FakeQuizDb:
    def __init__(self):
        self.committed = 0
        self.rolled_back = 0
        self.flushed = 0

    def commit(self):
        self.committed += 1

    def rollback(self):
        self.rolled_back += 1

    def flush(self):
        self.flushed += 1


def make_kategorija(sifra="OPSTE", naziv="Opšte", aktivna="D", redosled=10) -> KvizKategorija:
    return KvizKategorija(
        sifra=sifra,
        naziv=naziv,
        redosled=redosled,
        aktivna=aktivna,
        kreirao_platni_broj="SISTEM",
        izmenio_platni_broj="SISTEM",
        datum_kreiranja=FIXED_NOW,
        datum_izmene=FIXED_NOW,
    )


def question_payload(tekst="Koliko prodavnica ima Gomex?", tacna=1, n=4, kategorija="OPSTE", slika_id=None):
    return {
        "tekst": tekst,
        "kategorija_sifra": kategorija,
        "slika_id": slika_id,
        "objasnjenje": "Zato što je tako.",
        "opcije": [{"tekst": f"Odgovor {i}", "tacna": i == tacna} for i in range(n)],
    }


def quiz_payload(n_questions=5, **overrides) -> dict:
    data = {
        "naziv": "Puls izazov 1",
        "opis": "Prvi nedeljni kviz",
        "datum_od": FIXED_NOW - datetime.timedelta(hours=1),
        "datum_do": FIXED_NOW + datetime.timedelta(days=6),
        "trajanje_sekundi": 120,
        "ciljevi": [],
        "pitanja": [question_payload(tekst=f"Pitanje {i}") for i in range(1, n_questions + 1)],
    }
    data.update(overrides)
    return data


class FakeQuizRepo:
    def __init__(self):
        self.categories: dict[str, KvizKategorija] = {}
        self.images_active: set[int] = set()
        self.quizzes: dict[int, Kviz] = {}
        self.targets: dict[int, list[KvizCilj]] = {}
        self.questions: dict[int, list[KvizPitanje]] = {}
        self.options: dict[int, list[KvizOpcija]] = {}
        self.attempts: list = []
        self.answers: list = []
        self.primary: dict[int, str] = {}
        for k in ("OPSTE", "ASORTIMAN"):
            self.categories[k] = make_kategorija(sifra=k, naziv=k.title())

    # --- kategorije ---
    def list_categories(self, aktivna=None):
        items = [k for k in self.categories.values() if aktivna is None or k.aktivna == aktivna]
        return sorted(items, key=lambda k: (k.redosled, k.sifra))

    def get_category(self, sifra):
        return self.categories.get(sifra)

    get_category_for_update = get_category

    def add_category(self, k):
        self.categories[k.sifra] = k
        return k

    def active_category_codes(self, codes):
        return {c for c in codes if c in self.categories and self.categories[c].aktivna == "D"}

    def category_names(self, codes):
        return {c: self.categories[c].naziv for c in codes if c in self.categories}

    def active_image_ids(self, ids):
        return {i for i in ids if i in self.images_active}

    # --- kvizovi ---
    def list_admin(self, status, search, page, page_size):
        items = [k for k in self.quizzes.values() if status is None or k.status == status]
        if search:
            items = [k for k in items if search.lower() in k.naziv.lower()]
        items.sort(key=lambda k: (k.datum_od, int(k.id)), reverse=True)
        start = (page - 1) * page_size
        return items[start : start + page_size], len(items)

    def question_counts(self, ids):
        return {i: len(self.questions.get(i, [])) for i in ids}

    def get(self, kviz_id):
        return self.quizzes.get(kviz_id)

    get_for_update = get

    def add(self, kviz):
        if kviz.id is None:
            kviz.id = next(_ids)
        self.quizzes[int(kviz.id)] = kviz
        return kviz

    def find_overlapping_published(self, od, do, exclude_id):
        return [
            k
            for k in self.quizzes.values()
            if k.status == KVIZ_STATUS_OBJAVLJEN and k.datum_od < do and k.datum_do > od and k.id != exclude_id
        ]

    def find_open_published(self, now):
        items = [k for k in self.quizzes.values() if k.is_open(now)]
        return sorted(items, key=lambda k: (k.datum_od, int(k.id)), reverse=True)

    def get_targets(self, kviz_id):
        return list(self.targets.get(kviz_id, []))

    def get_questions(self, kviz_id):
        return sorted(self.questions.get(kviz_id, []), key=lambda p: p.redosled)

    def get_options(self, pitanje_ids):
        out = []
        for pid in pitanje_ids:
            out.extend(self.options.get(pid, []))
        return out

    def replace_targets(self, kviz_id, ciljevi):
        self.targets[kviz_id] = [
            KvizCilj(id=next(_ids), kviz_id=kviz_id, tip_cilja=t, vrednost=v) for t, v in ciljevi
        ]

    def replace_questions(self, kviz_id, pitanja):
        for p in self.questions.get(kviz_id, []):
            self.options.pop(int(p.id), None)
        self.questions[kviz_id] = []
        for r, p in enumerate(pitanja, start=1):
            q = KvizPitanje(
                id=next(_ids),
                kviz_id=kviz_id,
                redosled=r,
                tekst=p["tekst"],
                kategorija_sifra=p["kategorija_sifra"],
                slika_id=p["slika_id"],
                objasnjenje=p["objasnjenje"],
            )
            self.questions[kviz_id].append(q)
            self.options[int(q.id)] = [
                KvizOpcija(id=next(_ids), pitanje_id=q.id, redosled=i, tekst=o["tekst"], tacna="D" if o["tacna"] else "N")
                for i, o in enumerate(p["opcije"], start=1)
            ]

    # --- pokusaji ---
    def primary_orgjed(self, korisnik_id):
        return self.primary.get(korisnik_id)

    def get_attempt(self, kviz_id, korisnik_id):
        return next((p for p in self.attempts if p.kviz_id == kviz_id and p.korisnik_id == korisnik_id), None)

    get_attempt_for_update = get_attempt

    def get_attempt_by_id_for_update(self, pokusaj_id):
        return next((p for p in self.attempts if int(p.id) == pokusaj_id), None)

    def add_attempt(self, p):
        p.id = next(_ids)
        self.attempts.append(p)
        return p

    def get_answers(self, pokusaj_id):
        return [o for o in self.answers if o.pokusaj_id == pokusaj_id]

    def add_answer(self, o):
        o.id = next(_ids)
        self.answers.append(o)
        return o

    def orgjed_average(self, kviz_id, orgjed):
        done = [
            p for p in self.attempts
            if p.kviz_id == kviz_id and p.orgjed_sifra == orgjed and p.status == POKUSAJ_ZAVRSEN
        ]
        if not done:
            return 0, None
        return len(done), sum(int(p.broj_tacnih) for p in done) / len(done)

    def attempt_totals(self, kviz_id):
        mine = [p for p in self.attempts if p.kviz_id == kviz_id]
        done = [p for p in mine if p.status == POKUSAJ_ZAVRSEN]
        return {
            "ukupno": len(mine),
            "zavrseno": len(done),
            "prosek_tacnih": (sum(p.broj_tacnih for p in done) / len(done)) if done else None,
            "prosek_trajanja_ms": (sum(p.trajanje_ms for p in done) / len(done)) if done else None,
        }

    def orgjed_stats(self, kviz_id):
        groups: dict = {}
        for p in self.attempts:
            if p.kviz_id == kviz_id and p.status == POKUSAJ_ZAVRSEN:
                groups.setdefault(p.orgjed_sifra, []).append(p.broj_tacnih)
        return [(o, len(v), sum(v) / len(v)) for o, v in sorted(groups.items(), key=lambda x: str(x[0]))]

    def question_stats(self, kviz_id):
        qids = {int(p.id) for p in self.questions.get(kviz_id, [])}
        out: dict = {}
        for o in self.answers:
            if int(o.pitanje_id) in qids:
                c, t = out.get(int(o.pitanje_id), (0, 0))
                out[int(o.pitanje_id)] = (c + 1, t + (1 if o.tacan == "D" else 0))
        return out


def seed_quiz(repo: FakeQuizRepo, status=KVIZ_STATUS_OBJAVLJEN, n_questions=5, targets=(), **overrides) -> Kviz:
    data = quiz_payload(n_questions)
    kviz = Kviz(
        id=next(_ids),
        naziv=overrides.pop("naziv", data["naziv"]),
        opis=data["opis"],
        datum_od=overrides.pop("datum_od", data["datum_od"]),
        datum_do=overrides.pop("datum_do", data["datum_do"]),
        trajanje_sekundi=overrides.pop("trajanje_sekundi", 120),
        status=status,
        kreirao_platni_broj="admin1",
        izmenio_platni_broj="admin1",
        datum_objave=FIXED_NOW if status != KVIZ_STATUS_DRAFT else None,
        datum_kreiranja=FIXED_NOW,
        datum_izmene=FIXED_NOW,
    )
    repo.add(kviz)
    repo.replace_targets(int(kviz.id), list(targets))
    repo.replace_questions(int(kviz.id), data["pitanja"])
    return kviz


class FakeModuleAccess:
    def __init__(self, enabled=True):
        self.enabled = enabled

    def is_enabled(self, korisnik, kod):
        return self.enabled and kod == "KVIZ"

    def enabled_modules(self, korisnik):
        return {"POGODNOSTI": False, "PITAJ_HR": False, "KVIZ": self.enabled, "IGRA": False, "ZAHVALNICE": False}


class FakeAccessRepo:
    def __init__(self, orgjed=None):
        self.orgjed = orgjed or {}

    def active_orgjed_codes(self, korisnik_id):
        return frozenset(self.orgjed.get(korisnik_id, set()))
