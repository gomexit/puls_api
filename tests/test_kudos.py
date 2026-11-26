"""HVALA, KOLEGA!: servis, filter reci, admin, worker (push), HTTP, SQL 013 i Oracle upiti."""

import datetime
import itertools
import pathlib

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.dialects import oracle

from app.api.v1 import admin_kudos as admin_mod
from app.api.v1 import kudos as kudos_mod
from app.core.exceptions import (
    KudosCannotReportError,
    KudosDailyLimitError,
    KudosInappropriateError,
    KudosInvalidStatusError,
    KudosNotAvailableError,
    KudosNotFoundError,
    KudosRecipientInvalidError,
    KudosSelfError,
    ValidationBusinessError,
)
from app.dependencies.auth import get_current_ready_user
from app.dependencies.portal_auth import require_portal_admin_or_hr
from app.main import app
from app.models.sistemski_dogadjaj import DOGADJAJ_TIP_KUDOS_RECEIVED, DOGADJAJ_TIPOVI
from app.models.zahvalnica import STATUS_NA_PROVERI, STATUS_OBJAVLJENA, STATUS_SAKRIVENA
from app.repositories.kudos_repository import KudosRepository
from app.services import system_notification_service as sns
from app.services.kudos_admin_service import KudosAdminService
from app.services.kudos_service import KudosService, clean_text
from app.services.kudos_text_filter import is_inappropriate
from tests.fakes import make_korisnik

NOW = datetime.datetime(2026, 11, 26, 10, 0, 0)
SQL_013 = pathlib.Path(__file__).resolve().parents[1] / "sql" / "013_zahvalnice_module.sql"
_ids = itertools.count(5000)


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
    def __init__(self, enabled=True, disabled_ids=()):
        self.enabled = enabled
        self.disabled_ids = set(disabled_ids)

    def is_enabled(self, korisnik, kod):
        return self.enabled and kod == "ZAHVALNICE" and int(korisnik.id) not in self.disabled_ids


class FakeEvents:
    def __init__(self):
        self.events = []

    def enqueue_if_absent(self, kljuc, tip, resurs_id, vrednost, now):
        self.events.append((kljuc, tip, resurs_id))
        return True


class FakeRepo:
    def __init__(self, users, orgjed=None):
        self.users = {int(u.id): u for u in users}
        self.orgjed = orgjed or {}
        self.rows = []
        self.reports_ = []

    def get_user(self, kid):
        return self.users.get(kid)

    def users_by_ids(self, ids):
        return {i: self.users[i] for i in ids if i in self.users}

    def primary_orgjed(self, kid):
        return self.orgjed.get(kid)

    def orgjed_names(self, sifre):
        return {s: f"Prodavnica {s}" for s in sifre}

    def search_colleagues(self, tokens, exclude_id, limit):
        out = [
            u for u in self.users.values()
            if int(u.id) != exclude_id and u.status_zaposlenja == "AKTIVAN" and u.status_naloga == "OMOGUCEN"
            and all(t.upper() in u.ime.upper() or t.upper() in u.prezime.upper() for t in tokens)
        ]
        return out[:limit]

    def add(self, z):
        z.id = next(_ids)
        self.rows.append(z)
        return z

    def get(self, zid):
        return next((z for z in self.rows if int(z.id) == zid), None)

    get_for_update = get

    def count_sent_since(self, sid, since):
        return sum(1 for z in self.rows if z.posiljalac_id == sid and z.datum_kreiranja >= since)

    def _sorted(self, rows):
        return sorted(rows, key=lambda z: (z.datum_kreiranja, z.id), reverse=True)

    def feed(self, orgjed, offset, limit):
        rows = [z for z in self.rows if z.status == STATUS_OBJAVLJENA]
        if orgjed is not None:
            rows = [z for z in rows if orgjed in (z.primalac_orgjed, z.posiljalac_orgjed)]
        return self._sorted(rows)[offset : offset + limit]

    def received(self, kid, offset, limit):
        rows = [z for z in self.rows if z.primalac_id == kid and z.status == STATUS_OBJAVLJENA]
        return self._sorted(rows)[offset : offset + limit]

    def sent(self, kid, offset, limit):
        return self._sorted([z for z in self.rows if z.posiljalac_id == kid])[offset : offset + limit]

    def unread_count(self, kid):
        return sum(
            1 for z in self.rows if z.primalac_id == kid and z.status == STATUS_OBJAVLJENA and z.procitana == "N"
        )

    def mark_received_read(self, kid):
        n = 0
        for z in self.rows:
            if z.primalac_id == kid and z.procitana == "N":
                z.procitana = "D"
                n += 1
        return n

    def has_report(self, zid, kid):
        return any(p.zahvalnica_id == zid and p.korisnik_id == kid for p in self.reports_)

    def add_report(self, p):
        self.reports_.append(p)
        return p

    def report_count(self, zid):
        return sum(1 for p in self.reports_ if p.zahvalnica_id == zid)

    def report_counts(self, ids):
        return {i: self.report_count(i) for i in ids if self.report_count(i)}

    def reports(self, zid):
        return [p for p in self.reports_ if p.zahvalnica_id == zid]

    def admin_list(self, status, offset, limit):
        rows = [z for z in self.rows if status is None or z.status == status]
        return len(rows), self._sorted(rows)[offset : offset + limit]


