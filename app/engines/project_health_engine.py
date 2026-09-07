import logging
from datetime import datetime, timezone
from typing import Any, Dict, List
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import Approval, Project, Risk, Task, TaskDependency, Ticket

logger = logging.getLogger(__name__)


class ProjectHealthEngine:
    @staticmethod
    async def evaluate_project_health(
        session: AsyncSession,
        organization_id: UUID,
        project_id: UUID,
    ) -> Dict[str, Any]:
        """Deterministically evaluates project operational health score (0-100) and status.
        Combines tasks, tickets, risks, approvals, and blocker data.
        """
        now = datetime.now(timezone.utc)

        # 1. Fetch project
        proj = (await session.execute(
            select(Project).where(
                Project.id == project_id,
                Project.organization_id == organization_id,
            )
        )).scalar_one_or_none()

        if not proj:
            raise ValueError("Project not found")

        # 2. Fetch Tasks
        tasks_res = await session.execute(
            select(Task).where(
                Task.project_id == project_id,
                Task.organization_id == organization_id,
                Task.deleted_at.is_(None),
            )
        )
        tasks = tasks_res.scalars().all()

        overdue_tasks = [t for t in tasks if t.status != "done" and t.due_date and t.due_date < now]
        blocked_tasks = [t for t in tasks if t.is_blocked or t.status == "blocked"]
        p0_tasks = [t for t in tasks if t.priority == "P0" and t.status != "done"]

        # 3. Fetch Tickets
        tickets_res = await session.execute(
            select(Ticket).where(
                Ticket.project_id == project_id,
                Ticket.organization_id == organization_id,
                Ticket.deleted_at.is_(None),
                Ticket.status != "resolved",
            )
        )
        tickets = tickets_res.scalars().all()

        p0_tickets = [t for t in tickets if t.severity == "critical" or t.priority == "P0"]
        breached_tickets = [t for t in tickets if t.sla_due_at and t.sla_due_at < now]

        # 4. Fetch Risks
        risks_res = await session.execute(
            select(Risk).where(
                Risk.project_id == project_id,
                Risk.organization_id == organization_id,
                Risk.status != "mitigated",
            )
        )
        risks = risks_res.scalars().all()
        critical_risks = [r for r in risks if (r.likelihood * r.impact) >= 15]

        # 5. Fetch Approvals
        approvals_res = await session.execute(
            select(Approval).where(
                Approval.project_id == project_id,
                Approval.organization_id == organization_id,
                Approval.status == "pending",
            )
        )
        approvals = approvals_res.scalars().all()
        overdue_approvals = [a for a in approvals if a.sla_due_at and a.sla_due_at < now]

        # 6. Calculate Deterministic Score
        score = 100
        factors = []

        if breached_tickets:
            deduction = len(breached_tickets) * 15
            score -= deduction
            factors.append(f"{len(breached_tickets)} ticket(s) breached SLA (-{deduction} pts)")

        if p0_tickets:
            deduction = len(p0_tickets) * 10
            score -= deduction
            factors.append(f"{len(p0_tickets)} active critical/P0 ticket(s) (-{deduction} pts)")

        if overdue_tasks:
            deduction = len(overdue_tasks) * 8
            score -= deduction
            factors.append(f"{len(overdue_tasks)} overdue task(s) (-{deduction} pts)")

        if critical_risks:
            deduction = len(critical_risks) * 10
            score -= deduction
            factors.append(f"{len(critical_risks)} high/critical unmitigated risk(s) (-{deduction} pts)")

        if overdue_approvals:
            deduction = len(overdue_approvals) * 10
            score -= deduction
            factors.append(f"{len(overdue_approvals)} overdue governance approval gate(s) (-{deduction} pts)")

        if blocked_tasks:
            deduction = len(blocked_tasks) * 5
            score -= deduction
            factors.append(f"{len(blocked_tasks)} blocked task(s) (-{deduction} pts)")

        score = max(0, min(100, score))

        # Classification
        if score >= 80:
            status = "healthy"
        elif score >= 50:
            status = "at_risk"
        else:
            status = "critical"

        return {
            "project_id": str(proj.id),
            "project_key": proj.key,
            "project_name": proj.name,
            "health_score": score,
            "status": status,
            "metrics": {
                "total_tasks": len(tasks),
                "overdue_tasks": len(overdue_tasks),
                "blocked_tasks": len(blocked_tasks),
                "p0_tasks": len(p0_tasks),
                "open_tickets": len(tickets),
                "breached_tickets": len(breached_tickets),
                "critical_tickets": len(p0_tickets),
                "active_risks": len(risks),
                "critical_risks": len(critical_risks),
                "pending_approvals": len(approvals),
                "overdue_approvals": len(overdue_approvals),
            },
            "factors": factors or ["All operational metrics within standard thresholds"],
            "evaluated_at": now.isoformat(),
        }
