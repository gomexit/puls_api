"""Sortiranje po koloni (+paginacija) na admin GET listama: SQL (Oracle dijalekat) po repozitorijumu
i HTTP ponasanje po endpointu. Zajednicki modul je pokriven u tests/test_sorting.py."""

import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.dialects import oracle

from app.api.v1 import admin_ideas, admin_notifications, admin_surveys, admin_users
from app.core.sorting import SortSpec
from app.dependencies.portal_auth import require_portal_admin, require_portal_admin_or_hr
from app.main import app
from app.repositories import idea_repository, notification_repository
from app.repositories.admin_users_repository import (
    USERS_DEFAULT_SORT,
    USERS_SORT_COLUMNS,
    AdminUsersRepository,
)
from app.repositories.idea_repository import IDEA_DEFAULT_SORT, IDEA_SORT_COLUMNS, IdeaRepository
from app.repositories.notification_repository import (
    ADMIN_DEFAULT_SORT as NOTIF_DEFAULT_SORT,
)
from app.repositories.notification_repository import (
    ADMIN_SORT_FIELDS as NOTIF_SORT_FIELDS,
)
from app.repositories.notification_repository import NotificationRepository
from app.repositories.survey_repository import (
    SURVEY_DEFAULT_SORT,
    SURVEY_SORT_COLUMNS,
    SurveyRepository,
)
from tests.fakes import make_korisnik


# ======================================================================= SQL (Oracle)
class _Stub:
    def all(self):
        return []

    def first(self):
        return None

    def scalar_one(self):
        return 0

    def scalar_one_or_none(self):
        return None

    def scalars(self):
        return self


class _CompileDb:
    def __init__(self):
        self.compiled: list[str] = []

    def execute(self, stmt, *args, **kwargs):
        sql = str(stmt.compile(dialect=oracle.dialect())).upper().replace('"', "")
        self.compiled.append(" ".join(sql.split()))
        return _Stub()


def _order_by(sql: str) -> str:
    return sql.split("ORDER BY", 1)[1].split(" OFFSET")[0].strip()


def _notif_columns():
    repo = NotificationRepository(_CompileDb())
    return notification_repository.admin_sort_columns(repo._recipient_counts_subquery())


# ime modula -> (repo factory, poziv liste, polja, default, tekst, lpad, case)
MODULES = {
    "users": dict(
        repo=lambda db: AdminUsersRepository(db),
        call=lambda repo, sort: repo.list_users(None, None, None, None, None, 1, 20, sort=sort),
        fields=list(USERS_SORT_COLUMNS),
        default=USERS_DEFAULT_SORT,
        text={"ime", "prezime"},
        lpad={"platni_broj"},
        case={"zakljucan", "obavezna_promena_lozinke", "telefon_potvrdjen"},
    ),
    "surveys": dict(
        repo=lambda db: SurveyRepository(db),
        call=lambda repo, sort: repo.list_surveys(None, None, None, None, 1, 20, sort=sort),
        fields=list(SURVEY_SORT_COLUMNS),
        default=SURVEY_DEFAULT_SORT,
        text={"naziv"},
        lpad=set(),
        case={"status", "anonimna"},
    ),
    "notifications": dict(
        repo=lambda db: NotificationRepository(db),
        call=lambda repo, sort: repo.admin_list(None, None, None, None, 1, 20, sort=sort),
        fields=list(NOTIF_SORT_FIELDS),
        default=NOTIF_DEFAULT_SORT,
        text={"naslov", "kategorija"},
        lpad={"kreirao_platni_broj"},
        case={"status"},
    ),
    "ideas": dict(
        repo=lambda db: IdeaRepository(db),
        call=lambda repo, sort: repo.admin_list(None, None, None, None, 1, 20, sort=sort),
        fields=list(IDEA_SORT_COLUMNS),
        default=IDEA_DEFAULT_SORT,
        text={"ime_autora", "prezime_autora", "naslov"},
        lpad={"platni_broj", "orgjed_sifra"},
        case={"status"},
    ),
}


