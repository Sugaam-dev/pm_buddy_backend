from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import CurrentTenantUser, get_current_tenant_user, require_permission
from app.services.project_service import ProjectService

router = APIRouter(prefix="/projects", tags=["Projects"])


@router.get("/")
async def list_projects(
    user: CurrentTenantUser = Depends(require_permission("project.read")),
    db: AsyncSession = Depends(get_db),
):
    return await ProjectService.list_projects(db, user.organization_id)


@router.get("/{project_id}/dashboard")
async def get_project_dashboard(
    project_id: UUID,
    user: CurrentTenantUser = Depends(require_permission("project.read")),
    db: AsyncSession = Depends(get_db),
):
    dash = await ProjectService.get_project_dashboard(db, user.organization_id, project_id)
    if not dash:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found in your organization."
        )
    return dash
