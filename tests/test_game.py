"""GOMEX PUTANJA: generator, servis, HTTP, SQL skripta 012 i Oracle upiti."""

import datetime
import itertools
import json
import pathlib

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.dialects import oracle

from app.api.v1 import game as game_mod
from app.api.v1 import home as home_mod
from app.core.exceptions import (
    GameInvalidPathError,
    GameLevelExpiredError,
    GameNotAvailableError,
    GameNotStartedError,
)
from app.dependencies.auth import get_current_ready_user
from app.main import app
from app.models.igra import REZULTAT_RESEN, IgraNivo, IgraRezultat
from app.repositories.game_repository import GameRepository
from app.services import game_generator as gen
from app.services.game_service import GameService
from app.services.home_summary_service import HomeSummaryService
from tests.fakes import make_korisnik

NOW = datetime.datetime(2026, 11, 26, 9, 0, 0)  # cetvrtak -> 7x7
SQL_012 = pathlib.Path(__file__).resolve().parents[1] / "sql" / "012_igra_module.sql"
_ids = itertools.count(9000)


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
        return self.enabled and kod == "IGRA"

    def enabled_modules(self, korisnik):
        return {"POGODNOSTI": False, "PITAJ_HR": False, "KVIZ": False, "IGRA": self.enabled, "ZAHVALNICE": False}


class FakeGameRepo:
    def __init__(self):
        self.levels: dict[datetime.date, IgraNivo] = {}
        self.results: list[IgraRezultat] = []
        self.orgjed = {}

    def get_level(self, datum):
        return self.levels.get(datum)

    def add_level(self, nivo):
        nivo.id = next(_ids)
        self.levels[nivo.datum] = nivo
        return nivo

    def get_result(self, nivo_id, korisnik_id):
        return next((r for r in self.results if r.nivo_id == nivo_id and r.korisnik_id == korisnik_id), None)

    get_result_for_update = get_result

    def add_result(self, r):
        r.id = next(_ids)
        self.results.append(r)
        return r

    def primary_orgjed(self, korisnik_id):
        return self.orgjed.get(korisnik_id, "318")

    def orgjed_average(self, nivo_id, orgjed):
        done = [r for r in self.results if r.nivo_id == nivo_id and r.orgjed_sifra == orgjed and r.status == REZULTAT_RESEN]
        if not done:
            return 0, None
        return len(done), sum(int(r.trajanje_ms) for r in done) / len(done)

    def solved_dates(self, korisnik_id, since):
        by_id = {int(n.id): d for d, n in self.levels.items()}
        return {
            by_id[r.nivo_id]
            for r in self.results
            if r.korisnik_id == korisnik_id and r.status == REZULTAT_RESEN and by_id[r.nivo_id] >= since
        }


class Clock:
    def __init__(self, now=NOW):
        self.now = now

    def __call__(self):
        return self.now


def _service(repo=None, enabled=True, clock=None):
    return GameService(
        db=FakeDb(), repository=repo or FakeGameRepo(), module_access=FakeModules(enabled), now_fn=clock or Clock()
    )


def _user(id=10):
    return make_korisnik(id=id, platni_broj=f"E{id}", obavezna_promena_lozinke="N", telefon_potvrdjen="D")


def _solution(repo, datum):
    return json.loads(repo.levels[datum].resenje)


def _solve(svc, repo, user, clock, seconds):
    svc.start(user)
    clock.now += datetime.timedelta(seconds=seconds)
    out = svc.submit(user, clock.now.date(), _solution(repo, clock.now.date()))
    return out


# ================================================================ generator
def test_generator_is_deterministic_valid_and_scaled_by_weekday():
    start = datetime.date(2026, 11, 23)  # ponedeljak
    sizes = []
    for k in range(14):
        d = start + datetime.timedelta(days=k)
        podaci, resenje = gen.generate(d)
        assert gen.generate(d) == (podaci, resenje)
        assert gen.is_valid_solution(podaci, resenje)
        n = podaci["velicina"]
        assert len(podaci["tacke"]) == gen.difficulty(d)[1]
        assert len({tuple(t) for t in podaci["tacke"]}) == len(podaci["tacke"])
        assert podaci["tacke"][0] == list(resenje[0]) and podaci["tacke"][-1] == list(resenje[-1])
        for z in podaci["zidovi"]:
            assert abs(z[0] - z[2]) + abs(z[1] - z[3]) == 1 and all(0 <= v < n for v in z)
        sizes.append(n)
    assert sizes[:7] == [6, 6, 7, 7, 7, 8, 8]
    assert gen.generate(start)[0] != gen.generate(start + datetime.timedelta(days=7))[0]