class Clock:
    def __init__(self, now=NOW):
        self.now = now

    def __call__(self):
        return self.now


class FakeAudit:
    def __init__(self):
        self.entries = []

    def log(self, akcija, **kw):
        self.entries.append((akcija, kw))


def _people():
    ana = make_korisnik(id=1, ime="Ana", prezime="Petrović", platni_broj="111")
    marko = make_korisnik(id=2, ime="Marko", prezime="Jovanović", platni_broj="222")
    jelena = make_korisnik(id=3, ime="Jelena", prezime="Marković", platni_broj="333")
    bivsi = make_korisnik(id=4, ime="Mara", prezime="Bivša", platni_broj="444", status_zaposlenja="NEAKTIVAN")
    return ana, marko, jelena, bivsi


def _setup(enabled=True, disabled_ids=()):
    ana, marko, jelena, bivsi = _people()
    repo = FakeRepo([ana, marko, jelena, bivsi], orgjed={1: "318", 2: "318", 3: "201"})
    events, clock = FakeEvents(), Clock()
    svc = KudosService(FakeDb(), repository=repo, module_access=FakeModules(enabled, disabled_ids),
                       event_repository=events, now_fn=clock)
    return svc, repo, events, clock, (ana, marko, jelena, bivsi)


# ================================================================ servis
def test_send_publishes_immediately_and_queues_push():
    svc, repo, events, _, (ana, *_) = _setup()
    view = svc.send(ana, 2, "pomoc", "  Hvala   na pomoći oko\r\n\r\n\r\ninventara!  ")
    assert view["status"] == STATUS_OBJAVLJENA and view["tekst"] == "Hvala na pomoći oko\n\ninventara!"
    assert view["primalac"] == {"id": 2, "ime": "Marko", "prezime": "Jovanović", "orgjed_naziv": "Prodavnica 318"}
    assert "platni_broj" not in view["primalac"] and "broj_telefona" not in str(view)
    assert view["povod"] == "POMOC" and view["povod_naziv"] == "Pomoć" and view["mogu_prijaviti"] is False
    assert events.events == [(f"KUDOS_RECEIVED:{view['id']}", DOGADJAJ_TIP_KUDOS_RECEIVED, view["id"])]
    assert repo.rows[0].primalac_orgjed == "318" and repo.rows[0].posiljalac_orgjed == "318"


def test_send_rules():
    svc, _, _, clock, (ana, _, _, _) = _setup()
    with pytest.raises(KudosSelfError):
        svc.send(ana, 1, "POMOC", "Sebi")
    with pytest.raises(KudosRecipientInvalidError):
        svc.send(ana, 4, "POMOC", "Bivšem")
    with pytest.raises(KudosRecipientInvalidError):
        svc.send(ana, 99, "POMOC", "Nikome")
    with pytest.raises(ValidationBusinessError):
        svc.send(ana, 2, "NESTO", "Hvala")
    with pytest.raises(ValidationBusinessError):
        svc.send(ana, 2, "POMOC", "x" * 281)
    with pytest.raises(ValidationBusinessError):
        svc.send(ana, 2, "POMOC", "   ")
    with pytest.raises(KudosInappropriateError):
        svc.send(ana, 2, "POMOC", "Hvala, kretenu")
    for i in range(5):
        svc.send(ana, 2 if i % 2 else 3, "TIMSKI_RAD", f"Hvala {i}")
    with pytest.raises(KudosDailyLimitError):
        svc.send(ana, 2, "POMOC", "Šesta")
    clock.now += datetime.timedelta(days=1)
    assert svc.send(ana, 2, "POMOC", "Novi dan")["id"]


