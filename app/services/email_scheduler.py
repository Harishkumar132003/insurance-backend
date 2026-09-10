import logging

from apscheduler.schedulers.background import BackgroundScheduler

from app.services.email_reader_service import process_unread_emails

logger = logging.getLogger(__name__)

scheduler = BackgroundScheduler()


# Minutes between inbox checks. Each unread email costs one OpenAI round trip
# and they are handled sequentially, so a backlog can legitimately outlast one
# interval; see max_instances below.
EMAIL_POLL_MINUTES = 1


def start_email_scheduler():
    """Start the background email reader scheduler."""
    scheduler.add_job(
        process_unread_emails,
        "interval",
        minutes=EMAIL_POLL_MINUTES,
        id="email_reader",
        replace_existing=True,
        # Never run two inbox sweeps at once — they would race on the same
        # UNSEEN messages and double-process them. This was already the
        # APScheduler default; stating it makes the "maximum number of running
        # instances reached (1)" warning self-explanatory instead of looking
        # like a fault.
        max_instances=1,
        # A tick that arrives while the previous run is still going is dropped
        # rather than queued, so we never build up a backlog of sweeps.
        coalesce=True,
        misfire_grace_time=30,
    )
    scheduler.start()
    logger.info(
        "Email reader scheduler started — checking every %s minute(s)",
        EMAIL_POLL_MINUTES,
    )


def stop_email_scheduler():
    """Stop the background email reader scheduler."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Email reader scheduler stopped")