def test_validator_rejects_bad_paths():
    podaci, resenje = gen.generate(datetime.date(2026, 11, 26))
    path = [list(c) for c in resenje]
    assert gen.is_valid_solution(podaci, path)
    assert not gen.is_valid_solution(podaci, path[:-1])  # nije proslo sva polja
    assert not gen.is_valid_solution(podaci, path[::-1])  # pocinje od kase
    assert not gen.is_valid_solution(podaci, path[:-1] + [path[0]])  # ponovljeno polje
    skok = path[:]
    skok[1], skok[2] = skok[2], skok[1]
    assert not gen.is_valid_solution(podaci, skok)
    assert not gen.is_valid_solution(podaci, [[0, 0]] * 49)
    assert not gen.is_valid_solution(podaci, [["a", 1]])
    # Zid preko poteza resenja: ista putanja vise ne vazi.
    a, b = path[3], path[4]
    with_wall = dict(podaci, zidovi=[*podaci["zidovi"], [*a, *b]])
    assert not gen.is_valid_solution(with_wall, path)


# ================================================================ servis
def test_daily_without_level_and_module_off():
    svc = _service()
    out = svc.daily(_user())
    assert out["status"] == "NIJE_POCETO" and out["velicina"] == 7 and out["broj_tacaka"] == 8
    assert out["niz_dana"] == 0 and out["prosek_orgjed_ms"] is None
    with pytest.raises(GameNotAvailableError):
        _service(enabled=False).daily(_user())
    with pytest.raises(GameNotAvailableError):
        _service(enabled=False).start(_user())


def test_start_creates_level_once_and_hides_solution():
    repo = FakeGameRepo()
    svc = _service(repo)
    level = svc.start(_user())
    assert level["status"] == "U_TOKU" and level["velicina"] == 7
    assert "resenje" not in level and len(level["tacke"]) == 8
    svc.start(_user(11))
    assert len(repo.levels) == 1
    assert repo.get_result(int(repo.levels[NOW.date()].id), 10).broj_pokretanja == 1


def test_server_timed_first_solution_counts_and_restart_resets_clock():
    repo, clock = FakeGameRepo(), Clock()
    svc = _service(repo, clock=clock)
    user = _user()
    svc.start(user)
    clock.now += datetime.timedelta(seconds=300)
    svc.start(user)  # nova partija - sat ispocetka
    clock.now += datetime.timedelta(seconds=42)
    out = svc.submit(user, NOW.date(), _solution(repo, NOW.date()))
    assert out["prvo_resenje"] is True and out["status"] == "RESENO" and out["moje_vreme_ms"] == 42000
    assert out["niz_dana"] == 1
    r = repo.results[0]
    assert r.broj_pokretanja == 2

    level = svc.start(user)  # ponovna igra posle resenja
    assert level["status"] == "RESENO"
    clock.now += datetime.timedelta(seconds=5)
    again = svc.submit(user, NOW.date(), _solution(repo, NOW.date()))
    assert again["prvo_resenje"] is False and again["moje_vreme_ms"] == 42000
    assert svc.badge_count(user) == 0


def test_submit_errors():
    repo, clock = FakeGameRepo(), Clock()
    svc = _service(repo, clock=clock)
    user = _user()
    with pytest.raises(GameNotStartedError):
        svc.submit(user, NOW.date(), [[0, 0]])
    svc.start(user)
    with pytest.raises(GameInvalidPathError):
        svc.submit(user, NOW.date(), [[0, 0]])
    with pytest.raises(GameLevelExpiredError):
        svc.submit(user, NOW.date() - datetime.timedelta(days=1), _solution(repo, NOW.date()))
    clock.now += datetime.timedelta(days=1)  # prosla ponoc tokom igre
    with pytest.raises(GameLevelExpiredError):
        svc.submit(user, NOW.date(), _solution(repo, NOW.date()))
    assert repo.results[0].status == "U_TOKU"


