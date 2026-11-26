"""PITAJ HR: servis zaposlenog, admin (odgovor, dopuna, zatvaranje, kategorije, cesta pitanja),
worker (push bez teksta odgovora), HTTP, SQL 014 i Oracle upiti."""

import datetime
import itertools
import pathlib

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.dialects import oracle

from app.api.v1 import admin_hr_questions as admin_mod
from app.api.v1 import hr_questions as hr_mod
from app.core.exceptions import (
    HrCategoryAlreadyExistsError,
    HrCategoryNotFoundError,
    HrFaqNotFoundError,
    HrQuestionAnswerNotAllowedError,
    HrQuestionCategoryInvalidError,
    HrQuestionDailyLimitError,
    HrQuestionFollowUpNotAllowedError,
    HrQuestionInvalidStatusError,
    HrQuestionNotAvailableError,
    HrQuestionNotFoundError,
    ValidationBusinessError,
)
from app.dependencies.auth import get_current_ready_user
from app.dependencies.portal_auth import require_portal_admin_or_hr
from app.main import app
from app.models.hr_pitanje import (
    STATUS_ODGOVORENO,
    STATUS_POSLATO,
    STATUS_ZATVORENO,
    HrKategorija,
)
from app.models.sistemski_dogadjaj import (
    DOGADJAJ_TIP_HR_QUESTION_ANSWERED,
    DOGADJAJ_TIPOVI,
    DOGADJAJ_TIPOVI_NOVIH_MODULA,
)
from app.repositories.hr_question_repository import HrQuestionRepository
from app.services import system_notification_service as sns
from app.services.hr_question_admin_service import HrQuestionAdminService
from app.services.hr_question_service import HrQuestionService, preview
from tests.fakes import make_korisnik

NOW = datetime.datetime(2026, 11, 26, 10, 0, 0)
SQL_014 = pathlib.Path(__file__).resolve().parents[1] / "sql" / "014_pitaj_hr_module.sql"
_ids = itertools.count(7000)


# ================================================================ fake-ovi
class FakeDb:
    def __init__(self):
        self.committed = 0
        self.rolled_back = 0

    def commit(self):
        self.committed += 1

    def rollback(self):
        self.rolled_back += 1

    def flush(self):
        pass


class FakeModules:
    def __init__(self, enabled=True):
        self.enabled = enabled

    def is_enabled(self, korisnik, kod):
        return self.enabled and kod == "PITAJ_HR"


class FakeEvents:
    def __init__(self):
        self.events = []

    def enqueue_if_absent(self, kljuc, tip, resurs_id, vrednost, now):
        self.events.append((kljuc, tip, resurs_id, vrednost))
        return True


class FakeAudit:
    def __init__(self):
        self.entries = []

    def log(self, akcija, **kw):
        self.entries.append((akcija, kw))


def _kat(sifra, naziv, redosled, aktivna="D"):
    return HrKategorija(sifra=sifra, naziv=naziv, redosled=redosled, aktivna=aktivna, kreirao_platni_broj="SISTEM",
                        izmenio_platni_broj="SISTEM", datum_kreiranja=NOW, datum_izmene=NOW)


