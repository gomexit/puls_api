"""Periodic provisioning worker: python -m app.scripts.provision_worker

Runs the provisioning job immediately on start and then every
PROVISIONING_INTERVAL_MINUTES. Meant to run as a single instance."""

import datetime
import logging

from apscheduler.schedulers.blocking import BlockingScheduler

from app.core.config import get_settings
from app.core.logging import setup_logging
from app.core.scheduler import PROVISIONING_JOB_ID, run_provisioning_job

logger = logging.getLogger("puls.scheduler")


def main() -> None:
    setup_logging()
    settings = get_settings()

    scheduler = BlockingScheduler(timezone="Europe/Belgrade")
    scheduler.add_job(
        run_provisioning_job,
        trigger="interval",
        minutes=settings.provisioning_interval_minutes,
        id=PROVISIONING_JOB_ID,
        max_instances=1,
        coalesce=True,
        # Run once immediately on startup, then on the interval.
        next_run_time=datetime.datetime.now(),
    )
    logger.info(
        "Provisioning worker started (interval=%d min, first run now). Ctrl+C to stop.",
        settings.provisioning_interval_minutes,
    )
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Provisioning worker stopped.")


if __name__ == "__main__":
    main()
