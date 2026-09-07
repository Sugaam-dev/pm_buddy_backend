import asyncio
from datetime import datetime, timezone
import json
from typing import Any
from uuid import UUID, uuid4
import redis.asyncio as aioredis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from app.core.config import settings
from app.models.entities import OutboxEvent

logger = structlog.get_logger(__name__)


class OutboxService:
    @staticmethod
    def create_event(
        session: AsyncSession,
        organization_id: UUID,
        event_type: str,
        aggregate_type: str,
        aggregate_id: UUID,
        payload: dict[str, Any],
    ) -> OutboxEvent:
        """
        Creates an OutboxEvent inside the current active database transaction.
        Must be committed by the caller in the same ACID transaction.
        """
        event = OutboxEvent(
            id=uuid4(),
            organization_id=organization_id,
            event_type=event_type,
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            payload=payload,
            status="PENDING",
            retry_count=0,
        )
        session.add(event)
        return event


class OutboxDispatcher:
    """
    Asynchronous Outbox Dispatcher Worker.
    Uses SELECT ... FOR UPDATE SKIP LOCKED to ensure:
    1. Safe concurrent multi-worker execution without duplicate claims.
    2. Guaranteed at-least-once delivery to Redis Pub/Sub.
    3. Failure tolerance with retry tracking and error recording.
    """

    MAX_RETRIES = 5

    @classmethod
    async def process_batch(
        cls,
        session: AsyncSession,
        redis_client: Any,
        batch_size: int = 50,
    ) -> dict[str, int]:
        processed_count = 0
        published_count = 0
        failed_count = 0

        # Concurrency-safe query using SKIP LOCKED
        stmt = (
            select(OutboxEvent)
            .where(OutboxEvent.status == "PENDING")
            .order_by(OutboxEvent.created_at.asc())
            .limit(batch_size)
            .with_for_update(skip_locked=True)
        )

        result = await session.execute(stmt)
        events = result.scalars().all()

        if not events:
            return {"processed": 0, "published": 0, "failed": 0}

        now = datetime.now(timezone.utc)

        for event in events:
            processed_count += 1
            channel_name = f"channel:events:{event.organization_id}"
            message_payload = json.dumps({
                "event_id": str(event.id),
                "organization_id": str(event.organization_id),
                "event_type": event.event_type,
                "aggregate_type": event.aggregate_type,
                "aggregate_id": str(event.aggregate_id),
                "payload": event.payload,
                "created_at": event.created_at.isoformat() if event.created_at else now.isoformat(),
            })

            try:
                # Attempt Redis publish
                await redis_client.publish(channel_name, message_payload)

                # Update status strictly AFTER successful publish
                event.status = "PUBLISHED"
                event.published_at = datetime.now(timezone.utc)
                event.last_error = None
                published_count += 1
                logger.info("outbox_event_published", event_id=str(event.id), channel=channel_name)

            except Exception as e:
                failed_count += 1
                event.retry_count = (event.retry_count or 0) + 1
                event.last_error = str(e)
                logger.warning(
                    "outbox_event_publish_failed",
                    event_id=str(event.id),
                    retry=event.retry_count,
                    error=str(e),
                )
                if event.retry_count >= cls.MAX_RETRIES:
                    event.status = "FAILED"

        await session.commit()
        return {
            "processed": processed_count,
            "published": published_count,
            "failed": failed_count,
        }

    @classmethod
    async def run_loop(
        cls,
        session_factory: Any,
        redis_url: str | None = None,
        poll_interval: float = 1.0,
        stop_event: asyncio.Event | None = None,
    ):
        redis_url = redis_url or settings.REDIS_URL
        redis_client = None

        logger.info("outbox_dispatcher_started", poll_interval=poll_interval)
        try:
            redis_client = aioredis.from_url(redis_url, decode_responses=True)
            while stop_event is None or not stop_event.is_set():
                try:
                    async with session_factory() as session:
                        res = await cls.process_batch(session, redis_client)
                        if res["processed"] > 0:
                            logger.debug("outbox_batch_processed", **res)
                except Exception as e:
                    logger.error("outbox_batch_cycle_error", error=str(e))

                await asyncio.sleep(poll_interval)
        finally:
            if redis_client:
                await redis_client.aclose()
            logger.info("outbox_dispatcher_stopped")
