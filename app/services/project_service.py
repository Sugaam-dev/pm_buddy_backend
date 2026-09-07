from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.engines.sla_engine import SLAEngine
from app.models.entities import Approval, Milestone, Project, Risk, Task, Ticket


class ProjectService:
    @staticmethod
    async def list_projects(session: AsyncSession, organization_id: UUID) -> list[dict[str, Any]]:
        stmt = select(Project).where(
            Project.organization_id == organization_id,
            Project.deleted_at.is_(None)
        ).order_by(Project.created_at.desc())
        
        result = await session.execute(stmt)
        projects = result.scalars().all()
        
        return [
            {
                "id": str(p.id),
                "name": p.name,
                "key": p.key,
                "description": p.description,
                "status": p.status,
                "health": p.health,
                "budget": float(p.budget or 0),
                "spent": float(p.spent or 0),
                "target_date": p.target_date.isoformat() if p.target_date else None,
            }
            for p in projects
        ]

    @staticmethod
    async def get_project_dashboard(
        session: AsyncSession, organization_id: UUID, project_id: UUID
    ) -> dict[str, Any] | None:
        # 1. Fetch Project
        stmt = select(Project).where(
            Project.id == project_id,
            Project.organization_id == organization_id,
            Project.deleted_at.is_(None)
        )
        proj_res = await session.execute(stmt)
        project = proj_res.scalar_one_or_none()
        if not project:
            return None

        now = datetime.now(timezone.utc)

        # 2. Tasks Aggregation
        task_stmt = select(Task).where(
            Task.project_id == project_id,
            Task.organization_id == organization_id,
            Task.deleted_at.is_(None)
        )
        tasks = (await session.execute(task_stmt)).scalars().all()

        total_tasks = len(tasks)
        completed_tasks = sum(1 for t in tasks if t.status == "done")
        blocked_tasks = [
            {"id": str(t.id), "title": t.title, "reason": t.blocker_reason, "priority": t.priority}
            for t in tasks if t.is_blocked
        ]
        overdue_tasks = sum(
            1 for t in tasks if t.due_date and t.due_date < now and t.status != "done"
        )
        progress_pct = int(round((completed_tasks / total_tasks * 100))) if total_tasks > 0 else 0

        # 3. Pending Approvals & SLA
        app_stmt = select(Approval).where(
            Approval.project_id == project_id,
            Approval.organization_id == organization_id,
            Approval.status == "pending"
        )
        approvals = (await session.execute(app_stmt)).scalars().all()
        
        approval_data = []
        for app in approvals:
            sla_info = SLAEngine.evaluate_status(app.created_at, app.sla_due_at, now=now)
            approval_data.append({
                "id": str(app.id),
                "title": app.title,
                "stage": app.stage,
                "sla_status": sla_info["status"].value,
                "is_breached": sla_info["is_breached"],
                "sla_due_at": app.sla_due_at.isoformat(),
            })

        # 4. Open Tickets
        ticket_stmt = select(Ticket).where(
            Ticket.project_id == project_id,
            Ticket.organization_id == organization_id,
            Ticket.status.in_(["open", "in_progress"]),
            Ticket.deleted_at.is_(None)
        )
        tickets = (await session.execute(ticket_stmt)).scalars().all()
        critical_tickets = sum(1 for t in tickets if t.severity == "critical")

        # 5. Risks
        risk_stmt = select(Risk).where(
            Risk.project_id == project_id,
            Risk.organization_id == organization_id
        ).order_by((Risk.likelihood * Risk.impact).desc())
        risks = (await session.execute(risk_stmt)).scalars().all()

        return {
            "project": {
                "id": str(project.id),
                "name": project.name,
                "key": project.key,
                "health": project.health,
                "status": project.status,
                "budget": float(project.budget or 0),
                "spent": float(project.spent or 0),
                "target_date": project.target_date.isoformat() if project.target_date else None,
            },
            "metrics": {
                "progress_percentage": progress_pct,
                "total_tasks": total_tasks,
                "completed_tasks": completed_tasks,
                "overdue_tasks": overdue_tasks,
                "blocked_task_count": len(blocked_tasks),
                "critical_ticket_count": critical_tickets,
                "pending_approval_count": len(approval_data),
            },
            "blockers": blocked_tasks,
            "pending_approvals": approval_data,
            "top_risks": [
                {
                    "id": str(r.id),
                    "title": r.title,
                    "category": r.category,
                    "score": r.likelihood * r.impact,
                    "status": r.status,
                }
                for r in risks[:3]
            ],
        }

    @staticmethod
    async def update_project_status(
        session: AsyncSession,
        organization_id: UUID,
        project_id: UUID,
        status: str | None = None,
        health: str | None = None,
        reason: str | None = None,
    ) -> dict[str, Any]:
        """Mutates operational status and health for a project."""
        stmt = (
            select(Project)
            .where(
                Project.id == project_id,
                Project.organization_id == organization_id,
                Project.deleted_at.is_(None),
            )
            .with_for_update()
        )
        project = (await session.execute(stmt)).scalar_one_or_none()
        if not project:
            from fastapi import HTTPException, status as http_status
            raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Project not found.")

        if status:
            project.status = status
        if health:
            project.health = health
        await session.flush()

        return {
            "project_id": str(project.id),
            "status": project.status,
            "health": project.health,
            "reason": reason,
        }

