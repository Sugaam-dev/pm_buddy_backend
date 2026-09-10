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


@router.get("/{ticket_id}")
async def get_ticket(
    ticket_id: UUID,
    user: CurrentTenantUser = Depends(require_permission("ticket.read")),
    db: AsyncSession = Depends(get_db),
):
    ticket = await TicketService.get_ticket(db, user.organization_id, ticket_id)
    if not ticket:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ticket not found in your organization."
        )
    return ticket


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


class CreateTicketRequest(BaseModel):
    title: str
    description: str = ""
    severity: str = "high"
    priority: str = "P2"
    category: str = "Infrastructure"
    status: str = "new"
    affected_service: str | None = None
    assignee_id: UUID | None = None
    project_id: UUID | None = None
    sla_hours: int | None = None


@router.post("/")
async def create_ticket(
    req: CreateTicketRequest,
    user: CurrentTenantUser = Depends(require_permission(["ticket.create", "ticket.write"])),
    db: AsyncSession = Depends(get_db),
):
    ticket = await TicketService.create_ticket(
        session=db,
        organization_id=user.organization_id,
        title=req.title,
        description=req.description,
        severity=req.severity,
        priority=req.priority,
        category=req.category,
        status=req.status,
        affected_service=req.affected_service,
        assignee_id=req.assignee_id,
        project_id=req.project_id,
        sla_hours=req.sla_hours,
    )
    return ticket


class UpdateTicketStatusRequest(BaseModel):
    status: str


@router.patch("/{ticket_id}/status")
async def update_ticket_status(
    ticket_id: UUID,
    req: UpdateTicketStatusRequest,
    user: CurrentTenantUser = Depends(require_permission("ticket.read")),
    db: AsyncSession = Depends(get_db),
):
    res = await TicketService.update_ticket_status(
        session=db,
        organization_id=user.organization_id,
        ticket_id=ticket_id,
        status=req.status,
    )
    if not res:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ticket not found."
        )
    return res