class FakeRepo:
    def __init__(self, users):
        self.users = {int(u.id): u for u in users}
        self.cats = {k.sifra: k for k in (_kat("ODMOR", "Godišnji odmor", 10), _kat("ZARADA", "Zarada", 20),
                                          _kat("STARO", "Staro", 99, aktivna="N"))}
        self.questions, self.msgs, self.faqs = [], [], []

    def users_by_ids(self, ids):
        return {i: self.users[i] for i in ids if i in self.users}

    def primary_orgjed(self, kid):
        return "318" if kid == 1 else None

    def orgjed_names(self, sifre):
        return {s: f"Prodavnica {s}" for s in sifre}

    def list_categories(self, aktivna=None):
        return sorted((k for k in self.cats.values() if aktivna is None or k.aktivna == aktivna),
                      key=lambda k: (k.redosled, k.sifra))

    def get_category(self, sifra):
        return self.cats.get(sifra)

    get_category_for_update = get_category

    def add_category(self, k):
        self.cats[k.sifra] = k
        return k

    def category_names(self):
        return {k.sifra: k.naziv for k in self.cats.values()}

    def add_question(self, p):
        p.id = next(_ids)
        self.questions.append(p)
        return p

    def add_message(self, m):
        m.id = next(_ids)
        self.msgs.append(m)
        return m

    def get_question(self, qid):
        return next((p for p in self.questions if int(p.id) == qid), None)

    get_question_for_update = get_question

    def count_asked_since(self, kid, since):
        return sum(1 for p in self.questions if p.korisnik_id == kid and p.datum_kreiranja >= since)

    def mine(self, kid, offset, limit):
        rows = sorted((p for p in self.questions if p.korisnik_id == kid), key=lambda p: (p.datum_izmene, p.id),
                      reverse=True)
        return rows[offset : offset + limit]

    def unread_count(self, kid):
        return sum(1 for p in self.questions if p.korisnik_id == kid and p.procitano == "N")

    def messages(self, qid):
        return [m for m in self.msgs if m.pitanje_id == qid]

    def first_messages(self, ids):
        out = {}
        for m in self.msgs:
            out.setdefault(int(m.pitanje_id), m)
        return {i: out[i] for i in ids if i in out}

    def admin_list(self, status, kategorija, offset, limit):
        rows = [p for p in self.questions if (status is None or p.status == status)
                and (kategorija is None or p.kategorija_sifra == kategorija)]
        rows.sort(key=lambda p: (p.datum_izmene, p.id), reverse=status != STATUS_POSLATO)
        return len(rows), rows[offset : offset + limit]

    def list_faq(self, aktivno, kategorija):
        return [f for f in self.faqs if (aktivno is None or f.aktivno == aktivno)
                and (kategorija is None or f.kategorija_sifra == kategorija)]

    def get_faq_for_update(self, fid):
        return next((f for f in self.faqs if int(f.id) == fid), None)

    def add_faq(self, f):
        f.id = next(_ids)
        self.faqs.append(f)
        return f


class Clock:
    def __init__(self, now=NOW):
        self.now = now

    def __call__(self):
        return self.now


def _setup(enabled=True):
    ana = make_korisnik(id=1, ime="Ana", prezime="Petrović", platni_broj="111")
    marko = make_korisnik(id=2, ime="Marko", prezime="Jovanović", platni_broj="222")
    hr = make_korisnik(id=9, ime="Jelena", prezime="HR", platni_broj="999")
    repo = FakeRepo([ana, marko, hr])
    clock, events, audit = Clock(), FakeEvents(), FakeAudit()
    svc = HrQuestionService(FakeDb(), repository=repo, module_access=FakeModules(enabled), now_fn=clock)
    admin = HrQuestionAdminService(FakeDb(), repository=repo, audit_service=audit, event_repository=events,
                                   now_fn=clock)
    return svc, admin, repo, clock, events, audit, (ana, marko, hr)


