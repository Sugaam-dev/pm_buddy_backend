import logging
from datetime import datetime, timezone
from typing import Any, Dict, List
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import Approval, Project, Risk, Task, TaskDependency, Ticket

logger = logging.getLogger(__name__)


class RecommendationService:
    @staticmethod
    async def get_action_recommendations(
        session: AsyncSession,
        organization_id: UUID,
        limit: int = 5,
    ) -> List[Dict[str, Any]]:
        """Generates deterministic, rule-based operational recommendations.
        Never executes mutations automatically; outputs proposals for HITL confirmation.
        """
        now = datetime.now(timezone.utc)
        recommendations = []

        # Rule 1: SLA Breached Tickets needing Escalation
        tickets_res = await session.execute(
            select(Ticket).where(
                Ticket.organization_id == organization_id,
                Ticket.status.in_(["open", "in_progress"]),
                Ticket.sla_due_at < now,
                Ticket.deleted_at.is_(None),
            ).order_by(Ticket.sla_due_at.asc()).limit(3)
        )
        for t in tickets_res.scalars().all():
            recommendations.append({
                "id": f"rec-escalate-{t.id}",
                "action_type": "propose_escalation",
                "title": f"Escalate Breached Ticket {t.ticket_number}",
                "reason": f"Ticket '{t.title}' has breached SLA deadline of {t.sla_due_at.strftime('%Y-%m-%d %H:%M')}.",
                "priority": "P0" if t.severity == "critical" else "P1",
                "source_entity": "ticket",
                "source_id": str(t.id),
                "required_permission": "ticket.escalate",
                "payload": {
                    "ticket_id": str(t.id),
                    "ticket_number": t.ticket_number,
                    "escalate_to": "cto@acme.com",
                    "reason": f"SLA breached on {t.ticket_number}",
                },
            })

        # Rule 2: Unassigned P0/P1 Tickets
        unassigned_res = await session.execute(
            select(Ticket).where(
                Ticket.organization_id == organization_id,
                Ticket.status == "open",
                Ticket.assignee_id.is_(None),
                Ticket.priority.in_(["P0", "P1"]),
                Ticket.deleted_at.is_(None),
            ).order_by(Ticket.priority.asc()).limit(2)
        )
        for t in unassigned_res.scalars().all():
            recommendations.append({
                "id": f"rec-assign-{t.id}",
                "action_type": "propose_ticket_assignment",
                "title": f"Assign Urgent Ticket {t.ticket_number}",
                "reason": f"Ticket '{t.title}' has priority {t.priority} but is currently unassigned.",
                "priority": t.priority,
                "source_entity": "ticket",
                "source_id": str(t.id),
                "required_permission": "ticket.assign",
                "payload": {
                    "ticket_id": str(t.id),
                    "ticket_number": t.ticket_number,
                    "assignee_id": None,  # To be picked by user
                },
            })

        # Rule 3: Overdue Governance Approvals
        approvals_res = await session.execute(
            select(Approval, Project).join(Project, Project.id == Approval.project_id).where(
                Approval.organization_id == organization_id,
                Approval.status == "pending",
                Approval.sla_due_at < now,
            ).order_by(Approval.sla_due_at.asc()).limit(2)
        )
        for a, p in approvals_res.all():
            recommendations.append({
                "id": f"rec-approve-{a.id}",
                "action_type": "propose_gate_approval",
                "title": f"Decide Governance Gate: {a.title}",
                "reason": f"Approval for project '{p.name}' is overdue for stage '{a.stage}'.",
                "priority": "P0",
                "source_entity": "approval",
                "source_id": str(a.id),
                "required_permission": "approval.approve",
                "payload": {
                    "approval_id": str(a.id),
                    "decision": "approved",
                    "notes": "Fast-tracked after automated SLA alert",
                },
            })

        # Rule 4: Projects with Health = 'at_risk' or 'critical' needing sync
        crit_proj_res = await session.execute(
            select(Project).where(
                Project.organization_id == organization_id,
                Project.health.in_(["at_risk", "critical"]),
                Project.deleted_at.is_(None),
            ).limit(2)
        )
        for p in crit_proj_res.scalars().all():
            recommendations.append({
                "id": f"rec-meet-{p.id}",
                "action_type": "propose_calendar_meeting",
                "title": f"Schedule Governance Sync for Project {p.name}",
                "reason": f"Project '{p.name}' health is '{p.health}'. An operational review is recommended.",
                "priority": "P1",
                "source_entity": "project",
                "source_id": str(p.id),
                "required_permission": "calendar.write",
                "payload": {
                    "title": f"{p.name} — Emergency Operational Review",
                    "meeting_type": "governance",
                    "project_id": str(p.id),
                },
            })

        # Sort recommendations by priority (P0 first, then P1)
        priority_order = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
        recommendations.sort(key=lambda r: priority_order.get(r["priority"], 99))

        return recommendations[:limit]
