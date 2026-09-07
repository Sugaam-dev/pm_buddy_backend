from typing import Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query, Security
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import CurrentTenantUser, require_permission
from app.engines.project_health_engine import ProjectHealthEngine
from app.services.daily_briefing_service import DailyBriefingService
from app.services.recommendation_service import RecommendationService

router = APIRouter(prefix="/intelligence", tags=["Operational Intelligence"])


@router.get("/briefing")
async def get_daily_briefing(
    date: Optional[str] = Query(None, description="ISO date (YYYY-MM-DD) for briefing target"),
    user: CurrentTenantUser = Depends(require_permission("project.read")),
    session: AsyncSession = Depends(get_db),
):
    briefing = await DailyBriefingService.get_daily_briefing(session, user.organization_id, date)
    return briefing


@router.get("/recommendations")
async def get_action_recommendations(
    limit: int = Query(5, ge=1, le=20),
    user: CurrentTenantUser = Depends(require_permission("project.read")),
    session: AsyncSession = Depends(get_db),
):
    recs = await RecommendationService.get_action_recommendations(session, user.organization_id, limit)
    return {"count": len(recs), "recommendations": recs}


@router.get("/project-health/{project_id}")
async def get_project_health_breakdown(
    project_id: UUID,
    user: CurrentTenantUser = Depends(require_permission("project.read")),
    session: AsyncSession = Depends(get_db),
):
    try:
        health = await ProjectHealthEngine.evaluate_project_health(session, user.organization_id, project_id)
        return health
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
