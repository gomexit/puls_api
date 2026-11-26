"""PULS IZAZOV: SQL skripta 011, Oracle upiti repozitorijuma i push dogadjaji."""

import datetime
import pathlib

from sqlalchemy.dialects import oracle

from app.models.kviz import Kviz
from app.repositories.quiz_repository import QuizRepository
from app.repositories.system_event_repository import SystemEventRepository
from app.services.notification_publishing_service import NotificationPublishingService
from app.services.system_notification_service import SystemNotificationService
from tests.fakes import FakeAuditService
from tests.notification_fakes import (
    FakeConfigService,
    FakeNotifDb,
    FakeNotificationRepo,
    FakeNotificationTargetingRepo,
    FakePushDeliveryRepo,
    make_kategorija,
)
from tests.system_notification_fakes import (
    FakeAutomationRepo,
    FakeOnboardingAssignmentService,
    FakeSystemEventRepo,
)

SQL_011 = pathlib.Path(__file__).resolve().parents[1] / "sql" / "011_kviz_module.sql"
NOW = datetime.datetime(2026, 12, 1, 10, 0, 0)


# ================================================================ SQL skripta
def test_sql_011_is_additive_and_complete():
    sql = SQL_011.read_text(encoding="utf-8")
    code = "\n".join(line.split("--", 1)[0] for line in sql.splitlines())
    upper = code.upper()
    for forbidden in ("DROP ", "DELETE FROM", "TRUNCATE", "ALTER TABLE", "HR.", "IIS."):
        assert forbidden not in upper
    for table in (
        "PULS_KVIZ_KATEGORIJE", "PULS_KVIZOVI", "PULS_KVIZ_CILJEVI", "PULS_KVIZ_PITANJA",
        "PULS_KVIZ_OPCIJE", "PULS_KVIZ_POKUSAJI", "PULS_KVIZ_ODGOVORI",
    ):
        assert f"CREATE TABLE {table}" in upper
    assert "UNIQUE (KVIZ_ID, KORISNIK_ID)" in upper
    assert "NVARCHAR2" in upper  # korisnicki tekst (EE8ISO8859P2)
    assert upper.rstrip().endswith("COMMIT;")


# ================================================================ Oracle upiti
class _Result:
    def all(self):
        return []

    def one(self):
        return (0, None)

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
        self.sql: list[str] = []

    def execute(self, stmt):
        self.sql.append(str(stmt.compile(dialect=oracle.dialect())).upper())
        return _Result()

    def add(self, obj):
        pass

    def flush(self):
        pass


def test_quiz_repository_compiles_for_oracle_and_reads_only_puls_tables():
    db = _CompileDb()
    repo = QuizRepository(db)
    repo.list_categories("D")
    repo.active_category_codes(["OPSTE"])
    repo.active_image_ids([1])
    repo.list_admin("OBJAVLJEN", "kviz", 1, 20)
    repo.question_counts([1])
    repo.get_for_update(1)
    repo.find_overlapping_published(NOW, NOW, 1)
    repo.find_open_published(NOW)
    repo.get_options([1])
    repo.replace_targets(1, [("ORGJED", "318")])
    repo.replace_questions(1, [])
    repo.primary_orgjed(1)
    repo.get_attempt_by_id_for_update(1)
    repo.orgjed_average(1, "318")
    repo.attempt_totals(1)
    repo.orgjed_stats(1)
    repo.question_stats(1)
    joined = "\n".join(db.sql)
    assert "HR." not in joined and "IIS." not in joined and "SELECT *" not in joined
    assert "SADRZAJ" not in joined  # slika se nikad ne cita kao BLOB
    assert "FOR UPDATE" in joined


def test_system_event_quiz_queries_compile():
    db = _CompileDb()
    repo = SystemEventRepository(db)
    repo.find_quizzes_now_active(NOW)
    repo.find_quizzes_expiring_within(NOW, NOW)
    repo.quiz_targets(1)
    repo.quiz_finished_user_ids(1)
    assert all("PULS_KVIZ" in s for s in db.sql)


