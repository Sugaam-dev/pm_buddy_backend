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
            if status.lower() in ("open", "all_open"):
                stmt = stmt.where(Ticket.status.in_(["open", "new", "in_progress", "escalated"]))
            else:
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
                "created_at": t.created_at.isoformat() if t.created_at else None,
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

    @staticmethod
    async def create_ticket(
        session: AsyncSession,
        organization_id: UUID,
        title: str,
        description: str = "",
        severity: str = "high",
        priority: str = "P2",
        category: str = "Infrastructure",
        status: str = "new",
        affected_service: str | None = None,
        assignee_id: UUID | None = None,
        project_id: UUID | None = None,
        sla_hours: int | None = None,
    ) -> dict[str, Any]:
        """Creates a new incident/support ticket with SLA tracking."""
        from datetime import timedelta

        # Normalize severity and priority supporting natural language inputs
        norm_combined = f"{severity} {priority}".lower().strip()
        if any(term in norm_combined for term in ["p0", "priority 0", "critical priority", "critical"]):
            sev_clean = "critical"
            prio_clean = "P0"
            default_sla = 4
        elif any(term in norm_combined for term in ["p1", "priority 1", "high priority"]):
            sev_clean = "critical"
            prio_clean = "P1"
            default_sla = 8
        elif any(term in norm_combined for term in ["p3", "priority 3", "low priority", "low", "routine"]):
            sev_clean = "medium"
            prio_clean = "P3"
            default_sla = 48
        elif any(term in norm_combined for term in ["p2", "priority 2", "medium priority"]):
            sev_clean = "high"
            prio_clean = "P2"
            default_sla = 24
        else:
            sev_clean = severity.lower() if severity in ["critical", "high", "medium", "low"] else "high"
            prio_clean = priority.upper() if priority and priority.upper() in ["P0", "P1", "P2", "P3"] else "P2"
            default_sla = 4 if prio_clean == "P0" else (8 if prio_clean == "P1" else (48 if prio_clean == "P3" else 24))

        hours = sla_hours or default_sla
        now = datetime.now(timezone.utc)
        sla_due_at = now + timedelta(hours=hours)

        # Generate ticket number
        count_stmt = select(Ticket).where(Ticket.organization_id == organization_id)
        count = len((await session.execute(count_stmt)).scalars().all())
        ticket_number = f"INC-{count + 101}"

        from app.models.entities import Project
        # Validate project_id belongs to the authenticated organization
        if project_id:
            proj_valid = (await session.execute(
                select(Project.id).where(
                    Project.id == project_id,
                    Project.organization_id == organization_id,
                    Project.deleted_at.is_(None),
                )
            )).scalar_one_or_none()
            if not proj_valid:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Project not found or does not belong to your organization."
                )
        else:
            # Pick first active project in organization
            proj_stmt = (
                select(Project.id)
                .where(
                    Project.organization_id == organization_id,
                    Project.deleted_at.is_(None)
                )
                .limit(1)
            )
            project_id = (await session.execute(proj_stmt)).scalar_one_or_none()

        ticket = Ticket(
            organization_id=organization_id,
            project_id=project_id,
            ticket_number=ticket_number,
            title=title.strip(),
            description=description or f"Incident reported: {title.strip()}",
            category=category,
            severity=sev_clean,
            priority=prio_clean,
            status=status or "new",
            affected_service=affected_service,
            assignee_id=assignee_id,
            sla_due_at=sla_due_at,
        )
        session.add(ticket)
        await session.flush()
        await session.commit()

        sla_info = SLAEngine.evaluate_status(ticket.created_at, ticket.sla_due_at, now=now)
        return {
            "id": str(ticket.id),
            "organization_id": str(ticket.organization_id),
            "ticket_number": ticket.ticket_number,
            "title": ticket.title,
            "description": ticket.description,
            "category": ticket.category,
            "severity": ticket.severity,
            "priority": ticket.priority,
            "status": ticket.status,
            "affected_service": ticket.affected_service,
            "assignee_id": str(ticket.assignee_id) if ticket.assignee_id else None,
            "sla_status": sla_info["status"].value,
            "is_breached": sla_info["is_breached"],
            "sla_due_at": ticket.sla_due_at.isoformat(),
            "breach_risk_score": ticket.breach_risk_score,
            "probable_cause": ticket.probable_cause,
            "suggested_resolution": ticket.suggested_resolution,
            "created_at": ticket.created_at.isoformat() if ticket.created_at else None,
        }

    @staticmethod
    async def update_ticket_status(
        session: AsyncSession,
        organization_id: UUID,
        ticket_id: UUID,
        status: str,
    ) -> dict[str, Any] | None:
        stmt = select(Ticket).where(
            Ticket.id == ticket_id,
            Ticket.organization_id == organization_id,
            Ticket.deleted_at.is_(None),
        )
        ticket = (await session.execute(stmt)).scalar_one_or_none()
        if not ticket:
            return None
        ticket.status = status
        if status.lower() in ("resolved", "closed"):
            ticket.resolved_at = datetime.now(timezone.utc)
        await session.flush()
        await session.commit()
        return {"id": str(ticket.id), "status": ticket.status}

    @staticmethod
    async def get_ticket(
        session: AsyncSession,
        organization_id: UUID,
        ticket_id: UUID,
    ) -> dict[str, Any] | None:
        """Fetches a single ticket with full details, strictly scoped to organization_id."""
        stmt = select(Ticket).where(
            Ticket.id == ticket_id,
            Ticket.organization_id == organization_id,
            Ticket.deleted_at.is_(None),
        )
        ticket = (await session.execute(stmt)).scalar_one_or_none()
        if not ticket:
            return None

        now = datetime.now(timezone.utc)
        sla_info = SLAEngine.evaluate_status(ticket.created_at, ticket.sla_due_at, now=now)
        return {
            "id": str(ticket.id),
            "ticket_number": ticket.ticket_number,
            "title": ticket.title,
            "description": ticket.description,
            "category": ticket.category,
            "severity": ticket.severity,
            "priority": ticket.priority,
            "status": ticket.status,
            "affected_service": ticket.affected_service,
            "assignee_id": str(ticket.assignee_id) if ticket.assignee_id else None,
            "sla_status": sla_info["status"].value,
            "is_breached": sla_info["is_breached"],
            "sla_due_at": ticket.sla_due_at.isoformat(),
            "first_response_at": ticket.first_response_at.isoformat() if ticket.first_response_at else None,
            "resolved_at": ticket.resolved_at.isoformat() if ticket.resolved_at else None,
            "breach_risk_score": ticket.breach_risk_score,
            "probable_cause": ticket.probable_cause,
            "suggested_resolution": ticket.suggested_resolution,
            "created_at": ticket.created_at.isoformat() if ticket.created_at else None,
            "updated_at": ticket.updated_at.isoformat() if ticket.updated_at else None,
        }