def test_recipient_without_module_and_module_off():
    svc, _, _, _, (ana, _, _, _) = _setup(disabled_ids={2})
    with pytest.raises(KudosRecipientInvalidError):
        svc.send(ana, 2, "POMOC", "Hvala")
    assert [c["id"] for c in svc.search_colleagues(ana, "ović")] == [3]
    off, *_ = _setup(enabled=False)
    for call in (lambda: off.feed(ana, "svi", 1, 20), lambda: off.send(ana, 2, "POMOC", "x"),
                 lambda: off.search_colleagues(ana, "Mar"), lambda: off.report(ana, 1, None)):
        with pytest.raises(KudosNotAvailableError):
            call()


def test_search_returns_only_safe_fields_and_needs_three_letters():
    svc, _, _, _, (ana, _, _, _) = _setup()
    assert svc.search_colleagues(ana, "Ma") == []
    found = svc.search_colleagues(ana, "mar")
    assert {c["id"] for c in found} == {2, 3}  # bez neaktivne Mare i bez mene
    assert set(found[0]) == {"id", "ime", "prezime", "orgjed_naziv"}
    assert [c["id"] for c in svc.search_colleagues(ana, "Jelena Mar")] == [3]


def test_feed_scope_mine_and_badge():
    svc, _, _, clock, (ana, marko, jelena, _) = _setup()
    a = svc.send(ana, 2, "POMOC", "Ana Marku")
    clock.now += datetime.timedelta(minutes=1)
    b = svc.send(jelena, 2, "LJUBAZNOST", "Jelena Marku")
    clock.now += datetime.timedelta(minutes=1)
    c = svc.send(jelena, 1, "TIMSKI_RAD", "Jelena Ani")
    assert [i["id"] for i in svc.feed(marko, "svi", 1, 20)["items"]] == [c["id"], b["id"], a["id"]]
    store = svc.feed(jelena, "prodavnica", 1, 20)  # Jelena je iz 201: samo njene poslate su "njene"
    assert [i["id"] for i in store["items"]] == [c["id"], b["id"]]
    page = svc.feed(marko, "svi", 1, 2)
    assert len(page["items"]) == 2 and page["ima_jos"] is True
    assert svc.badge_count(marko) == 2
    mine = svc.mine(marko, "primljene", 1, 20)
    assert [i["id"] for i in mine["items"]] == [b["id"], a["id"]] and mine["items"][0]["status"] is None
    assert svc.badge_count(marko) == 0
    sent = svc.mine(jelena, "poslate", 1, 20)
    assert [i["id"] for i in sent["items"]] == [c["id"], b["id"]] and sent["items"][0]["status"] == "OBJAVLJENA"


def test_reports_hide_after_three_and_review_stops_auto_hide():
    svc, repo, _, _, (ana, marko, jelena, _) = _setup()
    z = svc.send(ana, 2, "POMOC", "Hvala")
    with pytest.raises(KudosCannotReportError):
        svc.report(ana, z["id"], None)
    svc.report(marko, z["id"], "ne valja")
    svc.report(marko, z["id"], "ponovo")  # ista osoba se ne broji dvaput
    svc.report(jelena, z["id"], None)
    assert repo.get(z["id"]).status == STATUS_OBJAVLJENA
    treci = make_korisnik(id=7, ime="Treći", prezime="Kolega")
    repo.users[7] = treci
    svc.report(treci, z["id"], None)
    assert repo.get(z["id"]).status == STATUS_NA_PROVERI
    assert svc.feed(marko, "svi", 1, 20)["items"] == [] and svc.badge_count(marko) == 0
    with pytest.raises(KudosNotFoundError):
        svc.report(marko, z["id"], None)

    audit = FakeAudit()
    admin = KudosAdminService(FakeDb(), repository=repo, audit_service=audit, now_fn=Clock())
    lst = admin.list("na_proveri", 1, 20)
    assert lst["total"] == 1 and lst["items"][0]["broj_prijava"] == 3
    detail = admin.get(z["id"])
    assert [p["razlog"] for p in detail["prijave"]] == ["ne valja", None, None]
    assert "korisnik_id" not in str(detail["prijave"])
    hr = make_korisnik(id=9, ime="HR", prezime="Admin")
    restored = admin.restore(hr, z["id"])
    assert restored["status"] == STATUS_OBJAVLJENA and restored["proverena"] is True
    novi = make_korisnik(id=8, ime="Novi", prezime="Kolega")
    repo.users[8] = novi
    svc.report(novi, z["id"], None)
    assert repo.get(z["id"]).status == STATUS_OBJAVLJENA  # posle pregleda HR-a nema automatskog sklanjanja
    assert admin.hide(hr, z["id"])["status"] == STATUS_SAKRIVENA
    assert [a for a, _ in audit.entries] == ["ADMIN_KUDOS_RESTORED", "ADMIN_KUDOS_HIDDEN"]
    with pytest.raises(KudosInvalidStatusError):
        admin.list("BRISANA", 1, 20)
    with pytest.raises(KudosNotFoundError):
        admin.get(12345)


