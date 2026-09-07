import pytest
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4
from fastapi import HTTPException
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.services.calendar_service import CalendarService
from app.services.action_service import ActionService
from app.models.entities import CalendarEvent, CalendarEventParticipant, AIAction, AuditLog, OutboxEvent
from sqlalchemy import delete


@pytest.fixture(autouse=True)
async def cleanup_test_calendar_events():
    yield
    async with AsyncSessionLocal() as session:
        await session.execute(
            delete(CalendarEvent).where(
                CalendarEvent.title.in_([
                    "Confirmed AI Strategy Session",
                    "Idempotent Sync Meeting",
                    "Meeting A (Proposed)",
                    "Interim Direct Booking Conflict",
                    "Initial Standup",
                    "Rescheduled Standup",
                ])
            )
        )
        await session.commit()



@pytest.mark.asyncio
async def test_ai_schedule_meeting_creates_proposal_without_mutation():
    """
    Test 1: Proposing a meeting creates an AIAction in WAITING_FOR_CONFIRMATION status
    with a 15-minute TTL, and does NOT mutate calendar_events.
    """
    async with AsyncSessionLocal() as session:
        org_id = UUID("11111111-1111-1111-1111-111111111111")
        conv_id = uuid4()
        user_id = UUID("10000000-0000-0000-0000-000000000001")

        before_count = len((await session.execute(
            select(CalendarEvent).where(CalendarEvent.organization_id == org_id)
        )).scalars().all())

        start = datetime.now(timezone.utc) + timedelta(days=10, hours=2)
        end = start + timedelta(minutes=30)
        meeting_payload = {
            "title": "AI Proposed Architecture Sync",
            "description": "Evaluate caching architecture",
            "start_time": start.isoformat(),
            "end_time": end.isoformat(),
            "attendee_emails": ["alice@acme.com", "rahul@acme.com"],
            "meeting_type": "architecture_review",
            "location": "Google Meet",
        }

        proposal = await ActionService.propose_action(
            session=session,
            organization_id=org_id,
            conversation_id=conv_id,
            tool_name="create_calendar_meeting",
            action_type="create_calendar_meeting",
            payload=meeting_payload,
            expires_in_minutes=15,
        )
        await session.commit()

        action_id = UUID(proposal["action_id"])
        assert proposal["status"] == "WAITING_FOR_CONFIRMATION"

        after_count = len((await session.execute(
            select(CalendarEvent).where(CalendarEvent.organization_id == org_id)
        )).scalars().all())
        assert after_count == before_count

        db_action = (await session.execute(
            select(AIAction).where(AIAction.id == action_id)
        )).scalar_one_or_none()
        assert db_action is not None
        assert db_action.status == "WAITING_FOR_CONFIRMATION"
        assert db_action.expires_at > datetime.now(timezone.utc)