# ================================================================ zaposleni
def test_ask_answer_follow_up_close_flow():
    svc, admin, repo, clock, events, audit, (ana, _marko, hr) = _setup()
    q = svc.ask(ana, "odmor", "  Koliko   dana godišnjeg\r\n\r\n\r\nmi je ostalo?  ")
    assert q["status"] == STATUS_POSLATO and q["kategorija_naziv"] == "Godišnji odmor"
    assert q["poruke"] == [{"autor": "ZAPOSLENI", "tekst": "Koliko dana godišnjeg\n\nmi je ostalo?",
                            "datum_kreiranja": NOW}]
    assert q["mogu_dopuniti"] is False and repo.questions[0].orgjed == "318"
    with pytest.raises(HrQuestionFollowUpNotAllowedError):
        svc.follow_up(ana, q["id"], "Još nešto")

    clock.now += datetime.timedelta(hours=1)
    a = admin.answer(hr, q["id"], "Ostalo vam je 12 dana.")
    assert a["status"] == STATUS_ODGOVORENO and a["poruke"][-1]["autor_ime"] == "Jelena HR"
    assert events.events[0][1:3] == (DOGADJAJ_TIP_HR_QUESTION_ANSWERED, q["id"])
    assert svc.badge_count(ana) == 1
    lst = svc.mine(ana, 1, 20)
    assert lst["items"][0]["nov_odgovor"] is True and lst["items"][0]["pregled"].startswith("Koliko dana")
    d = svc.detail(ana, q["id"])
    assert d["mogu_dopuniti"] is True and [m["autor"] for m in d["poruke"]] == ["ZAPOSLENI", "HR"]
    assert "autor_ime" not in d["poruke"][1] and "Jelena" not in str(d)  # ime HR-ovca se ne vraca
    assert svc.badge_count(ana) == 0
    with pytest.raises(HrQuestionAnswerNotAllowedError):
        admin.answer(hr, q["id"], "Duplo")

    f = svc.follow_up(ana, q["id"], "A za sledeću godinu?")
    assert f["status"] == STATUS_POSLATO and f["mogu_dopuniti"] is False
    last = admin.answer(hr, q["id"], "Novih 20 dana od januara.")
    assert last["status"] == STATUS_ZATVORENO and len(events.events) == 2
    assert events.events[0][0] != events.events[1][0]  # svaki odgovor ima svoj push
    with pytest.raises(HrQuestionFollowUpNotAllowedError):
        svc.follow_up(ana, q["id"], "Treće")
    assert [a for a, _ in audit.entries] == ["ADMIN_HR_QUESTION_ANSWERED", "ADMIN_HR_QUESTION_ANSWERED"]
    assert "20 dana" not in str(audit.entries)  # tekst se ne upisuje u audit


def test_privacy_rules_and_validation():
    svc, _admin, _, clock, _, _, (ana, marko, _hr) = _setup()
    q = svc.ask(ana, "ZARADA", "Kada stiže plata?")
    with pytest.raises(HrQuestionNotFoundError):
        svc.detail(marko, q["id"])
    with pytest.raises(HrQuestionNotFoundError):
        svc.follow_up(marko, q["id"], "x")
    assert svc.mine(marko, 1, 20)["items"] == []
    with pytest.raises(HrQuestionCategoryInvalidError):
        svc.ask(ana, "STARO", "Neaktivna")
    with pytest.raises(HrQuestionCategoryInvalidError):
        svc.ask(ana, "NEMA", "Nepostojeća")
    with pytest.raises(ValidationBusinessError):
        svc.ask(ana, "ODMOR", "x" * 1001)
    with pytest.raises(ValidationBusinessError):
        svc.ask(ana, "ODMOR", "   ")
    for i in range(4):
        svc.ask(ana, "ODMOR", f"Pitanje {i}")
    with pytest.raises(HrQuestionDailyLimitError):
        svc.ask(ana, "ODMOR", "Šesto")
    clock.now += datetime.timedelta(days=1)
    assert svc.ask(ana, "ODMOR", "Novi dan")["id"]
    assert [k["sifra"] for k in svc.categories(ana)] == ["ODMOR", "ZARADA"]
    off, *_ = _setup(enabled=False)
    for call in (lambda: off.mine(ana, 1, 20), lambda: off.ask(ana, "ODMOR", "x"), lambda: off.categories(ana),
                 lambda: off.faq(ana, None), lambda: off.detail(ana, q["id"])):
        with pytest.raises(HrQuestionNotAvailableError):
            call()