def test_text_filter():
    assert not is_inappropriate("Hvala na pomoći oko inventara, sjajan si!")
    assert not is_inappropriate("Zahvaljujem se na seriji akcija i divno sređenim rafovima.")
    for bad in ("jebiga", "Ti si KRETEN", "Пичка", "idiote jedan", "kuuurvo", "Jebeeeno"):
        assert is_inappropriate(bad), bad
    assert clean_text(" a \n\n\n b ") == "a\n\nb"


# ================================================================ worker (push)
def test_worker_resolves_kudos_for_recipient(monkeypatch):
    assert DOGADJAJ_TIP_KUDOS_RECEIVED in DOGADJAJ_TIPOVI
    svc, repo, _, _, (ana, *_) = _setup()
    z = svc.send(ana, 2, "LJUBAZNOST", "Hvala što si pomogao kupcu.")

    class Access:
        def __init__(self, *a):
            pass

        def is_enabled(self, k, kod):
            return kod == "ZAHVALNICE"

    monkeypatch.setattr(sns, "KudosRepository", lambda db: repo)
    monkeypatch.setattr(sns, "ModuleAccessService", Access)
    monkeypatch.setattr(sns, "ConfigurationRepository", lambda db: None)
    monkeypatch.setattr(sns, "ModuleAccessRepository", lambda db: None)
    worker = sns.SystemNotificationService.__new__(sns.SystemNotificationService)
    worker.db = None
    event = type("E", (), {"resurs_id": z["id"], "tip_dogadjaja": DOGADJAJ_TIP_KUDOS_RECEIVED})()
    recipients, content = worker._resolve_kudos(event)
    assert recipients == {2}
    assert content["akcija_tip"] == "KUDOS" and content["resurs_id"] == z["id"] and content["akcija_url"] is None
    assert content["kratak_tekst"] == "Ana Petrović vam šalje zahvalnicu."
    assert content["sadrzaj"] == "Ljubaznost prema kupcu: Hvala što si pomogao kupcu."
    repo.get(z["id"]).status = STATUS_SAKRIVENA
    assert worker._resolve_kudos(event) == (None, None)


