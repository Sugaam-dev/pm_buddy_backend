from uuid import UUID
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import CurrentTenantUser, require_permission
from app.services.risk_service import RiskService

router = APIRouter(prefix="/risks", tags=["Risks"])


@router.get("/")
async def list_risks(
    project_id: UUID | None = None,
    user: CurrentTenantUser = Depends(require_permission("risk.read")),
    db: AsyncSession = Depends(get_db),
):
    return await RiskService.list_risks(db, user.organization_id, project_id=project_id)
