"""Optional always-on host scheduler for the current desk; Actions is the cloud default."""
import logging

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from app.services.daily_update import run
from app.services.jobs import backup_database

logging.basicConfig(level=logging.INFO)


def main() -> None:
    scheduler = BlockingScheduler(timezone="UTC")
    scheduler.add_job(run, CronTrigger(day_of_week="mon-fri", hour=19, minute=15,
                                      timezone="America/New_York"),
                      kwargs={"sync_quotes": True}, id="daily_desk", max_instances=1,
                      coalesce=True, misfire_grace_time=3600)
    scheduler.add_job(backup_database, CronTrigger(hour=3, minute=30, timezone="UTC"),
                      id="daily_backup", max_instances=1, coalesce=True)
    logging.info("Current desk scheduler started; no legacy strategy or actual trading jobs")
    scheduler.start()


if __name__ == "__main__":
    main()