@pytest.mark.asyncio
async def test_confirm_schedule_meeting_creates_event_and_audit():
    """
    Test 2: Confirming a proposed meeting executes the transaction, creating:
    - CalendarEvent (status = confirmed)
    - CalendarEventParticipant rows
    - AuditLog (CALENDAR_EVENT_CREATED)
    - OutboxEvent (CALENDAR_EVENT_SCHEDULED)
    - AIAction status = COMPLETED
    """
    async with AsyncSessionLocal() as session:
        org_id = UUID("11111111-1111-1111-1111-111111111111")
        conv_id = uuid4()
        user_id = UUID("10000000-0000-0000-0000-000000000001")

        start = datetime.now(timezone.utc) + timedelta(days=12, hours=3)
        end = start + timedelta(minutes=45)
        meeting_payload = {
            "title": "Confirmed AI Strategy Session",
            "description": "Product roadmap deep dive",
            "start_time": start.isoformat(),
            "end_time": end.isoformat(),
            "attendee_emails": ["alice@acme.com", "rahul@acme.com"],
            "meeting_type": "planning",
            "location": "Boardroom Alpha",
        }

        proposal = await ActionService.propose_action(
            session=session,
            organization_id=org_id,
            conversation_id=conv_id,
            tool_name="create_calendar_meeting",
            action_type="create_calendar_meeting",
            payload=meeting_payload,
            expires_in_minutes=15,
        )
        await session.commit()
        action_id = UUID(proposal["action_id"])

        confirm_result = await ActionService.confirm_action(
            session=session,
            organization_id=org_id,
            user_id=user_id,
            action_id=action_id,
            user_permissions=["calendar.write", "action.execute"],
        )
        await session.commit()

        assert confirm_result["status"] == "COMPLETED"
        event_id = UUID(confirm_result["result"]["id"])

        evt = (await session.execute(
            select(CalendarEvent).where(CalendarEvent.id == event_id)
        )).scalar_one_or_none()
        assert evt is not None
        assert evt.title == "Confirmed AI Strategy Session"
        assert evt.status == "confirmed"

        parts = (await session.execute(
            select(CalendarEventParticipant).where(CalendarEventParticipant.event_id == event_id)
        )).scalars().all()
        assert len(parts) == 2
        attendee_emails = {p.user_email for p in parts}
        assert "alice@acme.com" in attendee_emails
        assert "rahul@acme.com" in attendee_emails

        audit = (await session.execute(
            select(AuditLog).where(
                AuditLog.organization_id == org_id,
                AuditLog.target_id == event_id,
                AuditLog.action == "CALENDAR_EVENT_CREATED",
            )
        )).scalar_one_or_none()
        assert audit is not None
        assert audit.result == "SUCCESS"

        outbox = (await session.execute(
            select(OutboxEvent).where(
                OutboxEvent.organization_id == org_id,
                OutboxEvent.aggregate_id == event_id,
                OutboxEvent.event_type == "CALENDAR_EVENT_SCHEDULED",
            )
        )).scalar_one_or_none()
        assert outbox is not None
        assert outbox.status == "PENDING"

        db_action = (await session.execute(
            select(AIAction).where(AIAction.id == action_id)
        )).scalar_one_or_none()
        assert db_action.status == "COMPLETED"


@pytest.mark.asyncio
async def test_unconfirmed_meeting_not_created():
    """
    Test 3: An unconfirmed meeting never creates rows in calendar_events.
    """
    async with AsyncSessionLocal() as session:
        org_id = UUID("11111111-1111-1111-1111-111111111111")
        conv_id = uuid4()

        start = datetime.now(timezone.utc) + timedelta(days=14, hours=1)
        end = start + timedelta(minutes=30)
        unique_title = f"Unconfirmed Sync {uuid4().hex[:6]}"

        proposal = await ActionService.propose_action(
            session=session,
            organization_id=org_id,
            conversation_id=conv_id,
            tool_name="create_calendar_meeting",
            action_type="create_calendar_meeting",
            payload={
                "title": unique_title,
                "start_time": start.isoformat(),
                "end_time": end.isoformat(),
                "attendee_emails": ["alice@acme.com"],
            },
            expires_in_minutes=15,
        )
        await session.commit()

        found = (await session.execute(
            select(CalendarEvent).where(
                CalendarEvent.organization_id == org_id,
                CalendarEvent.title == unique_title,
            )
        )).scalar_one_or_none()
        assert found is None


@pytest.mark.asyncio
async def test_user_without_calendar_write_cannot_schedule():
    """
    Test 4: RBAC enforcement - User without 'calendar.write' permission
    cannot confirm meeting creation (HTTP 403).
    """
    async with AsyncSessionLocal() as session:
        org_id = UUID("11111111-1111-1111-1111-111111111111")
        conv_id = uuid4()
        user_id = UUID("10000000-0000-0000-0000-000000000004")

        start = datetime.now(timezone.utc) + timedelta(days=15, hours=2)
        end = start + timedelta(minutes=30)

        proposal = await ActionService.propose_action(
            session=session,
            organization_id=org_id,
            conversation_id=conv_id,
            tool_name="create_calendar_meeting",
            action_type="create_calendar_meeting",
            payload={
                "title": "Unauthorized Meeting Proposal",
                "start_time": start.isoformat(),
                "end_time": end.isoformat(),
                "attendee_emails": ["dave@acme.com"],
            },
            expires_in_minutes=15,
        )
        await session.commit()
        action_id = UUID(proposal["action_id"])

        with pytest.raises(HTTPException) as exc_info:
            await ActionService.confirm_action(
                session=session,
                organization_id=org_id,
                user_id=user_id,
                action_id=action_id,
                user_permissions=["calendar.read", "project.read"],
            )

        assert exc_info.value.status_code == 403
        assert "lacks required domain permission" in exc_info.value.detail.lower()


