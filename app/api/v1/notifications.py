from typing import List, Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query, Security, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import CurrentTenantUser, get_current_tenant_user
from app.services.notification_service import NotificationService

router = APIRouter(prefix="/notifications", tags=["In-App Notifications"])


class NotificationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    user_id: Optional[UUID]
    title: str
    message: str
    severity: str
    event_type: str
    source_entity: Optional[str]
    source_id: Optional[UUID]
    action_link: Optional[str]
    is_read: bool
    created_at: str


@router.get("")
async def list_notifications(
    unread_only: bool = Query(False),
    limit: int = Query(50, ge=1, le=100),
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    session: AsyncSession = Depends(get_db),
):
    notifs = await NotificationService.list_notifications(
        session=session,
        organization_id=user.organization_id,
        user_id=user.user_id,
        unread_only=unread_only,
        limit=limit,
    )
    unread_count = await NotificationService.get_unread_count(
        session=session,
        organization_id=user.organization_id,
        user_id=user.user_id,
    )

    return {
        "unread_count": unread_count,
        "notifications": [
            NotificationResponse(
                id=n.id,
                organization_id=n.organization_id,
                user_id=n.user_id,
                title=n.title,
                message=n.message,
                severity=n.severity,
                event_type=n.event_type or n.type or "GENERAL",
                source_entity=n.source_entity,
                source_id=n.source_id,
                action_link=n.action_link or n.link_url,
                is_read=n.is_read,
                created_at=n.created_at.isoformat(),
            )
            for n in notifs
        ],
    }


@router.patch("/{notification_id}/read")
async def mark_notification_read(
    notification_id: UUID,
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    session: AsyncSession = Depends(get_db),
):
    success = await NotificationService.mark_read(session, user.organization_id, notification_id)
    if not success:
        raise HTTPException(status_code=404, detail="Notification not found")
    return {"status": "ok", "id": str(notification_id)}


@router.post("/read-all")
async def mark_all_notifications_read(
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    session: AsyncSession = Depends(get_db),
):
    count = await NotificationService.mark_all_read(session, user.organization_id, user.user_id)
    return {"status": "ok", "marked_count": count}
