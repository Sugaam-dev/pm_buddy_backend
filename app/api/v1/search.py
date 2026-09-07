from typing import Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import CurrentTenantUser, get_current_tenant_user
from app.services.search_service import SearchService

router = APIRouter(prefix="/search", tags=["Global Search"])


@router.get("")
async def global_search(
    q: str = Query(..., min_length=1, description="Search term across entities"),
    category: Optional[str] = Query(None, description="Optional category filter: projects, tasks, tickets, risks, approvals, calendar, knowledge"),
    limit: int = Query(5, ge=1, le=20),
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    session: AsyncSession = Depends(get_db),
):
    search_results = await SearchService.global_search(
        session=session,
        organization_id=user.organization_id,
        query=q,
        user_permissions=user.permissions,
        category=category,
        limit_per_category=limit,
    )
    return search_results
