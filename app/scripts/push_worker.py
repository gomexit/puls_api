"""Zaseban push worker: python -m app.scripts.push_worker

Cita PENDING redove iz PULS_PUSH_ISPORUKE i salje kroz FcmProvider. Radi SAMO ako
je FCM_ENABLED=true. Jedna instanca procesa je deployment pravilo (bez Redis/Celery/
scheduler-a u web procesu). NE pokrece se iz app/main.py.

SENT = FCM prihvatio poruku (nije potvrda dostave uredjaju). Token/tajne se ne loguju."""

import logging

from apscheduler.schedulers.blocking import BlockingScheduler

from app.core.config import get_settings
from app.core.logging import setup_logging
from app.db.session import SessionLocal
from app.services.fcm_provider import get_fcm_provider
from app.services.push_service import PushDeliveryWorker

logger = logging.getLogger("puls.push")

PUSH_JOB_ID = "puls_push_delivery"


def run_push_batch(fcm_provider, settings) -> None:
    db = SessionLocal()
    try:
        worker = PushDeliveryWorker(
            db=db,
            fcm_provider=fcm_provider,
            max_attempts=settings.fcm_max_attempts,
        )
        summary = worker.process_batch(settings.fcm_batch_size)
        logger.info("Push batch obradjen: %s", summary)
    finally:
        db.close()


def main() -> None:
    setup_logging()
    settings = get_settings()

    if not settings.fcm_enabled:
        logger.info("FCM_ENABLED=false -> push worker se ne pokrece.")
        return

    # Firebase se inicijalizuje tacno jednom (kroz get_fcm_provider).
    fcm_provider = get_fcm_provider(settings)

    scheduler = BlockingScheduler(timezone="Europe/Belgrade")
    scheduler.add_job(
        run_push_batch,
        trigger="interval",
        seconds=settings.fcm_worker_interval_seconds,
        id=PUSH_JOB_ID,
        max_instances=1,
        coalesce=True,
        args=[fcm_provider, settings],
    )
    logger.info(
        "Push worker started (interval=%ds, batch=%d). Ctrl+C to stop.",
        settings.fcm_worker_interval_seconds, settings.fcm_batch_size,
    )
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Push worker stopped.")


if __name__ == "__main__":
    main()