# ================================================================ push dogadjaji
def _service(config):
    event_repo = FakeSystemEventRepo()
    notif_repo = FakeNotificationRepo()
    notif_repo.add_category(make_kategorija(sifra="SISTEM", naziv="Sistemsko"))
    targeting = FakeNotificationTargetingRepo(
        all_ids={1, 2, 3, 4}, by_orgjed={"318": {1, 2}, "401": {3}}, by_platni={"P4": 4}
    )
    cfg = FakeConfigService(config)
    publishing = NotificationPublishingService(
        db=FakeNotifDb(), repository=notif_repo, targeting_repository=targeting,
        audit_service=FakeAuditService(), configuration_service=cfg,
        push_delivery_repository=FakePushDeliveryRepo(), now_fn=lambda: NOW,
    )
    svc = SystemNotificationService(
        db=FakeNotifDb(), event_repository=event_repo, targeting_repository=targeting,
        publishing_service=publishing, configuration_service=cfg,
        onboarding_assignment_service=FakeOnboardingAssignmentService(),
        automation_repository=FakeAutomationRepo(), now_fn=lambda: NOW,
    )
    return svc, event_repo, notif_repo


def _kviz(id=7, od=NOW - datetime.timedelta(hours=1), do=NOW + datetime.timedelta(hours=10)):
    return Kviz(id=id, naziv="Izazov", status="OBJAVLJEN", datum_od=od, datum_do=do, trajanje_sekundi=120)


def test_quiz_events_discovered_and_targeted():
    svc, events, _ = _service({"MODUL_KVIZ": "SVI"})
    events.seed_quiz(_kviz(), targets=[("ORGJED", "318"), ("PLATNI_BROJ", "P4")], finished={2})
    assert svc.discover_events()["discovered"] == 2  # ACTIVATED + EXPIRING (rok za 10 h)
    assert svc.discover_events()["discovered"] == 0  # idempotentno
    tipovi = sorted(e.tip_dogadjaja for e in events.events.values())
    assert tipovi == ["QUIZ_ACTIVATED", "QUIZ_EXPIRING"]

    recipients = {}
    for e in events.events.values():
        rcpt, content = svc._resolve(e, NOW)
        recipients[e.tip_dogadjaja] = rcpt
        assert content["akcija_tip"] == "QUIZ" and content["resurs_id"] == 7
    assert recipients["QUIZ_ACTIVATED"] == {1, 2, 4}
    assert recipients["QUIZ_EXPIRING"] == {1, 4}  # 2 je vec zavrsio

    summary = svc.process_batch(10)
    assert summary["published"] == 2


def test_quiz_events_respect_module_mode_and_stale_deadline():
    svc, events, _ = _service({"MODUL_KVIZ": "PILOT", "MODUL_PILOT_ORGJED": "401"})
    kviz = events.seed_quiz(_kviz())
    svc.enqueue_quiz_activated(7)
    event = next(iter(events.events.values()))
    assert svc._resolve(event, NOW)[0] == {3}

    svc_off, events_off, _ = _service({"MODUL_KVIZ": "ISKLJUCEN"})
    events_off.seed_quiz(_kviz())
    svc_off.enqueue_quiz_activated(7)
    assert svc_off.process_batch(10)["skipped"] == 1

    svc.enqueue_quiz_expiring(7, kviz.datum_do)
    kviz.datum_do = kviz.datum_do + datetime.timedelta(days=1)  # produzen rok
    stale = next(e for e in events.events.values() if e.tip_dogadjaja == "QUIZ_EXPIRING")
    assert svc._resolve(stale, NOW) == (None, None)


def test_discovery_skips_quiz_tables_while_module_is_off():
    svc, events, _ = _service({"MODUL_KVIZ": "ISKLJUCEN"})
    events.seed_quiz(_kviz())
    assert svc.discover_events()["discovered"] == 0
    assert events.events == {}
