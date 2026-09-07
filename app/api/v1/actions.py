from typing import Any
from uuid import UUID
from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import CurrentTenantUser, require_permission
from app.services.action_service import ActionService

router = APIRouter(prefix="/actions", tags=["Human-In-The-Loop Actions"])


class ConfirmActionRequest(BaseModel):
    idempotency_key: str | None = None


@router.post("/{action_id}/confirm")
async def confirm_action(
    action_id: UUID,
    req: ConfirmActionRequest = ConfirmActionRequest(),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    user: CurrentTenantUser = Depends(require_permission("action.execute")),
    db: AsyncSession = Depends(get_db),
):
    key = idempotency_key or req.idempotency_key
    return await ActionService.confirm_action(
        session=db,
        organization_id=user.organization_id,
        user_id=user.user_id,
        action_id=action_id,
        idempotency_key=key,
        user_permissions=user.permissions,
    )


@router.post("/{action_id}/cancel")
async def cancel_action(
    action_id: UUID,
    user: CurrentTenantUser = Depends(require_permission("action.execute")),
    db: AsyncSession = Depends(get_db),
):
    return await ActionService.cancel_action(
        session=db,
        organization_id=user.organization_id,
        user_id=user.user_id,
        action_id=action_id,
    )
