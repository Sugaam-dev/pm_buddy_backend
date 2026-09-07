import asyncio
import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import redis.asyncio as aioredis

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.services.outbox_service import OutboxDispatcher

logger = structlog.get_logger(__name__)


async def run_outbox_dispatcher_job():
    """Polls and dispatches pending outbox events to Redis."""
    redis_client = None
    try:
        redis_client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        async with AsyncSessionLocal() as session:
            await OutboxDispatcher.process_batch(session, redis_client, batch_size=50)
    except Exception as e:
        logger.warning("outbox_dispatcher_job_error", error=str(e))
    finally:
        if redis_client:
            await redis_client.aclose()


async def run_sla_check_job():
    logger.info("scheduler_executing_sla_scan")
    # SLA periodic scan logic


async def run_prediction_refresh_job():
    logger.info("scheduler_refreshing_predictions")


def start_scheduler():
    scheduler = AsyncIOScheduler()
    # Outbox dispatcher runs every 2 seconds for low-latency delivery
    scheduler.add_job(run_outbox_dispatcher_job, "interval", seconds=2, id="outbox_dispatcher")
    # SLA Scanner runs every 2 minutes
    scheduler.add_job(run_sla_check_job, "interval", minutes=2, id="sla_scanner")
    # Prediction recalculation runs hourly
    scheduler.add_job(run_prediction_refresh_job, "interval", hours=1, id="prediction_refresh")
    
    scheduler.start()
    logger.info(
        "apscheduler_started",
        jobs=["outbox_dispatcher", "sla_scanner", "prediction_refresh"],
    )

    loop = asyncio.get_event_loop()
    try:
        loop.run_forever()
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()


if __name__ == "__main__":
    start_scheduler()
