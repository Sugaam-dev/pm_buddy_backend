from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import CurrentTenantUser, require_permission
from app.services.approval_service import ApprovalService

router = APIRouter(prefix="/approvals", tags=["Approvals"])


@router.get("/")
async def list_approvals(
    project_id: UUID | None = None,
    status: str = "pending",
    breached_only: bool = Query(False),
    user: CurrentTenantUser = Depends(require_permission("approval.read")),
    db: AsyncSession = Depends(get_db),
):
    return await ApprovalService.list_approvals(
        session=db,
        organization_id=user.organization_id,
        project_id=project_id,
        status=status,
        breached_only=breached_only,
    )


@router.get("/blocking-approvers")
async def get_blocking_approvers(
    user: CurrentTenantUser = Depends(require_permission("approval.read")),
    db: AsyncSession = Depends(get_db),
):
    return await ApprovalService.get_blocking_approvers(db, user.organization_id)


class DecisionRequest(BaseModel):
    decision: str  # "approved" or "rejected"
    notes: str | None = None


@router.post("/{approval_id}/decide")
async def decide_approval(
    approval_id: UUID,
    req: DecisionRequest,
    user: CurrentTenantUser = Depends(require_permission("approval.write")),
    db: AsyncSession = Depends(get_db),
):
    res = await ApprovalService.decide_step(
        session=db,
        organization_id=user.organization_id,
        approval_id=approval_id,
        user_id=user.user_id,
        decision=req.decision,
        notes=req.notes,
    )
    await db.commit()
    return res