def _compile(module: str, sort):
    cfg = MODULES[module]
    db = _CompileDb()
    cfg["call"](cfg["repo"](db), sort)
    return db.compiled[-1]


@pytest.mark.parametrize("module", list(MODULES))
def test_every_column_both_directions_has_nulls_last_and_tiebreaker(module):
    cfg = MODULES[module]
    for field in cfg["fields"]:
        for direction in ("asc", "desc"):
            order_by = _order_by(_compile(module, SortSpec(field, direction)))
            word = direction.upper()
            assert f"{word} NULLS LAST" in order_by, (module, field, direction, order_by)
            last = order_by.split(",")[-1].strip()
            assert re.fullmatch(rf"\S*\.ID {word}", last), (module, field, order_by)
            assert ("NLSSORT(" in order_by) == (field in cfg["text"]), (module, field)
            assert ("LPAD(" in order_by) == (field in cfg["lpad"]), (module, field)
            # CASE: flag/status kolone i grupa cifara kod tekstualnih kolona
            assert ("CASE" in order_by) == (field in cfg["case"] or field in cfg["text"]), (module, field)
            assert ("REGEXP_LIKE" in order_by) == (field in cfg["text"]), (module, field)


@pytest.mark.parametrize("module", list(MODULES))
def test_default_order_is_unchanged_when_no_sort_is_given(module):
    cfg = MODULES[module]
    assert _order_by(_compile(module, None)) == _order_by(_compile(module, cfg["default"]))


def test_documented_defaults_match_the_previous_hardcoded_order():
    assert USERS_DEFAULT_SORT == SortSpec("id", "asc")
    assert SURVEY_DEFAULT_SORT == SortSpec("datum_kreiranja", "desc")
    assert NOTIF_DEFAULT_SORT == SortSpec("datum_kreiranja", "desc")
    assert IDEA_DEFAULT_SORT == SortSpec("datum_kreiranja", "desc")


def test_default_sort_columns_are_whitelisted():
    for fields, default in (
        (USERS_SORT_COLUMNS, USERS_DEFAULT_SORT),
        (SURVEY_SORT_COLUMNS, SURVEY_DEFAULT_SORT),
        (IDEA_SORT_COLUMNS, IDEA_DEFAULT_SORT),
        (NOTIF_SORT_FIELDS, NOTIF_DEFAULT_SORT),
    ):
        assert default.by in fields


def test_users_org_unit_role_and_secret_columns_are_not_sortable():
    for blocked in ("lozinka_hash", "orgjed_sifra", "orgjed_naziv", "radno_mesto_naziv", "uloge"):
        assert blocked not in USERS_SORT_COLUMNS


def test_free_text_and_blob_columns_are_not_sortable():
    assert "opis" not in IDEA_SORT_COLUMNS and "opis" not in SURVEY_SORT_COLUMNS
    assert "kratak_tekst" not in NOTIF_SORT_FIELDS and "sadrzaj" not in NOTIF_SORT_FIELDS


def test_notification_field_tuple_matches_the_real_column_map():
    assert list(NOTIF_SORT_FIELDS) == list(_notif_columns())


def test_notification_aggregates_use_coalesce_and_unread_is_a_difference():
    sql = _compile("notifications", SortSpec("broj_neprocitanih", "desc"))
    order_by = _order_by(sql)
    assert order_by.count("COALESCE(") == 2 and " - " in order_by


def test_workflow_status_order_is_defined_by_status_tuples():
    from app.models.anketa import ANKETA_STATUSI
    from app.models.ideja import IDEJA_STATUSI
    from app.models.obavestenje import OBAVESTENJE_STATUSI

    for column, statuses in (
        (SURVEY_SORT_COLUMNS["status"].expr, ANKETA_STATUSI),
        (IDEA_SORT_COLUMNS["status"].expr, IDEJA_STATUSI),
    ):
        sql = str(column.compile(dialect=oracle.dialect(), compile_kwargs={"literal_binds": True})).upper()
        positions = [sql.index(f"'{s.upper()}'") for s in statuses]
        assert positions == sorted(positions)
    assert OBAVESTENJE_STATUSI == ("DRAFT", "PUBLISHED", "ARCHIVED")