def test_admin_close_list_and_categories():
    svc, admin, _repo, clock, events, audit, (ana, marko, hr) = _setup()
    a = svc.ask(ana, "ODMOR", "Prvo")
    clock.now += datetime.timedelta(minutes=5)
    b = svc.ask(marko, "ZARADA", "Drugo")
    waiting = admin.list_questions("poslato", None, 1, 20)
    assert [i["id"] for i in waiting["items"]] == [a["id"], b["id"]]  # najduze ceka prvo
    item = waiting["items"][0]
    assert item["zaposleni"] == {"id": 1, "ime": "Ana", "prezime": "Petrović", "platni_broj": "111",
                                 "orgjed_naziv": "Prodavnica 318"}
    assert item["pregled"] == "Prvo" and "poruke" not in item
    assert admin.list_questions(None, "ZARADA", 1, 20)["total"] == 1
    closed = admin.close(hr, a["id"])
    assert closed["status"] == STATUS_ZATVORENO and events.events == []
    with pytest.raises(HrQuestionAnswerNotAllowedError):
        admin.answer(hr, a["id"], "Kasno")
    with pytest.raises(HrQuestionInvalidStatusError):
        admin.list_questions("BRISANO", None, 1, 20)
    with pytest.raises(HrQuestionNotFoundError):
        admin.get_question(123456)

    kat = admin.create_category(hr, "bolovanje", "Bolovanje", 30, True)
    assert kat["sifra"] == "BOLOVANJE" and kat["kreirao_platni_broj"] == "999"
    with pytest.raises(HrCategoryAlreadyExistsError):
        admin.create_category(hr, "BOLOVANJE", "Opet", 1, True)
    with pytest.raises(ValidationBusinessError):
        admin.create_category(hr, "loša šifra", "X", 1, True)
    upd = admin.update_category(hr, "bolovanje", "Bolovanje i povrede", 30, False)
    assert upd["aktivna"] is False and "BOLOVANJE" not in [k["sifra"] for k in svc.categories(ana)]
    with pytest.raises(HrCategoryNotFoundError):
        admin.update_category(hr, "NEMA", "X", 1, True)
    assert [x for x, _ in audit.entries] == ["ADMIN_HR_QUESTION_CLOSED", "ADMIN_HR_CATEGORY_CREATED",
                                             "ADMIN_HR_CATEGORY_UPDATED"]


def test_faq_is_public_without_names():
    svc, admin, _, _, _, _, (ana, marko, hr) = _setup()
    q = svc.ask(ana, "ODMOR", "Ana pita: da li se godišnji prenosi?")
    f = admin.create_faq(hr, "odmor", "Da li se godišnji odmor prenosi u sledeću godinu?",
                         "Da, do 30. juna.", 10, True, q["id"])
    assert f["izvor_pitanje_id"] == q["id"]
    hidden = admin.create_faq(hr, "ZARADA", "Skriveno", "Odgovor", 20, False, None)
    public = svc.faq(marko, None)
    assert [p["id"] for p in public] == [f["id"]]
    assert set(public[0]) == {"id", "kategorija_sifra", "kategorija_naziv", "pitanje", "odgovor"}
    assert svc.faq(marko, "zarada") == []
    admin.update_faq(hr, hidden["id"], "ZARADA", "Skriveno", "Odgovor", 20, True)
    assert len(svc.faq(marko, None)) == 2
    with pytest.raises(HrFaqNotFoundError):
        admin.update_faq(hr, 99999, "ZARADA", "x", "y", 0, True)
    with pytest.raises(HrQuestionCategoryInvalidError):
        admin.create_faq(hr, "NEMA", "x", "y", 0, True, None)
    with pytest.raises(HrQuestionNotFoundError):
        admin.create_faq(hr, "ODMOR", "x", "y", 0, True, 424242)
    assert len(admin.list_faq(None, None)) == 2 and len(admin.list_faq(False, None)) == 0


def test_preview():
    assert preview("kratko") == "kratko"
    long = preview("a " * 100)
    assert len(long) <= 120 and long.endswith("…")


# ================================================================ worker (push)
def test_worker_push_has_no_answer_text(monkeypatch):
    assert DOGADJAJ_TIP_HR_QUESTION_ANSWERED in DOGADJAJ_TIPOVI
    assert DOGADJAJ_TIP_HR_QUESTION_ANSWERED not in DOGADJAJ_TIPOVI_NOVIH_MODULA
    svc, admin, repo, _, _, _, (ana, _, hr) = _setup()
    q = svc.ask(ana, "ZARADA", "Kolika mi je plata?")

    class Access:
        def __init__(self, *a):
            pass

        def is_enabled(self, k, kod):
            return kod == "PITAJ_HR"

    monkeypatch.setattr(sns, "HrQuestionRepository", lambda db: repo)
    monkeypatch.setattr(sns, "ModuleAccessService", Access)
    monkeypatch.setattr(sns, "ConfigurationRepository", lambda db: None)
    monkeypatch.setattr(sns, "ModuleAccessRepository", lambda db: None)
    worker = sns.SystemNotificationService.__new__(sns.SystemNotificationService)
    worker.db = None
    event = type("E", (), {"resurs_id": q["id"], "tip_dogadjaja": DOGADJAJ_TIP_HR_QUESTION_ANSWERED})()
    assert worker._resolve_hr_answer(event) == (None, None)  # jos nema odgovora
    admin.answer(hr, q["id"], "Tajni iznos 100.000")
    recipients, content = worker._resolve_hr_answer(event)
    assert recipients == {1}
    assert content["akcija_tip"] == "HR_QUESTION" and content["resurs_id"] == q["id"] and content["akcija_url"] is None
    assert "100.000" not in str(content) and content["sadrzaj"].startswith("Kategorija: Zarada")
    repo.users[1].status_zaposlenja = "NEAKTIVAN"
    assert worker._resolve_hr_answer(event) == (None, None)


