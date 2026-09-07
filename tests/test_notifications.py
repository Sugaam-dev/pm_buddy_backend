import pytest
from uuid import uuid4

from app.core.database import AsyncSessionLocal
from app.models.entities import Notification, Organization
from app.services.notification_service import NotificationService


@pytest.mark.asyncio
async def test_notifications_crud_and_unread_counter():
    async with AsyncSessionLocal() as session:
        org_id = uuid4()
        user_id = uuid4()

        org = Organization(id=org_id, name="Notif Org", slug=f"notif-{org_id.hex[:8]}")
        session.add(org)
        await session.commit()

        # Create notification
        notif = await NotificationService.create_notification(
            session=session,
            organization_id=org_id,
            user_id=user_id,
            title="SLA Breach Alert",
            message="TCK-1001 has breached SLA",
            severity="critical",
            event_type="SLA_BREACH",
        )
        assert notif.id is not None
        assert notif.is_read is False

        # Check unread count
        unread = await NotificationService.get_unread_count(session, org_id, user_id)
        assert unread == 1

        # Mark read
        success = await NotificationService.mark_read(session, org_id, notif.id)
        assert success is True

        unread_after = await NotificationService.get_unread_count(session, org_id, user_id)
        assert unread_after == 0

        # Cleanup
        await session.delete(notif)
        await session.delete(org)
        await session.commit()


@pytest.mark.asyncio
async def test_notifications_tenant_isolation():
    async with AsyncSessionLocal() as session:
        org_a = uuid4()
        org_b = uuid4()

        o_a = Organization(id=org_a, name="Notif Org A", slug=f"notif-a-{org_a.hex[:8]}")
        o_b = Organization(id=org_b, name="Notif Org B", slug=f"notif-b-{org_b.hex[:8]}")
        session.add_all([o_a, o_b])
        await session.commit()

        n_b = await NotificationService.create_notification(
            session=session,
            organization_id=org_b,
            title="Secret Notification for Org B",
            message="Internal only",
        )

        # Org A queries notifications
        list_a = await NotificationService.list_notifications(session, org_a)
        assert len(list_a) == 0

        await session.delete(n_b)
        await session.delete(o_a)
        await session.delete(o_b)
        await session.commit()
