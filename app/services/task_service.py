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
            .outerjoin(Project, Task.project_id == Project.id)
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

    @staticmethod
    async def create_task(
        session: AsyncSession,
        organization_id: UUID,
        title: str,
        description: str | None = None,
        priority: str = "P2",
        status: str = "todo",
        assignee_id: UUID | None = None,
        project_id: UUID | None = None,
        due_date: datetime | None = None,
    ) -> dict[str, Any]:
        """Creates a new task/to-do item."""
        if not project_id:
            proj_stmt = (
                select(Project.id)
                .where(
                    Project.organization_id == organization_id,
                    Project.deleted_at.is_(None)
                )
                .limit(1)
            )
            project_id = (await session.execute(proj_stmt)).scalar_one_or_none()

        priority_clean = priority.upper() if priority and priority.upper() in ["P0", "P1", "P2", "P3"] else "P2"
        score_map = {"P0": 95, "P1": 75, "P2": 50, "P3": 25}

        new_task = Task(
            organization_id=organization_id,
            project_id=project_id,
            title=title.strip(),
            description=description or "",
            priority=priority_clean,
            priority_score=score_map.get(priority_clean, 50),
            status=status or "todo",
            assignee_id=assignee_id,
            due_date=due_date,
        )
        session.add(new_task)
        await session.flush()
        await session.commit()

        return {
            "id": str(new_task.id),
            "project_id": str(new_task.project_id) if new_task.project_id else None,
            "title": new_task.title,
            "description": new_task.description,
            "status": new_task.status,
            "priority": new_task.priority,
            "priority_score": new_task.priority_score,
            "assignee_id": str(new_task.assignee_id) if new_task.assignee_id else None,
            "due_date": new_task.due_date.isoformat() if new_task.due_date else None,
            "is_blocked": new_task.is_blocked,
            "blocker_reason": new_task.blocker_reason,
        }

    @staticmethod
    async def update_task_status(
        session: AsyncSession,
        organization_id: UUID,
        task_id: UUID,
        status: str,
    ) -> dict[str, Any] | None:
        stmt = select(Task).where(
            Task.id == task_id,
            Task.organization_id == organization_id,
            Task.deleted_at.is_(None),
        )
        task = (await session.execute(stmt)).scalar_one_or_none()
        if not task:
            return None
        task.status = status
        await session.flush()
        await session.commit()
        return {"id": str(task.id), "status": task.status}
