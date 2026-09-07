import logging
from typing import List, Optional
from uuid import UUID, uuid4

from sqlalchemy import and_, delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import Task, TaskDependency

logger = logging.getLogger(__name__)


class DependencyService:
    @staticmethod
    async def _would_create_cycle(
        session: AsyncSession,
        organization_id: UUID,
        task_id: UUID,  # successor
        depends_on_task_id: UUID,  # predecessor
    ) -> bool:
        """Checks whether making `task_id` depend on `depends_on_task_id` creates a cycle.
        A cycle occurs if `depends_on_task_id` already depends on `task_id` directly or transitively.
        """
        if task_id == depends_on_task_id:
            return True

        # Fetch all dependencies in the organization
        stmt = select(TaskDependency.task_id, TaskDependency.depends_on_task_id).where(
            TaskDependency.organization_id == organization_id
        )
        res = await session.execute(stmt)
        edges = res.fetchall()

        # Build adjacency graph: successor -> predecessors
        # We want to check if task_id can reach depends_on_task_id by following existing dependencies,
        # or if depends_on_task_id already depends on task_id.
        graph = {}
        for succ, pred in edges:
            graph.setdefault(succ, []).append(pred)

        # BFS/DFS starting from `depends_on_task_id` to see if it reaches `task_id`
        visited = set()
        queue = [depends_on_task_id]

        while queue:
            curr = queue.pop(0)
            if curr == task_id:
                return True
            if curr not in visited:
                visited.add(curr)
                for predecessor in graph.get(curr, []):
                    if predecessor not in visited:
                        queue.append(predecessor)

        return False

    @staticmethod
    async def add_dependency(
        session: AsyncSession,
        organization_id: UUID,
        project_id: Optional[UUID],
        task_id: UUID,  # successor (blocked task)
        depends_on_task_id: UUID,  # predecessor (blocking task)
        dependency_type: str = "blocks",
        created_by: Optional[UUID] = None,
    ) -> TaskDependency:
        """Adds a dependency between two tasks, ensuring no circular dependencies exist."""
        # Verify both tasks exist and belong to organization
        stmt = select(Task).where(
            Task.id.in_([task_id, depends_on_task_id]),
            Task.organization_id == organization_id,
        )
        res = await session.execute(stmt)
        tasks = res.scalars().all()
        if len(tasks) < 2 and task_id != depends_on_task_id:
            raise ValueError("One or both tasks not found in the organization.")

        # Cycle detection
        is_cycle = await DependencyService._would_create_cycle(
            session, organization_id, task_id, depends_on_task_id
        )
        if is_cycle:
            raise ValueError("Circular dependency detected: adding this link would create an execution cycle.")

        # Check existing
        check_stmt = select(TaskDependency).where(
            TaskDependency.organization_id == organization_id,
            TaskDependency.task_id == task_id,
            TaskDependency.depends_on_task_id == depends_on_task_id,
        )
        existing = (await session.execute(check_stmt)).scalar_one_or_none()
        if existing:
            return existing

        dep = TaskDependency(
            id=uuid4(),
            organization_id=organization_id,
            project_id=project_id or tasks[0].project_id,
            task_id=task_id,
            depends_on_task_id=depends_on_task_id,
            dependency_type=dependency_type,
            created_by=created_by,
        )
        session.add(dep)
        await session.commit()
        await session.refresh(dep)
        return dep

    @staticmethod
    async def remove_dependency(
        session: AsyncSession,
        organization_id: UUID,
        dependency_id: UUID,
    ) -> bool:
        """Removes a dependency."""
        stmt = select(TaskDependency).where(
            TaskDependency.id == dependency_id,
            TaskDependency.organization_id == organization_id,
        )
        res = await session.execute(stmt)
        dep = res.scalar_one_or_none()
        if not dep:
            return False

        await session.delete(dep)
        await session.commit()
        return True

    @staticmethod
    async def get_task_dependencies(
        session: AsyncSession,
        organization_id: UUID,
        task_id: UUID,
    ) -> dict:
        """Returns predecessors (tasks this task depends on) and successors (tasks depending on this task)."""
        # Predecessors: this task is task_id, depending on depends_on_task_id
        pred_stmt = (
            select(TaskDependency, Task)
            .join(Task, Task.id == TaskDependency.depends_on_task_id)
            .where(
                TaskDependency.organization_id == organization_id,
                TaskDependency.task_id == task_id,
            )
        )
        pred_res = await session.execute(pred_stmt)
        predecessors = [
            {
                "dependency_id": str(dep.id),
                "task_id": str(t.id),
                "title": t.title,
                "status": t.status,
                "priority": t.priority,
                "is_completed": t.status == "done",
                "dependency_type": dep.dependency_type,
            }
            for dep, t in pred_res.all()
        ]

        # Successors: this task is depends_on_task_id, blocking task_id
        succ_stmt = (
            select(TaskDependency, Task)
            .join(Task, Task.id == TaskDependency.task_id)
            .where(
                TaskDependency.organization_id == organization_id,
                TaskDependency.depends_on_task_id == task_id,
            )
        )
        succ_res = await session.execute(succ_stmt)
        successors = [
            {
                "dependency_id": str(dep.id),
                "task_id": str(t.id),
                "title": t.title,
                "status": t.status,
                "priority": t.priority,
                "dependency_type": dep.dependency_type,
            }
            for dep, t in succ_res.all()
        ]

        return {
            "task_id": str(task_id),
            "predecessors": predecessors,
            "successors": successors,
            "is_blocked": any(not p["is_completed"] for p in predecessors),
        }

    @staticmethod
    async def get_blockers(
        session: AsyncSession,
        organization_id: UUID,
        project_id: Optional[UUID] = None,
    ) -> List[dict]:
        """Lists all tasks that are currently blocked by incomplete predecessor tasks."""
        stmt = (
            select(TaskDependency, Task)
            .join(Task, Task.id == TaskDependency.task_id)
            .where(TaskDependency.organization_id == organization_id)
        )
        if project_id:
            stmt = stmt.where(Task.project_id == project_id)

        rows = (await session.execute(stmt)).all()
        blocked_summary = []

        # Find all uncompleted predecessor tasks
        for dep, succ_task in rows:
            if succ_task.status == "done":
                continue

            pred_task = (await session.execute(
                select(Task).where(Task.id == dep.depends_on_task_id)
            )).scalar_one_or_none()

            if pred_task and pred_task.status != "done":
                blocked_summary.append({
                    "blocked_task_id": str(succ_task.id),
                    "blocked_task_title": succ_task.title,
                    "blocked_task_priority": succ_task.priority,
                    "blocking_task_id": str(pred_task.id),
                    "blocking_task_title": pred_task.title,
                    "blocking_task_status": pred_task.status,
                    "dependency_type": dep.dependency_type,
                })

        return blocked_summary
