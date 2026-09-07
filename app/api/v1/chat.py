from uuid import UUID, uuid4
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.orchestrator import AIOrchestrator
from app.core.database import get_db
from app.core.security import CurrentTenantUser, require_permission

router = APIRouter(prefix="/chat", tags=["PM Buddy AI Chat"])


class ChatMessageRequest(BaseModel):
    conversation_id: UUID | None = Field(None, description="UUID of thread, created if null")
    prompt: str = Field(..., description="User prompt or question to PM Buddy")


@router.post("/message")
async def send_chat_message(
    req: ChatMessageRequest,
    user: CurrentTenantUser = Depends(require_permission("ai.chat")),
    db: AsyncSession = Depends(get_db),
):
    conv_id = req.conversation_id or uuid4()
    return await AIOrchestrator.process_message(
        session=db,
        organization_id=user.organization_id,
        user_id=user.user_id,
        conversation_id=conv_id,
        prompt=req.prompt,
        user_permissions=user.permissions,
    )
