from datetime import datetime, timezone
from typing import Any
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.engines.prediction_engine import HeuristicPredictionProvider
from app.engines.sla_engine import SLAEngine
from app.models.entities import OrganizationMember, Role, Ticket


class TicketService:
    @staticmethod
    async def list_tickets(
        session: AsyncSession,
        organization_id: UUID,
        assignee_id: UUID | None = None,
        severity: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        stmt = select(Ticket).where(
            Ticket.organization_id == organization_id,
            Ticket.deleted_at.is_(None)
        )

        if assignee_id:
            stmt = stmt.where(Ticket.assignee_id == assignee_id)
        if severity:
            stmt = stmt.where(Ticket.severity == severity)
        if status:
            stmt = stmt.where(Ticket.status == status)

        result = await session.execute(stmt)
        tickets = result.scalars().all()
        now = datetime.now(timezone.utc)

        output = []
        for t in tickets:
            sla_info = SLAEngine.evaluate_status(t.created_at, t.sla_due_at, now=now)
            output.append({
                "id": str(t.id),
                "ticket_number": t.ticket_number,
                "title": t.title,
                "description": t.description,
                "category": t.category,
                "severity": t.severity,
                "priority": t.priority,
                "status": t.status,
                "affected_service": t.affected_service,
                "assignee_id": str(t.assignee_id) if t.assignee_id else None,
                "sla_status": sla_info["status"].value,
                "is_breached": sla_info["is_breached"],
                "sla_due_at": t.sla_due_at.isoformat(),
                "breach_risk_score": t.breach_risk_score,
                "probable_cause": t.probable_cause,
                "suggested_resolution": t.suggested_resolution,
            })

        return output

    @staticmethod
    async def recommend_assignee(
        session: AsyncSession,
        organization_id: UUID,
        ticket_id: UUID,
    ) -> dict[str, Any] | None:
        stmt = select(Ticket).where(Ticket.id == ticket_id, Ticket.organization_id == organization_id)
        ticket = (await session.execute(stmt)).scalar_one_or_none()
        if not ticket:
            return None

        # Fetch candidate engineers in organization
        eng_stmt = (
            select(OrganizationMember)
            .join(Role, OrganizationMember.role_id == Role.id)
            .where(
                OrganizationMember.organization_id == organization_id,
                Role.name.in_(["ENGINEER", "TEAM_LEAD"])
            )
        )
        members = (await session.execute(eng_stmt)).scalars().all()

        # Simple heuristic assignment matching
        candidates = []
        for m in members:
            # Count open tickets for member
            open_count_stmt = select(Ticket).where(
                Ticket.organization_id == organization_id,
                Ticket.assignee_id == m.user_id,
                Ticket.status.in_(["open", "in_progress"])
            )
            open_tickets = (await session.execute(open_count_stmt)).scalars().all()
            load = len(open_tickets)

            suitability_score = max(10, 100 - (load * 20))
            candidates.append({
                "user_id": str(m.user_id),
                "suitability_score": suitability_score,
                "active_ticket_count": load,
                "reason": f"Active workload of {load} tickets. Available for new assignments.",
            })

        candidates.sort(key=lambda x: x["suitability_score"], reverse=True)
        recommended = candidates[0] if candidates else None

        return {
            "ticket_id": str(ticket_id),
            "recommended_assignee": recommended,
            "all_candidates": candidates,
        }

    @staticmethod
    async def assign_ticket(
        session: AsyncSession,
        organization_id: UUID,
        ticket_id: UUID,
        assignee_id: UUID,
        notes: str | None = None,
    ) -> dict[str, Any]:
        """Assigns an incident ticket to a user."""
        stmt = (
            select(Ticket)
            .where(
                Ticket.id == ticket_id,
                Ticket.organization_id == organization_id,
                Ticket.deleted_at.is_(None),
            )
            .with_for_update()
        )
        ticket = (await session.execute(stmt)).scalar_one_or_none()
        if not ticket:
            from fastapi import HTTPException, status
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found.")

        ticket.assignee_id = assignee_id
        if ticket.status == "open":
            ticket.status = "in_progress"
        await session.flush()

        return {
            "ticket_id": str(ticket.id),
            "assignee_id": str(ticket.assignee_id),
            "status": ticket.status,
            "notes": notes,
        }