# ================================================================ HTTP
@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_http_flow(client):
    svc, repo, _, _, (ana, marko, _, _) = _setup()
    app.dependency_overrides[kudos_mod.get_kudos_service] = lambda: svc
    app.dependency_overrides[get_current_ready_user] = lambda: ana
    found = client.get("/api/v1/colleagues/search", params={"q": "Jovan"}).json()["items"]
    assert found == [{"id": 2, "ime": "Marko", "prezime": "Jovanović", "orgjed_naziv": "Prodavnica 318"}]
    created = client.post("/api/v1/kudos", json={"primalac_id": 2, "povod": "POMOC", "tekst": "Hvala!"})
    assert created.status_code == 201 and created.json()["primalac"]["ime"] == "Marko"
    bad = client.post("/api/v1/kudos", json={"primalac_id": 1, "povod": "POMOC", "tekst": "Sebi"})
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "KUDOS_SELF"
    feed = client.get("/api/v1/kudos/feed", params={"opseg": "svi"}).json()
    assert feed["opseg"] == "svi" and len(feed["items"]) == 1
    assert client.get("/api/v1/kudos/feed", params={"opseg": "nesto"}).status_code == 422
    app.dependency_overrides[get_current_ready_user] = lambda: marko
    zid = created.json()["id"]
    assert client.post(f"/api/v1/kudos/{zid}/report", json={"razlog": "test"}).json() == {"prijavljena": True}
    assert client.post(f"/api/v1/kudos/{zid}/report").status_code == 200
    mine = client.get("/api/v1/kudos/mine").json()
    assert mine["smer"] == "primljene" and mine["items"][0]["id"] == zid

    app.dependency_overrides[admin_mod.get_kudos_admin_service] = lambda: KudosAdminService(
        FakeDb(), repository=repo, audit_service=FakeAudit(), now_fn=Clock()
    )
    app.dependency_overrides[require_portal_admin_or_hr] = lambda: make_korisnik(id=9)
    lst = client.get("/api/v1/admin/kudos").json()
    assert lst["total"] == 1 and lst["items"][0]["broj_prijava"] == 1
    assert client.post(f"/api/v1/admin/kudos/{zid}/hide").json()["status"] == "SAKRIVENA"
    assert client.get("/api/v1/admin/kudos/999999").json()["error"]["code"] == "KUDOS_NOT_FOUND"


def test_http_requires_bearer_and_module(client):
    assert client.get("/api/v1/kudos/feed").status_code == 401
    off, *_ = _setup(enabled=False)
    app.dependency_overrides[kudos_mod.get_kudos_service] = lambda: off
    app.dependency_overrides[get_current_ready_user] = lambda: _people()[0]
    resp = client.get("/api/v1/kudos/feed")
    assert resp.status_code == 404 and resp.json()["error"]["code"] == "KUDOS_NOT_AVAILABLE"
    paths = app.openapi()["paths"]
    for p in ("/api/v1/kudos", "/api/v1/kudos/feed", "/api/v1/kudos/mine", "/api/v1/kudos/{zahvalnica_id}/report",
              "/api/v1/colleagues/search", "/api/v1/admin/kudos", "/api/v1/admin/kudos/{zahvalnica_id}/hide"):
        assert p in paths


# ================================================================ SQL i Oracle
def test_sql_013_is_additive_and_complete():
    sql = SQL_013.read_text(encoding="utf-8")
    code = "\n".join(line.split("--", 1)[0] for line in sql.splitlines()).upper()
    for forbidden in ("DROP ", "DELETE FROM", "TRUNCATE", "ALTER TABLE", "HR.", "IIS."):
        assert forbidden not in code
    for table in ("PULS_ZAHVALNICE", "PULS_ZAHVALNICA_PRIJAVE"):
        assert f"CREATE TABLE {table}" in code
    assert "UNIQUE (ZAHVALNICA_ID, KORISNIK_ID)" in code and "POSILJALAC_ID <> PRIMALAC_ID" in code
    assert "TEKST                   NVARCHAR2(280)" in code
    assert code.rstrip().endswith("COMMIT;")


class _Result:
    rowcount = 0

    def all(self):
        return []

    def one(self):
        return (0, None)

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


def test_kudos_repository_compiles_for_oracle():
    db = _CompileDb()
    repo = KudosRepository(db)
    repo.users_by_ids({1, 2})
    repo.primary_orgjed(1)
    repo.orgjed_names({"318"})
    repo.search_colleagues(["mar", "jov"], 1, 20)
    repo.get_for_update(1)
    repo.count_sent_since(1, NOW)
    repo.feed("318", 0, 21)
    repo.feed(None, 0, 21)
    repo.received(1, 0, 21)
    repo.sent(1, 0, 21)
    repo.unread_count(1)
    repo.mark_received_read(1)
    repo.has_report(1, 1)
    repo.report_count(1)
    repo.report_counts([1, 2])
    repo.reports(1)
    repo.admin_list("NA_PROVERI", 0, 20)
    joined = "\n".join(db.sql)
    assert "PULS_ZAHVALNICE" in joined and "PULS_ZAHVALNICA_PRIJAVE" in joined and "FOR UPDATE" in joined
    assert "HR." not in joined and "IIS.KADROVI" not in joined and "IIS.ZAPOSLENJA" not in joined