@pytest.mark.asyncio
async def test_cross_tenant_meeting_rejected():
    """
    Test 5: Multi-tenant isolation - scheduling with an attendee belonging
    to another organization is rejected with HTTP 400.
    """
    async with AsyncSessionLocal() as session:
        org_id = UUID("11111111-1111-1111-1111-111111111111")
        conv_id = uuid4()
        user_id = UUID("10000000-0000-0000-0000-000000000001")

        start = datetime.now(timezone.utc) + timedelta(days=16, hours=4)
        end = start + timedelta(minutes=30)

        proposal = await ActionService.propose_action(
            session=session,
            organization_id=org_id,
            conversation_id=conv_id,
            tool_name="create_calendar_meeting",
            action_type="create_calendar_meeting",
            payload={
                "title": "Cross Tenant Security Leak Test",
                "start_time": start.isoformat(),
                "end_time": end.isoformat(),
                "attendee_emails": ["alice@acme.com", "bob@globex.com"],
            },
            expires_in_minutes=15,
        )
        await session.commit()
        action_id = UUID(proposal["action_id"])

        with pytest.raises(HTTPException) as exc_info:
            await ActionService.confirm_action(
                session=session,
                organization_id=org_id,
                user_id=user_id,
                action_id=action_id,
                user_permissions=["calendar.write", "action.execute"],
            )

        assert exc_info.value.status_code == 400
        assert "cross-tenant" in exc_info.value.detail.lower()


@pytest.mark.asyncio
async def test_conflict_rechecked_on_confirmation():
    """
    Test 6: Conflict re-check at approval time - If an overlapping event was booked
    after proposal generation, confirmation aborts with HTTP 409 Conflict.
    """
    async with AsyncSessionLocal() as session:
        org_id = UUID("11111111-1111-1111-1111-111111111111")
        conv_id = uuid4()
        user_id = UUID("10000000-0000-0000-0000-000000000001")

        start = datetime.now(timezone.utc) + timedelta(days=18, hours=2)
        end = start + timedelta(minutes=45)

        proposal = await ActionService.propose_action(
            session=session,
            organization_id=org_id,
            conversation_id=conv_id,
            tool_name="create_calendar_meeting",
            action_type="create_calendar_meeting",
            payload={
                "title": "Meeting A (Proposed)",
                "start_time": start.isoformat(),
                "end_time": end.isoformat(),
                "attendee_emails": ["rahul@acme.com"],
            },
            expires_in_minutes=15,
        )
        await session.commit()
        action_id = UUID(proposal["action_id"])

        await CalendarService.create_event(
            session=session,
            organization_id=org_id,
            title="Interim Direct Booking Conflict",
            description="Direct calendar UI booking",
            start_time=start + timedelta(minutes=10),
            end_time=end + timedelta(minutes=10),
            attendees=["rahul@acme.com"],
            user_id=user_id,
        )
        await session.commit()

        with pytest.raises(HTTPException) as exc_info:
            await ActionService.confirm_action(
                session=session,
                organization_id=org_id,
                user_id=user_id,
                action_id=action_id,
                user_permissions=["calendar.write", "action.execute"],
            )

        assert exc_info.value.status_code == 409
        assert "scheduling conflict detected" in exc_info.value.detail.lower()

        db_action = (await session.execute(
            select(AIAction).where(AIAction.id == action_id)
        )).scalar_one_or_none()
        assert db_action.status == "FAILED"


