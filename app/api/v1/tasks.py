from datetime import datetime
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
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


class CreateTaskRequest(BaseModel):
    title: str
    description: str | None = None
    priority: str = "P2"
    status: str = "todo"
    assignee_id: UUID | None = None
    project_id: UUID | None = None
    due_date: datetime | None = None


@router.post("/")
async def create_task(
    req: CreateTaskRequest,
    user: CurrentTenantUser = Depends(require_permission("task.write")),
    db: AsyncSession = Depends(get_db),
):
    return await TaskService.create_task(
        session=db,
        organization_id=user.organization_id,
        title=req.title,
        description=req.description,
        priority=req.priority,
        status=req.status,
        assignee_id=req.assignee_id,
        project_id=req.project_id,
        due_date=req.due_date,
    )


class UpdateTaskStatusRequest(BaseModel):
    status: str


@router.patch("/{task_id}/status")
async def update_task_status(
    task_id: UUID,
    req: UpdateTaskStatusRequest,
    user: CurrentTenantUser = Depends(require_permission("task.write")),
    db: AsyncSession = Depends(get_db),
):
    res = await TaskService.update_task_status(
        session=db,
        organization_id=user.organization_id,
        task_id=task_id,
        status=req.status,
    )
    if not res:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found.")
    return res
