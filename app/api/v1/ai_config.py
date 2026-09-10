from typing import Any, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import CurrentTenantUser, require_permission
from app.services.ai_config_service import AIConfigService

router = APIRouter(prefix="/ai/config", tags=["AI Provider Configuration"])


class SaveAIConfigRequest(BaseModel):
    provider: str = Field("google_gemini", description="AI provider: google_gemini, openai, anthropic")
    api_key: str = Field(..., min_length=15, description="Provider API Key")


class AIConfigResponse(BaseModel):
    id: Optional[str] = None
    organization_id: str
    provider: str
    key_fingerprint: str
    status: str
    last_verified_at: Optional[str] = None
    masked_key: Optional[str] = None

    def __init__(self, **data):
        if "key_fingerprint" in data and "masked_key" not in data:
            data["masked_key"] = data["key_fingerprint"]
        super().__init__(**data)


@router.get("")
async def get_ai_config(
    provider: Optional[str] = Query(None),
    user: CurrentTenantUser = Depends(require_permission("ai_config.manage")),
    db: AsyncSession = Depends(get_db),
):
    if not provider:
        return await AIConfigService.list_configs(db, user.organization_id)
    cfg = await AIConfigService.get_config(db, user.organization_id, provider=provider)
    if not cfg:
        return None
    return AIConfigResponse(**cfg)


@router.post("", response_model=AIConfigResponse)
async def save_ai_config(
    req: SaveAIConfigRequest,
    user: CurrentTenantUser = Depends(require_permission("ai_config.manage")),
    db: AsyncSession = Depends(get_db),
):
    res = await AIConfigService.save_config(
        session=db,
        organization_id=user.organization_id,
        user_id=user.user_id,
        provider=req.provider,
        api_key=req.api_key,
    )
    return AIConfigResponse(**res)


@router.delete("")
async def delete_ai_config(
    provider: str = Query("google_gemini"),
    user: CurrentTenantUser = Depends(require_permission("ai_config.manage")),
    db: AsyncSession = Depends(get_db),
):
    success = await AIConfigService.delete_config(db, user.organization_id, user.user_id, provider=provider)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active AI configuration found for this provider."
        )
    return {"status": "deleted", "provider": provider}
