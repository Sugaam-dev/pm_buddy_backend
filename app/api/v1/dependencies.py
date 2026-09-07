from typing import Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query, Security, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import CurrentTenantUser, require_permission
from app.services.dependency_service import DependencyService

router = APIRouter(prefix="/dependencies", tags=["Task Dependencies"])


class AddDependencyRequest(BaseModel):
    task_id: UUID = Field(..., description="Blocked task (successor)")
    depends_on_task_id: UUID = Field(..., description="Prerequisite task (predecessor)")
    project_id: Optional[UUID] = Field(None, description="Project ID")
    dependency_type: str = Field("blocks", description="Type: blocks, depends_on, blocked_by")


@router.get("/tasks/{task_id}")
async def get_task_dependencies(
    task_id: UUID,
    user: CurrentTenantUser = Depends(require_permission("task.read")),
    session: AsyncSession = Depends(get_db),
):
    deps = await DependencyService.get_task_dependencies(session, user.organization_id, task_id)
    return deps


@router.post("", status_code=status.HTTP_201_CREATED)
async def add_dependency(
    body: AddDependencyRequest,
    user: CurrentTenantUser = Depends(require_permission("task.write")),
    session: AsyncSession = Depends(get_db),
):
    try:
        dep = await DependencyService.add_dependency(
            session=session,
            organization_id=user.organization_id,
            project_id=body.project_id,
            task_id=body.task_id,
            depends_on_task_id=body.depends_on_task_id,
            dependency_type=body.dependency_type,
            created_by=user.user_id,
        )
        return {
            "id": str(dep.id),
            "task_id": str(dep.task_id),
            "depends_on_task_id": str(dep.depends_on_task_id),
            "dependency_type": dep.dependency_type,
            "created_at": dep.created_at.isoformat(),
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{dependency_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_dependency(
    dependency_id: UUID,
    user: CurrentTenantUser = Depends(require_permission("task.write")),
    session: AsyncSession = Depends(get_db),
):
    success = await DependencyService.remove_dependency(session, user.organization_id, dependency_id)
    if not success:
        raise HTTPException(status_code=404, detail="Dependency not found")
    return None


@router.get("/blockers")
async def list_blockers(
    project_id: Optional[UUID] = Query(None),
    user: CurrentTenantUser = Depends(require_permission("task.read")),
    session: AsyncSession = Depends(get_db),
):
    blockers = await DependencyService.get_blockers(session, user.organization_id, project_id)
    return {"count": len(blockers), "blockers": blockers}
