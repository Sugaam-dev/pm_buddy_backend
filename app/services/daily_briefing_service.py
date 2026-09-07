import logging
from datetime import datetime, time, timedelta, timezone
from typing import Any, Dict, Optional
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import Approval, CalendarEvent, Project, Risk, Task, Ticket

logger = logging.getLogger(__name__)


class DailyBriefingService:
    @staticmethod
    async def get_daily_briefing(
        session: AsyncSession,
        organization_id: UUID,
        target_date: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Aggregates factual operational metrics for the day across calendar, tasks, tickets, risks, and approvals."""
        now = datetime.now(timezone.utc)
        if target_date:
            try:
                base_dt = datetime.fromisoformat(target_date.replace("Z", "+00:00"))
            except ValueError:
                base_dt = now
        else:
            base_dt = now

        day_start = datetime.combine(base_dt.date(), time.min, tzinfo=timezone.utc)
        day_end = datetime.combine(base_dt.date(), time.max, tzinfo=timezone.utc)

        # 1. Today's Meetings
        events_res = await session.execute(
            select(CalendarEvent).where(
                CalendarEvent.organization_id == organization_id,
                CalendarEvent.status != "cancelled",
                CalendarEvent.start_time >= day_start,
                CalendarEvent.start_time <= day_end,
            ).order_by(CalendarEvent.start_time.asc())
        )
        meetings = [
            {
                "id": str(e.id),
                "title": e.title,
                "start_time": e.start_time.isoformat(),
                "end_time": e.end_time.isoformat(),
                "location": e.location or "Google Meet",
                "attendees": e.attendees,
            }
            for e in events_res.scalars().all()
        ]

        # 2. High-Priority Open Tasks (P0/P1)
        tasks_res = await session.execute(
            select(Task, Project).join(Project, Project.id == Task.project_id).where(
                Task.organization_id == organization_id,
                Task.status.in_(["todo", "in_progress"]),
                Task.priority.in_(["P0", "P1"]),
                Task.deleted_at.is_(None),
            ).order_by(Task.priority.asc(), Task.due_date.asc().nulls_last()).limit(5)
        )
        priority_tasks = [
            {
                "id": str(t.id),
                "title": t.title,
                "priority": t.priority,
                "status": t.status,
                "project_name": p.name,
                "is_overdue": bool(t.due_date and t.due_date < now),
                "due_date": t.due_date.isoformat() if t.due_date else None,
            }
            for t, p in tasks_res.all()
        ]

        # 3. SLA Incident Tickets (Breached or Breaching Soon)
        tickets_res = await session.execute(
            select(Ticket).where(
                Ticket.organization_id == organization_id,
                Ticket.status.in_(["open", "in_progress"]),
                Ticket.deleted_at.is_(None),
            ).order_by(Ticket.sla_due_at.asc()).limit(5)
        )
        sla_tickets = []
        for t in tickets_res.scalars().all():
            is_breached = bool(t.sla_due_at and t.sla_due_at < now)
            sla_tickets.append({
                "id": str(t.id),
                "ticket_number": t.ticket_number,
                "title": t.title,
                "severity": t.severity,
                "priority": t.priority,
                "status": t.status,
                "is_breached": is_breached,
                "sla_due_at": t.sla_due_at.isoformat() if t.sla_due_at else None,
            })

        # 4. Pending Governance Gate Approvals
        approvals_res = await session.execute(
            select(Approval, Project).join(Project, Project.id == Approval.project_id).where(
                Approval.organization_id == organization_id,
                Approval.status == "pending",
            ).order_by(Approval.sla_due_at.asc())
        )
        pending_approvals = [
            {
                "id": str(a.id),
                "title": a.title,
                "stage": a.stage,
                "project_name": p.name,
                "is_overdue": bool(a.sla_due_at and a.sla_due_at < now),
                "sla_due_at": a.sla_due_at.isoformat() if a.sla_due_at else None,
            }
            for a, p in approvals_res.all()
        ]

        # 5. Top Unmitigated Risks
        risks_res = await session.execute(
            select(Risk, Project).join(Project, Project.id == Risk.project_id).where(
                Risk.organization_id == organization_id,
                Risk.status != "mitigated",
            ).order_by((Risk.likelihood * Risk.impact).desc()).limit(3)
        )
        top_risks = [
            {
                "id": str(r.id),
                "title": r.title,
                "category": r.category,
                "project_name": p.name,
                "score": r.likelihood * r.impact,
            }
            for r, p in risks_res.all()
        ]

        return {
            "date": base_dt.date().isoformat(),
            "summary": {
                "meeting_count": len(meetings),
                "high_priority_tasks_count": len(priority_tasks),
                "open_tickets_count": len(sla_tickets),
                "pending_approvals_count": len(pending_approvals),
                "top_risks_count": len(top_risks),
            },
            "meetings": meetings,
            "priority_tasks": priority_tasks,
            "sla_tickets": sla_tickets,
            "pending_approvals": pending_approvals,
            "top_risks": top_risks,
            "generated_at": now.isoformat(),
        }
