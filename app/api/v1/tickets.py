from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import CurrentTenantUser, require_permission
from app.services.ticket_service import TicketService

router = APIRouter(prefix="/tickets", tags=["Tickets"])


@router.get("/")
async def list_tickets(
    assignee_id: UUID | None = None,
    severity: str | None = None,
    status: str | None = None,
    user: CurrentTenantUser = Depends(require_permission("ticket.read")),
    db: AsyncSession = Depends(get_db),
):
    return await TicketService.list_tickets(
        session=db,
        organization_id=user.organization_id,
        assignee_id=assignee_id,
        severity=severity,
        status=status,
    )


@router.get("/{ticket_id}/recommend-assignee")
async def recommend_assignee(
    ticket_id: UUID,
    user: CurrentTenantUser = Depends(require_permission("ticket.assign")),
    db: AsyncSession = Depends(get_db),
):
    rec = await TicketService.recommend_assignee(db, user.organization_id, ticket_id)
    if not rec:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ticket not found."
        )
    return rec


class AssignTicketRequest(BaseModel):
    assignee_id: UUID
    notes: str | None = None


@router.post("/{ticket_id}/assign")
async def assign_ticket(
    ticket_id: UUID,
    req: AssignTicketRequest,
    user: CurrentTenantUser = Depends(require_permission("ticket.assign")),
    db: AsyncSession = Depends(get_db),
):
    res = await TicketService.assign_ticket(
        session=db,
        organization_id=user.organization_id,
        ticket_id=ticket_id,
        assignee_id=req.assignee_id,
        notes=req.notes,
    )
    await db.commit()
    return res
