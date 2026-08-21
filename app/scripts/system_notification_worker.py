"""Zaseban system notification worker: python -m app.scripts.system_notification_worker

Obradjuje PULS_SISTEMSKI_DOGADJAJI (SURVEY_ACTIVATED/EXPIRING, IDEA_CYCLE_ACTIVATED/
EXPIRING, IDEA_TOP_10/NAGRADJENA, APP_VERSION_CHANGED): materijalizuje sistemsko
PUBLISHED obavestenje u Oracle Inbox (izvor istine) + PENDING redove u postojecem
FCM outbox-u (PULS_PUSH_ISPORUKE - salje ih zaseban push_worker, ne ovaj proces).

Jedna instanca procesa je deployment pravilo (bez Redis/Celery/scheduler-a u web
procesu, BlockingScheduler kao i kod push_worker/provision_worker). Izvrsava posao
odmah pri startu, a zatim na fiksnom intervalu. NE pokrece se iz app/main.py."""

import datetime
import logging

from apscheduler.schedulers.blocking import BlockingScheduler

from app.core.config import get_settings
from app.core.logging import setup_logging
from app.db.session import SessionLocal
from app.services.system_notification_service import SystemNotificationService

logger = logging.getLogger("puls.system_notifications")

SYSTEM_NOTIFICATION_JOB_ID = "puls_system_notifications"


def run_system_notification_batch(settings) -> None:
    db = SessionLocal()
    try:
        service = SystemNotificationService(db, max_attempts=settings.sys_notification_max_attempts)
        # 1) Otkrij dogadjaje koje nije trigerovao direktan admin/servisni poziv
        #    (SCHEDULED anketa koja je vremenom postala dostupna, 24h podsetnici).
        discovery_summary = service.discover_events()
        # 2) Obradi PENDING dogadjaje - materijalizuj obavestenje/push redove.
        process_summary = service.process_batch(settings.sys_notification_batch_size)
        logger.info(
            "Sistemski dogadjaji obradjeni: discovery=%s, batch=%s", discovery_summary, process_summary
        )
    finally:
        db.close()


def main() -> None:
    setup_logging()
    settings = get_settings()

    scheduler = BlockingScheduler(timezone="Europe/Belgrade")
    scheduler.add_job(
        run_system_notification_batch,
        trigger="interval",
        seconds=settings.sys_notification_worker_interval_seconds,
        id=SYSTEM_NOTIFICATION_JOB_ID,
        max_instances=1,
        coalesce=True,
        # Izvrsi posao odmah na startu (ne cekaj prvi interval), pa zatim po intervalu.
        next_run_time=datetime.datetime.now(),
        args=[settings],
    )
    logger.info(
        "System notification worker started (interval=%ds, batch=%d). Ctrl+C to stop.",
        settings.sys_notification_worker_interval_seconds,
        settings.sys_notification_batch_size,
    )
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("System notification worker stopped.")


if __name__ == "__main__":
    main()