def test_store_average_from_three_solutions_and_streak():
    repo, clock = FakeGameRepo(), Clock()
    svc = _service(repo, clock=clock)
    for uid, sec in ((1, 30), (2, 60)):
        _solve(svc, repo, _user(uid), clock, sec)
    out = svc.daily(_user(1))
    assert out["broj_resenih_orgjed"] == 2 and out["prosek_orgjed_ms"] is None
    repo.orgjed[3] = "401"
    _solve(svc, repo, _user(3), clock, 10)  # druga prodavnica se ne racuna
    out = _solve(svc, repo, _user(4), clock, 90)
    assert out["broj_resenih_orgjed"] == 3 and out["prosek_orgjed_ms"] == 60000

    # niz: tri dana zaredom, pa danas jos nije reseno -> i dalje 3
    clock2 = Clock(datetime.datetime(2026, 11, 20, 9, 0))
    repo2 = FakeGameRepo()
    svc2 = _service(repo2, clock=clock2)
    user = _user()
    for _ in range(3):
        _solve(svc2, repo2, user, clock2, 20)
        clock2.now += datetime.timedelta(days=1)
    assert svc2.daily(user)["niz_dana"] == 3
    assert svc2.badge_count(user) == 1
    clock2.now += datetime.timedelta(days=1)  # preskocen dan
    assert svc2.daily(user)["niz_dana"] == 0


# ================================================================ HTTP
@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_http_flow_and_home_badge(client):
    repo, clock = FakeGameRepo(), Clock()
    app.dependency_overrides[game_mod.get_game_service] = lambda: _service(repo, clock=clock)
    app.dependency_overrides[get_current_ready_user] = lambda: _user()
    assert client.get("/api/v1/game/daily").json()["status"] == "NIJE_POCETO"
    level = client.post("/api/v1/game/daily/start").json()
    assert level["datum"] == "2026-11-26" and "resenje" not in level
    bad = client.post("/api/v1/game/daily/result", json={"datum": "2026-11-26", "putanja": [[0, 0]]})
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "GAME_INVALID_PATH"
    clock.now += datetime.timedelta(seconds=7)
    ok = client.post("/api/v1/game/daily/result", json={"datum": "2026-11-26", "putanja": _solution(repo, NOW.date())})
    assert ok.status_code == 200 and ok.json()["moje_vreme_ms"] == 7000 and ok.json()["prvo_resenje"] is True

    app.dependency_overrides[home_mod.get_home_summary_service] = lambda: HomeSummaryService(
        FakeModules(), badge_counters={"IGRA": _service(repo, clock=clock).badge_count}
    )
    moduli = {m["kod"]: m for m in client.get("/api/v1/home/summary").json()["moduli"]}
    assert moduli["IGRA"]["aktivan"] is True and moduli["IGRA"]["broj_novih"] == 0


def test_http_requires_bearer_and_module(client):
    assert client.get("/api/v1/game/daily").status_code == 401
    app.dependency_overrides[game_mod.get_game_service] = lambda: _service(enabled=False)
    app.dependency_overrides[get_current_ready_user] = lambda: _user()
    resp = client.post("/api/v1/game/daily/start")
    assert resp.status_code == 404 and resp.json()["error"]["code"] == "GAME_NOT_AVAILABLE"
    paths = app.openapi()["paths"]
    for p in ("/api/v1/game/daily", "/api/v1/game/daily/start", "/api/v1/game/daily/result"):
        assert p in paths


# ================================================================ SQL i Oracle
def test_sql_012_is_additive_and_complete():
    sql = SQL_012.read_text(encoding="utf-8")
    code = "\n".join(line.split("--", 1)[0] for line in sql.splitlines()).upper()
    for forbidden in ("DROP ", "DELETE FROM", "TRUNCATE", "ALTER TABLE", "HR.", "IIS."):
        assert forbidden not in code
    for table in ("PULS_IGRA_NIVOI", "PULS_IGRA_REZULTATI"):
        assert f"CREATE TABLE {table}" in code
    assert "UNIQUE (DATUM)" in code and "UNIQUE (NIVO_ID, KORISNIK_ID)" in code
    assert code.rstrip().endswith("COMMIT;")


class _Result:
    def all(self):
        return []

    def one(self):
        return (0, None)

    def first(self):
        return None

    def scalars(self):
        return self


class _CompileDb:
    def __init__(self):
        self.sql: list[str] = []

    def execute(self, stmt):
        self.sql.append(str(stmt.compile(dialect=oracle.dialect())).upper())
        return _Result()


def test_game_repository_compiles_for_oracle():
    db = _CompileDb()
    repo = GameRepository(db)
    d = datetime.date(2026, 11, 26)
    repo.get_level(d)
    repo.get_result(1, 1)
    repo.get_result_for_update(1, 1)
    repo.primary_orgjed(1)
    repo.orgjed_average(1, "318")
    repo.solved_dates(1, d)
    joined = "\n".join(db.sql)
    assert "PULS_IGRA_NIVOI" in joined and "PULS_IGRA_REZULTATI" in joined and "FOR UPDATE" in joined
    assert "HR." not in joined and "IIS." not in joined and "SELECT *" not in joined
