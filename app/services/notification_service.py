import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import Notification, utc_now

logger = logging.getLogger(__name__)


class NotificationService:
    @staticmethod
    async def create_notification(
        session: AsyncSession,
        organization_id: UUID,
        title: str,
        message: str,
        severity: str = "info",
        event_type: str = "GENERAL",
        source_entity: Optional[str] = None,
        source_id: Optional[UUID] = None,
        action_link: Optional[str] = None,
        user_id: Optional[UUID] = None,
    ) -> Notification:
        """Creates an in-app notification."""
        notif = Notification(
            id=uuid4(),
            organization_id=organization_id,
            user_id=user_id,
            title=title.strip(),
            message=message.strip(),
            severity=severity,
            type=event_type,
            event_type=event_type,
            source_entity=source_entity,
            source_id=source_id,
            link_url=action_link,
            action_link=action_link,
            is_read=False,
            created_at=utc_now(),
        )
        session.add(notif)
        await session.commit()
        await session.refresh(notif)
        return notif

    @staticmethod
    async def list_notifications(
        session: AsyncSession,
        organization_id: UUID,
        user_id: Optional[UUID] = None,
        unread_only: bool = False,
        limit: int = 50,
    ) -> List[Notification]:
        """Lists notifications for an organization and optional user."""
        query = select(Notification).where(Notification.organization_id == organization_id)
        if user_id:
            query = query.where(or_(Notification.user_id == user_id, Notification.user_id.is_(None)))
        if unread_only:
            query = query.where(Notification.is_read.is_(False))

        query = query.order_by(Notification.created_at.desc()).limit(limit)
        res = await session.execute(query)
        return list(res.scalars().all())

    @staticmethod
    async def get_unread_count(
        session: AsyncSession,
        organization_id: UUID,
        user_id: Optional[UUID] = None,
    ) -> int:
        """Counts unread notifications."""
        query = select(func.count(Notification.id)).where(
            Notification.organization_id == organization_id,
            Notification.is_read.is_(False),
        )
        if user_id:
            query = query.where(or_(Notification.user_id == user_id, Notification.user_id.is_(None)))

        res = await session.execute(query)
        return res.scalar() or 0

    @staticmethod
    async def mark_read(
        session: AsyncSession,
        organization_id: UUID,
        notification_id: UUID,
    ) -> bool:
        """Marks a single notification as read."""
        stmt = (
            update(Notification)
            .where(
                Notification.id == notification_id,
                Notification.organization_id == organization_id,
            )
            .values(is_read=True, read_at=utc_now())
        )
        res = await session.execute(stmt)
        await session.commit()
        return res.rowcount > 0

    @staticmethod
    async def mark_all_read(
        session: AsyncSession,
        organization_id: UUID,
        user_id: Optional[UUID] = None,
    ) -> int:
        """Marks all unread notifications as read."""
        stmt = (
            update(Notification)
            .where(
                Notification.organization_id == organization_id,
                Notification.is_read.is_(False),
            )
            .values(is_read=True, read_at=utc_now())
        )
        if user_id:
            stmt = stmt.where(or_(Notification.user_id == user_id, Notification.user_id.is_(None)))

        res = await session.execute(stmt)
        await session.commit()
        return res.rowcount