@pytest.mark.asyncio
async def test_duplicate_confirmation_is_idempotent():
    """
    Test 7: Confirming an already completed action returns the existing result
    without creating duplicate events.
    """
    async with AsyncSessionLocal() as session:
        org_id = UUID("11111111-1111-1111-1111-111111111111")
        conv_id = uuid4()
        user_id = UUID("10000000-0000-0000-0000-000000000001")

        start = datetime.now(timezone.utc) + timedelta(days=20, hours=1)
        end = start + timedelta(minutes=30)

        proposal = await ActionService.propose_action(
            session=session,
            organization_id=org_id,
            conversation_id=conv_id,
            tool_name="create_calendar_meeting",
            action_type="create_calendar_meeting",
            payload={
                "title": "Idempotent Sync Meeting",
                "start_time": start.isoformat(),
                "end_time": end.isoformat(),
                "attendee_emails": ["alice@acme.com"],
            },
            expires_in_minutes=15,
        )
        await session.commit()
        action_id = UUID(proposal["action_id"])

        first_res = await ActionService.confirm_action(
            session=session,
            organization_id=org_id,
            user_id=user_id,
            action_id=action_id,
            user_permissions=["calendar.write", "action.execute"],
        )
        await session.commit()
        assert first_res["status"] == "COMPLETED"
        event_id = first_res["result"]["id"]

        second_res = await ActionService.confirm_action(
            session=session,
            organization_id=org_id,
            user_id=user_id,
            action_id=action_id,
            user_permissions=["calendar.write", "action.execute"],
        )
        assert second_res["status"] == "COMPLETED"
        assert second_res["result"]["id"] == event_id

        events = (await session.execute(
            select(CalendarEvent).where(
                CalendarEvent.organization_id == org_id,
                CalendarEvent.title == "Idempotent Sync Meeting",
            )
        )).scalars().all()
        assert len(events) == 1


@pytest.mark.asyncio
async def test_ai_update_and_cancel_meeting_hitl():
    """
    Test 8: Meeting update and cancellation via AI propose actions and confirm.
    """
    async with AsyncSessionLocal() as session:
        org_id = UUID("11111111-1111-1111-1111-111111111111")
        conv_id = uuid4()
        user_id = UUID("10000000-0000-0000-0000-000000000001")

        start = datetime.now(timezone.utc) + timedelta(days=22, hours=1)
        end = start + timedelta(minutes=30)

        evt = await CalendarService.create_event(
            session=session,
            organization_id=org_id,
            title="Initial Standup",
            description="",
            start_time=start,
            end_time=end,
            attendees=["alice@acme.com"],
            user_id=user_id,
        )
        await session.commit()
        event_id = UUID(evt["id"])

        new_start = start + timedelta(hours=2)
        new_end = new_start + timedelta(minutes=30)
        upd_prop = await ActionService.propose_action(
            session=session,
            organization_id=org_id,
            conversation_id=conv_id,
            tool_name="update_calendar_meeting",
            action_type="update_calendar_meeting",
            payload={
                "event_id": str(event_id),
                "title": "Rescheduled Standup",
                "start_time": new_start.isoformat(),
                "end_time": new_end.isoformat(),
            },
            expires_in_minutes=15,
        )
        await session.commit()

        upd_res = await ActionService.confirm_action(
            session=session,
            organization_id=org_id,
            user_id=user_id,
            action_id=UUID(upd_prop["action_id"]),
            user_permissions=["calendar.write", "action.execute"],
        )
        await session.commit()
        assert upd_res["status"] == "COMPLETED"
        assert upd_res["result"]["title"] == "Rescheduled Standup"

        cancel_prop = await ActionService.propose_action(
            session=session,
            organization_id=org_id,
            conversation_id=conv_id,
            tool_name="cancel_calendar_meeting",
            action_type="cancel_calendar_meeting",
            payload={
                "event_id": str(event_id),
                "reason": "Cancelled by PM decision",
            },
            expires_in_minutes=15,
        )
        await session.commit()

        cancel_res = await ActionService.confirm_action(
            session=session,
            organization_id=org_id,
            user_id=user_id,
            action_id=UUID(cancel_prop["action_id"]),
            user_permissions=["calendar.write", "action.execute"],
        )
        await session.commit()
        assert cancel_res["status"] == "COMPLETED"
        assert cancel_res["result"]["status"] == "cancelled"
