from datetime import datetime, timezone
from typing import Any
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.engines.priority_engine import PriorityEngine
from app.models.entities import Project, Task


class TaskService:
    @staticmethod
    async def list_tasks(
        session: AsyncSession,
        organization_id: UUID,
        assignee_id: UUID | None = None,
        project_id: UUID | None = None,
        is_blocked: bool | None = None,
        overdue_only: bool = False,
    ) -> list[dict[str, Any]]:
        stmt = (
            select(Task, Project.health)
            .join(Project, Task.project_id == Project.id)
            .where(
                Task.organization_id == organization_id,
                Task.deleted_at.is_(None)
            )
        )

        if assignee_id:
            stmt = stmt.where(Task.assignee_id == assignee_id)
        if project_id:
            stmt = stmt.where(Task.project_id == project_id)
        if is_blocked is not None:
            stmt = stmt.where(Task.is_blocked == is_blocked)

        result = await session.execute(stmt)
        rows = result.all()

        now = datetime.now(timezone.utc)
        items = []
        for task, proj_health in rows:
            if overdue_only and (not task.due_date or task.due_date >= now or task.status == "done"):
                continue

            # Evaluate dynamic priority score
            eval_res = PriorityEngine.evaluate(
                sla_due_at=task.due_date,
                is_blocked=task.is_blocked,
                blocked_downstream_count=2 if task.is_blocked else 0,
                impact_level="high" if task.priority == "P0" else "medium",
                target_due_date=task.due_date,
                project_health=proj_health or "healthy",
                now=now,
            )

            items.append({
                "id": str(task.id),
                "project_id": str(task.project_id),
                "title": task.title,
                "description": task.description,
                "status": task.status,
                "priority": eval_res.tier,
                "priority_score": eval_res.score,
                "assignee_id": str(task.assignee_id) if task.assignee_id else None,
                "due_date": task.due_date.isoformat() if task.due_date else None,
                "is_blocked": task.is_blocked,
                "blocker_reason": task.blocker_reason,
            })

        # Order by highest priority score first
        items.sort(key=lambda x: x["priority_score"], reverse=True)
        return items
