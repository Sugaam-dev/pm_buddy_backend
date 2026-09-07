import asyncio
import structlog
from arq.connections import RedisSettings

from app.core.config import settings

logger = structlog.get_logger(__name__)


async def startup(ctx):
    logger.info("arq_worker_startup", env=settings.ENVIRONMENT)


async def shutdown(ctx):
    logger.info("arq_worker_shutdown")


async def ingest_document_task(ctx, document_id: str, organization_id: str):
    logger.info("ingest_document_task_started", doc_id=document_id, org_id=organization_id)
    # Simulates text chunking and vector embedding generation into pgvector
    await asyncio.sleep(1)
    logger.info("ingest_document_task_completed", doc_id=document_id)
    return {"status": "success", "document_id": document_id}


async def scan_sla_task(ctx, organization_id: str):
    logger.info("scan_sla_task_executed", org_id=organization_id)
    return {"status": "scanned", "organization_id": organization_id}


class WorkerSettings:
    redis_settings = RedisSettings.from_dsn(settings.REDIS_URL)
    functions = [ingest_document_task, scan_sla_task]
    on_startup = startup
    on_shutdown = shutdown


if __name__ == "__main__":
    from arq import run_worker
    run_worker(WorkerSettings)
