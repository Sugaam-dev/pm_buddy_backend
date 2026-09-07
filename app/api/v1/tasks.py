from uuid import UUID
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import CurrentTenantUser, require_permission
from app.services.task_service import TaskService

router = APIRouter(prefix="/tasks", tags=["Tasks"])


@router.get("/")
async def list_tasks(
    project_id: UUID | None = None,
    assignee_id: UUID | None = None,
    is_blocked: bool | None = None,
    overdue_only: bool = Query(False),
    user: CurrentTenantUser = Depends(require_permission("task.read")),
    db: AsyncSession = Depends(get_db),
):
    return await TaskService.list_tasks(
        session=db,
        organization_id=user.organization_id,
        assignee_id=assignee_id,
        project_id=project_id,
        is_blocked=is_blocked,
        overdue_only=overdue_only,
    )
