import pytest
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4
from fastapi import HTTPException

from app.core.database import AsyncSessionLocal
from app.services.calendar_service import CalendarService
from app.models.entities import CalendarEvent, AuditLog, OutboxEvent
from sqlalchemy import select


@pytest.mark.asyncio
async def test_calendar_slots_finder():
    async with AsyncSessionLocal() as session:
        org_id = UUID("11111111-1111-1111-1111-111111111111")
        target_date = datetime(2026, 9, 8, 10, 0, 0, tzinfo=timezone.utc)
        slots = await CalendarService.find_available_slots(
            session=session,
            organization_id=org_id,
            attendee_emails=["alice@acme.com", "rahul@acme.com"],
            duration_minutes=30,
            search_date=target_date,
        )

        assert isinstance(slots, list)
        assert len(slots) > 0
        for slot in slots:
            assert "start_time" in slot
            assert "end_time" in slot
            assert slot["is_available"] is True
            assert slot["duration_minutes"] == 30


@pytest.mark.asyncio
async def test_calendar_event_lifecycle_crud():
    async with AsyncSessionLocal() as session:
        org_id = UUID("11111111-1111-1111-1111-111111111111")
        user_id = UUID("10000000-0000-0000-0000-000000000001")
        start = datetime.now(timezone.utc) + timedelta(days=2, hours=1)
        end = start + timedelta(minutes=45)

        # 1. Create Event
        created = await CalendarService.create_event(
            session=session,
            organization_id=org_id,
            title="Q3 Strategic Architecture Review",
            description="Discussion on event sourcing and transactional outbox",
            start_time=start,
            end_time=end,
            attendees=["alice@acme.com", "charlie@acme.com"],
            user_id=user_id,
        )
        await session.commit()

        event_id = UUID(created["id"])
        assert created["title"] == "Q3 Strategic Architecture Review"
        assert len(created["participants"]) == 2
        assert created["status"] == "confirmed"

        # Verify Audit Log was recorded
        audit = (await session.execute(
            select(AuditLog).where(
                AuditLog.organization_id == org_id,
                AuditLog.target_id == event_id,
                AuditLog.action == "CALENDAR_EVENT_CREATED"
            )
        )).scalar_one_or_none()
        assert audit is not None
        assert audit.result == "SUCCESS"

        # Verify Transactional Outbox was recorded
        outbox = (await session.execute(
            select(OutboxEvent).where(
                OutboxEvent.organization_id == org_id,
                OutboxEvent.aggregate_id == event_id,
                OutboxEvent.event_type == "CALENDAR_EVENT_SCHEDULED"
            )
        )).scalar_one_or_none()
        assert outbox is not None
        assert outbox.status == "PENDING"

        # 2. Get Event by ID
        fetched = await CalendarService.get_event_by_id(session, org_id, event_id)
        assert fetched["id"] == str(event_id)
        assert fetched["title"] == "Q3 Strategic Architecture Review"

        # 3. Update Event
        new_start = start + timedelta(hours=1)
        new_end = new_start + timedelta(minutes=45)
        updated = await CalendarService.update_event(
            session=session,
            organization_id=org_id,
            event_id=event_id,
            updates={
                "title": "Rescheduled: Q3 Strategic Architecture Review",
                "start_time": new_start.isoformat(),
                "end_time": new_end.isoformat(),
            },
            user_id=user_id,
        )
        await session.commit()
        assert updated["title"] == "Rescheduled: Q3 Strategic Architecture Review"

        # 4. Cancel Event
        cancelled = await CalendarService.cancel_event(
            session=session,
            organization_id=org_id,
            event_id=event_id,
            user_id=user_id,
            reason="Project milestone rescheduled",
        )
        await session.commit()
        assert cancelled["status"] == "cancelled"

        # Verify final status
        final = await CalendarService.get_event_by_id(session, org_id, event_id)
        assert final["status"] == "cancelled"


@pytest.mark.asyncio
async def test_calendar_invalid_times():
    async with AsyncSessionLocal() as session:
        org_id = UUID("11111111-1111-1111-1111-111111111111")
        now = datetime.now(timezone.utc)
        # start after end should raise 400
        with pytest.raises(HTTPException) as exc_info:
            await CalendarService.create_event(
                session=session,
                organization_id=org_id,
                title="Invalid Time Meeting",
                description="",
                start_time=now + timedelta(hours=2),
                end_time=now + timedelta(hours=1),
                attendees=["alice@acme.com"],
            )
        assert exc_info.value.status_code == 400
