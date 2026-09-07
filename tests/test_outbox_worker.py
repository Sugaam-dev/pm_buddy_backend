import asyncio
from datetime import datetime, timezone
import json
import pytest
from uuid import uuid4

from app.models.entities import OutboxEvent
from app.services.outbox_service import OutboxDispatcher, OutboxService


class MockRedis:
    def __init__(self, should_fail: bool = False):
        self.should_fail = should_fail
        self.published_messages: list[tuple[str, str]] = []

    async def publish(self, channel: str, message: str):
        if self.should_fail:
            raise ConnectionError("Redis cluster unreachable")
        self.published_messages.append((channel, message))
        return 1


class MockAsyncSession:
    def __init__(self, events: list[OutboxEvent]):
        self.events = events
        self.committed = False

    async def execute(self, stmt):
        class Result:
            def __init__(self, items):
                self.items = items
            def scalars(self):
                class Scalars:
                    def __init__(self, items):
                        self.items = items
                    def all(self):
                        # Filter PENDING
                        return [e for e in self.items if e.status == "PENDING"]
                return Scalars(self.items)
        return Result(self.events)

    async def commit(self):
        self.committed = True


@pytest.mark.asyncio
async def test_outbox_case_a_successful_publication():
    """Case A: PENDING -> Redis publish succeeds -> PUBLISHED."""
    org_id = uuid4()
    event = OutboxEvent(
        id=uuid4(),
        organization_id=org_id,
        event_type="APPROVAL_SLA_BREACHED",
        aggregate_type="approval",
        aggregate_id=uuid4(),
        payload={"project_id": "p1", "days_overdue": 3},
        status="PENDING",
        retry_count=0,
        created_at=datetime.now(timezone.utc),
    )

    session = MockAsyncSession([event])
    redis = MockRedis(should_fail=False)

    result = await OutboxDispatcher.process_batch(session, redis, batch_size=10)

    assert result["processed"] == 1
    assert result["published"] == 1
    assert result["failed"] == 0
    assert event.status == "PUBLISHED"
    assert event.published_at is not None
    assert event.last_error is None
    assert session.committed is True

    # Verify Redis channel and payload structure
    assert len(redis.published_messages) == 1
    channel, payload_str = redis.published_messages[0]
    assert channel == f"channel:events:{org_id}"
    parsed = json.loads(payload_str)
    assert parsed["event_type"] == "APPROVAL_SLA_BREACHED"
    assert parsed["organization_id"] == str(org_id)


@pytest.mark.asyncio
async def test_outbox_case_b_redis_failure_retry_increment():
    """Case B: Redis unavailable -> event remains PENDING, retry_count increments, last_error recorded."""
    org_id = uuid4()
    event = OutboxEvent(
        id=uuid4(),
        organization_id=org_id,
        event_type="TASK_BLOCKED",
        aggregate_type="task",
        aggregate_id=uuid4(),
        payload={"task_id": "t1"},
        status="PENDING",
        retry_count=1,
        created_at=datetime.now(timezone.utc),
    )

    session = MockAsyncSession([event])
    redis = MockRedis(should_fail=True)

    result = await OutboxDispatcher.process_batch(session, redis, batch_size=10)

    assert result["processed"] == 1
    assert result["published"] == 0
    assert result["failed"] == 1
    assert event.status == "PENDING"  # Remains pending for next cycle
    assert event.retry_count == 2
    assert "Redis cluster unreachable" in event.last_error
    assert session.committed is True


@pytest.mark.asyncio
async def test_outbox_case_c_max_retries_transition_to_failed():
    """Case C: Repeated failures exceeding MAX_RETRIES transition to FAILED."""
    org_id = uuid4()
    event = OutboxEvent(
        id=uuid4(),
        organization_id=org_id,
        event_type="TICKET_ESCALATED",
        aggregate_type="ticket",
        aggregate_id=uuid4(),
        payload={},
        status="PENDING",
        retry_count=4,  # Next failure will hit max 5
        created_at=datetime.now(timezone.utc),
    )

    session = MockAsyncSession([event])
    redis = MockRedis(should_fail=True)

    result = await OutboxDispatcher.process_batch(session, redis, batch_size=10)

    assert event.status == "FAILED"
    assert event.retry_count == 5
    assert event.last_error is not None


@pytest.mark.asyncio
async def test_outbox_case_d_multiple_events_batch_processing():
    """Case D: Multiple pending events processed in batch."""
    org_id = uuid4()
    events = [
        OutboxEvent(
            id=uuid4(),
            organization_id=org_id,
            event_type=f"EVENT_{i}",
            aggregate_type="test",
            aggregate_id=uuid4(),
            payload={"index": i},
            status="PENDING",
            retry_count=0,
            created_at=datetime.now(timezone.utc),
        )
        for i in range(5)
    ]

    session = MockAsyncSession(events)
    redis = MockRedis(should_fail=False)

    result = await OutboxDispatcher.process_batch(session, redis, batch_size=10)

    assert result["processed"] == 5
    assert result["published"] == 5
    assert all(e.status == "PUBLISHED" for e in events)
    assert len(redis.published_messages) == 5