# ================================================================ HTTP
@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_http_flow(client):
    svc, admin, _, _, _, _, (ana, marko, hr) = _setup()
    app.dependency_overrides[hr_mod.get_hr_question_service] = lambda: svc
    app.dependency_overrides[admin_mod.get_hr_question_admin_service] = lambda: admin
    app.dependency_overrides[get_current_ready_user] = lambda: ana
    app.dependency_overrides[require_portal_admin_or_hr] = lambda: hr
    cats = client.get("/api/v1/hr-questions/categories").json()["items"]
    assert cats == [{"sifra": "ODMOR", "naziv": "Godišnji odmor"}, {"sifra": "ZARADA", "naziv": "Zarada"}]
    created = client.post("/api/v1/hr-questions", json={"kategorija_sifra": "ODMOR", "tekst": "Pitanje?"})
    assert created.status_code == 201 and created.json()["status"] == "POSLATO"
    qid = created.json()["id"]
    bad = client.post("/api/v1/hr-questions", json={"kategorija_sifra": "STARO", "tekst": "x"})
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "HR_QUESTION_CATEGORY_INVALID"
    ans = client.post(f"/api/v1/admin/hr-questions/{qid}/answer", json={"tekst": "Odgovor."})
    assert ans.status_code == 200 and ans.json()["status"] == "ODGOVORENO"
    again = client.post(f"/api/v1/admin/hr-questions/{qid}/answer", json={"tekst": "Opet"})
    assert again.status_code == 409 and again.json()["error"]["code"] == "HR_QUESTION_ANSWER_NOT_ALLOWED"
    mine = client.get("/api/v1/hr-questions").json()
    assert mine["items"][0]["nov_odgovor"] is True and mine["ima_jos"] is False
    assert client.get(f"/api/v1/hr-questions/{qid}").json()["mogu_dopuniti"] is True
    fu = client.post(f"/api/v1/hr-questions/{qid}/follow-up", json={"tekst": "Dopuna"})
    assert fu.status_code == 200 and fu.json()["status"] == "POSLATO"
    assert client.post(f"/api/v1/hr-questions/{qid}/follow-up", json={"tekst": "x"}).status_code == 409
    app.dependency_overrides[get_current_ready_user] = lambda: marko
    assert client.get(f"/api/v1/hr-questions/{qid}").json()["error"]["code"] == "HR_QUESTION_NOT_FOUND"
    lst = client.get("/api/v1/admin/hr-questions", params={"status": "POSLATO"}).json()
    assert lst["total"] == 1 and lst["items"][0]["zaposleni"]["platni_broj"] == "111"
    assert client.get(f"/api/v1/admin/hr-questions/{qid}").json()["poruke"][1]["autor"] == "HR"
    assert client.post(f"/api/v1/admin/hr-questions/{qid}/close").json()["status"] == "ZATVORENO"
    faq = client.post("/api/v1/admin/hr-faq", json={"kategorija_sifra": "ODMOR", "pitanje": "P?", "odgovor": "O."})
    assert faq.status_code == 201
    assert client.get("/api/v1/hr-questions/faq").json()["items"][0]["pitanje"] == "P?"
    assert client.put(f"/api/v1/admin/hr-faq/{faq.json()['id']}",
                      json={"kategorija_sifra": "ODMOR", "pitanje": "P?", "odgovor": "O.", "aktivno": False}
                      ).json()["aktivno"] is False
    cat = client.post("/api/v1/admin/hr-categories", json={"sifra": "nova", "naziv": "Nova"})
    assert cat.status_code == 201 and cat.json()["sifra"] == "NOVA"
    assert client.put("/api/v1/admin/hr-categories/NOVA", json={"naziv": "Nova 2"}).json()["naziv"] == "Nova 2"
    assert len(client.get("/api/v1/admin/hr-categories").json()["items"]) == 4