# ===================================================================== HTTP (stub servisi)
class _StubService:
    def __init__(self, result):
        self.result = result
        self.calls: list[tuple[str, tuple, dict]] = []

    def __getattr__(self, name):
        def method(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            return self.result

        return method


ENDPOINTS = {
    "users": dict(
        url="/api/v1/admin/users",
        service_dep=admin_users.get_admin_users_service,
        auth=require_portal_admin,
        result={"items": [], "page": 1, "page_size": 20, "total": 0, "has_more": False},
        fields=list(USERS_SORT_COLUMNS),
        default=USERS_DEFAULT_SORT,
        schema="AdminUserListResponse",
    ),
    "surveys": dict(
        url="/api/v1/admin/surveys",
        service_dep=admin_surveys.get_survey_admin_service,
        auth=require_portal_admin_or_hr,
        result=([], 0),
        fields=list(SURVEY_SORT_COLUMNS),
        default=SURVEY_DEFAULT_SORT,
        schema="AdminSurveyListResponse",
    ),
    "notifications": dict(
        url="/api/v1/admin/notifications",
        service_dep=admin_notifications.get_notification_admin_service,
        auth=require_portal_admin_or_hr,
        result={"items": [], "total": 0, "page": 1, "page_size": 50},
        fields=list(NOTIF_SORT_FIELDS),
        default=NOTIF_DEFAULT_SORT,
        schema="AdminNotificationListResponse",
    ),
    "ideas": dict(
        url="/api/v1/admin/ideas",
        service_dep=admin_ideas.get_idea_admin_service,
        auth=require_portal_admin_or_hr,
        result=([], 0),
        fields=list(IDEA_SORT_COLUMNS),
        default=IDEA_DEFAULT_SORT,
        schema="AdminIdeaListResponse",
    ),
}


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _setup(name: str) -> _StubService:
    cfg = ENDPOINTS[name]
    stub = _StubService(cfg["result"])
    app.dependency_overrides[cfg["auth"]] = lambda: make_korisnik(id=1, platni_broj="admin1")
    app.dependency_overrides[cfg["service_dep"]] = lambda: stub
    return stub


def _last_sort(stub: _StubService) -> SortSpec:
    return stub.calls[-1][2]["sort"]


@pytest.mark.parametrize("name", list(ENDPOINTS))
def test_no_params_uses_default_and_echoes_it(client, name):
    cfg, stub = ENDPOINTS[name], _setup(name)
    resp = client.get(cfg["url"])
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert (body["sort_by"], body["sort_dir"]) == (cfg["default"].by, cfg["default"].dir)
    assert _last_sort(stub) == cfg["default"]


@pytest.mark.parametrize("name", list(ENDPOINTS))
def test_every_column_and_direction_reaches_the_service_and_is_echoed(client, name):
    cfg, stub = ENDPOINTS[name], _setup(name)
    for field in cfg["fields"]:
        for direction in ("asc", "desc"):
            resp = client.get(cfg["url"], params={"sort_by": field, "sort_dir": direction})
            assert resp.status_code == 200, (name, field, direction, resp.text)
            assert (resp.json()["sort_by"], resp.json()["sort_dir"]) == (field, direction)
            assert _last_sort(stub) == SortSpec(field, direction)


@pytest.mark.parametrize("name", list(ENDPOINTS))
def test_sort_dir_alone_applies_to_default_column_and_sort_by_alone_is_ascending(client, name):
    cfg, stub = ENDPOINTS[name], _setup(name)
    other = "asc" if cfg["default"].dir == "desc" else "desc"
    client.get(cfg["url"], params={"sort_dir": other})
    assert _last_sort(stub) == SortSpec(cfg["default"].by, other)
    field = next(f for f in cfg["fields"] if f != cfg["default"].by)
    client.get(cfg["url"], params={"sort_by": field.upper()})
    assert _last_sort(stub) == SortSpec(field, "asc")


@pytest.mark.parametrize("name", list(ENDPOINTS))
def test_sorting_works_together_with_paging(client, name):
    cfg, stub = ENDPOINTS[name], _setup(name)
    resp = client.get(cfg["url"], params={"page": 3, "page_size": 7, "sort_by": cfg["fields"][1], "sort_dir": "desc"})
    assert resp.status_code == 200
    assert resp.json()["page"] in (1, 3)  # stub vraca fiksan page; bitno je da paging parametri prolaze validaciju
    assert _last_sort(stub) == SortSpec(cfg["fields"][1], "desc")


@pytest.mark.parametrize("name", list(ENDPOINTS))
@pytest.mark.parametrize(
    "bad",
    ["lozinka_hash", "sadrzaj", "opis", "nepoznato", "id; DROP TABLE x", "1=1", "id,naziv", "(select 1 from dual)"],
)
def test_sort_by_outside_whitelist_is_422_and_never_reaches_the_service(client, name, bad):
    cfg, stub = ENDPOINTS[name], _setup(name)
    resp = client.get(cfg["url"], params={"sort_by": bad})
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"
    assert "Dozvoljeno:" in resp.json()["error"]["message"]
    assert stub.calls == []


@pytest.mark.parametrize("name", list(ENDPOINTS))
@pytest.mark.parametrize("bad", ["up", "ascending", "asc,desc", "0", "desc; --"])
def test_invalid_sort_dir_is_422(client, name, bad):
    cfg, stub = ENDPOINTS[name], _setup(name)
    resp = client.get(cfg["url"], params={"sort_by": cfg["fields"][0], "sort_dir": bad})
    assert resp.status_code == 422 and resp.json()["error"]["code"] == "VALIDATION_ERROR"
    assert stub.calls == []


@pytest.mark.parametrize("name", list(ENDPOINTS))
def test_blank_params_from_datatable_are_ignored(client, name):
    cfg, stub = ENDPOINTS[name], _setup(name)
    resp = client.get(cfg["url"], params={"sort_by": "", "sort_dir": ""})
    assert resp.status_code == 200 and _last_sort(stub) == cfg["default"]


@pytest.mark.parametrize("name", list(ENDPOINTS))
def test_openapi_documents_sort_enum_and_response_fields(name):
    cfg = ENDPOINTS[name]
    spec = app.openapi()
    params = {p["name"]: p for p in spec["paths"][cfg["url"].replace("/api/v1", "/api/v1")]["get"]["parameters"]}
    assert params["sort_by"]["schema"]["enum"] == cfg["fields"]
    assert params["sort_dir"]["schema"]["enum"] == ["asc", "desc"]
    assert cfg["default"].by in params["sort_by"]["description"]
    props = spec["components"]["schemas"][cfg["schema"]]["properties"]
    assert {"sort_by", "sort_dir"} <= set(props)
    assert props["sort_dir"]["enum"] == ["asc", "desc"]


def test_existing_filters_and_paging_parameters_are_unchanged():
    spec = app.openapi()["paths"]
    expected = {
        "/api/v1/admin/users": {"page", "page_size", "search", "status_zaposlenja", "status_naloga",
                                "zakljucan", "uloga", "orgjed"},
        "/api/v1/admin/surveys": {"status", "tip", "datum_od", "datum_do", "page", "page_size"},
        "/api/v1/admin/notifications": {"page", "page_size", "status", "category", "datum_od", "datum_do"},
        "/api/v1/admin/ideas": {"cycle_id", "status", "korisnik_id", "platni_broj", "page", "page_size"},
    }
    for url, names in expected.items():
        got = {p["name"] for p in spec[url]["get"]["parameters"] if p["in"] == "query"}
        assert got == names | {"sort_by", "sort_dir"}, url


def test_idea_repository_module_exposes_the_whitelist():
    assert idea_repository.IDEA_SORT_COLUMNS is IDEA_SORT_COLUMNS
