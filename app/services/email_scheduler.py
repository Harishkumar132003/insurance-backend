import logging

from apscheduler.schedulers.background import BackgroundScheduler

from app.services.email_reader_service import process_unread_emails

logger = logging.getLogger(__name__)

scheduler = BackgroundScheduler()


def start_email_scheduler():
    """Start the background email reader scheduler."""
    scheduler.add_job(
        process_unread_emails,
        "interval",
        minutes=1,
        id="email_reader",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("Email reader scheduler started — checking every 2 minutes")


def stop_email_scheduler():
    """Stop the background email reader scheduler."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Email reader scheduler stopped")