def test_http_requires_bearer_and_module(client):
    assert client.get("/api/v1/hr-questions").status_code == 401
    off, *_ = _setup(enabled=False)
    app.dependency_overrides[hr_mod.get_hr_question_service] = lambda: off
    app.dependency_overrides[get_current_ready_user] = lambda: make_korisnik(id=1)
    resp = client.get("/api/v1/hr-questions")
    assert resp.status_code == 404 and resp.json()["error"]["code"] == "HR_QUESTION_NOT_AVAILABLE"
    paths = app.openapi()["paths"]
    for p in ("/api/v1/hr-questions", "/api/v1/hr-questions/{pitanje_id}", "/api/v1/hr-questions/categories",
              "/api/v1/hr-questions/faq", "/api/v1/hr-questions/{pitanje_id}/follow-up",
              "/api/v1/admin/hr-questions", "/api/v1/admin/hr-questions/{pitanje_id}/answer",
              "/api/v1/admin/hr-questions/{pitanje_id}/close", "/api/v1/admin/hr-categories",
              "/api/v1/admin/hr-faq", "/api/v1/admin/hr-faq/{faq_id}"):
        assert p in paths


# ================================================================ SQL i Oracle
def test_sql_014_is_additive_and_complete():
    sql = SQL_014.read_text(encoding="utf-8")
    code = "\n".join(line.split("--", 1)[0] for line in sql.splitlines()).upper()
    for forbidden in ("DROP ", "DELETE FROM", "TRUNCATE", "ALTER TABLE", "HR.", "IIS."):
        assert forbidden not in code
    for table in ("PULS_HR_KATEGORIJE", "PULS_HR_PITANJA", "PULS_HR_PORUKE", "PULS_HR_CESTA_PITANJA"):
        assert f"CREATE TABLE {table}" in code
    assert "STATUS IN ('POSLATO', 'ODGOVORENO', 'ZATVORENO')" in code and "AUTOR IN ('ZAPOSLENI', 'HR')" in code
    assert "MERGE INTO PULS_HR_KATEGORIJE" in code and code.rstrip().endswith("COMMIT;")


class _Result:
    rowcount = 0

    def all(self):
        return []

    def first(self):
        return None

    def scalar(self):
        return 0

    def scalars(self):
        return self


class _CompileDb:
    def __init__(self):
        self.sql: list[str] = []

    def execute(self, stmt):
        self.sql.append(str(stmt.compile(dialect=oracle.dialect())).upper())
        return _Result()


def test_repository_compiles_for_oracle():
    db = _CompileDb()
    repo = HrQuestionRepository(db)
    repo.users_by_ids({1})
    repo.primary_orgjed(1)
    repo.orgjed_names({"318"})
    repo.list_categories("D")
    repo.get_category_for_update("ODMOR")
    repo.category_names()
    repo.get_question_for_update(1)
    repo.count_asked_since(1, NOW)
    repo.mine(1, 0, 21)
    repo.unread_count(1)
    repo.messages(1)
    repo.first_messages([1, 2])
    repo.admin_list("POSLATO", "ODMOR", 0, 20)
    repo.admin_list(None, None, 0, 20)
    repo.list_faq("D", "ODMOR")
    repo.get_faq_for_update(1)
    joined = "\n".join(db.sql)
    for t in ("PULS_HR_KATEGORIJE", "PULS_HR_PITANJA", "PULS_HR_PORUKE", "PULS_HR_CESTA_PITANJA", "FOR UPDATE"):
        assert t in joined
    assert "HR.KADROVI" not in joined and "IIS.KADROVI" not in joined and "HR.UGOVOR" not in joined
