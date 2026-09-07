import asyncio
import json
from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
import redis.asyncio as aioredis
import structlog

from app.core.config import settings
from app.core.security import CurrentTenantUser, get_current_tenant_user

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/realtime", tags=["Realtime Streaming"])


@router.get("/stream")
async def sse_event_stream(
    request: Request,
    user: CurrentTenantUser = Depends(get_current_tenant_user),
):
    """
    Server-Sent Events (SSE) stream subscribed to organization channel.
    Crucial: Does NOT hold open a PostgreSQL database session.
    """
    async def event_generator():
        channel_name = f"channel:events:{user.organization_id}"
        redis_client = None
        pubsub = None

        try:
            redis_client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
            pubsub = redis_client.pubsub()
            await pubsub.subscribe(channel_name)
            yield f": connected to {channel_name}\n\n"

            while True:
                if await request.is_disconnected():
                    break

                try:
                    message = await asyncio.wait_for(
                        pubsub.get_message(ignore_subscribe_messages=True),
                        timeout=5.0
                    )
                    if message and message.get("type") == "message":
                        data = message["data"]
                        yield f"data: {data}\n\n"
                    else:
                        yield ": ping\n\n"
                except asyncio.TimeoutError:
                    yield ": ping\n\n"

        except Exception as e:
            # Fallback if Redis is unreachable in minimal dev mode: keep alive with pings
            logger.warning("redis_pubsub_unavailable", error=str(e))
            yield f": redis offline, running in heartbeat mode\n\n"
            while True:
                if await request.is_disconnected():
                    break
                await asyncio.sleep(5)
                yield ": ping\n\n"
        finally:
            if pubsub:
                await pubsub.unsubscribe(channel_name)
                await pubsub.close()
            if redis_client:
                await redis_client.aclose()

    return StreamingResponse(event_generator(), media_type="text/event-stream")
