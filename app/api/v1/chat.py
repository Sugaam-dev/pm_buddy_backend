from datetime import datetime, timezone
from uuid import UUID, uuid4
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.orchestrator import AIOrchestrator
from app.core.database import get_db
from app.core.security import CurrentTenantUser, require_permission
from app.models.entities import AIConversation, AIMessage

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

    # Ensure conversation exists
    try:
        conv_stmt = select(AIConversation).where(
            AIConversation.id == conv_id,
            AIConversation.organization_id == user.organization_id,
        )
        conv = (await db.execute(conv_stmt)).scalar_one_or_none()
        if not conv:
            conv = AIConversation(
                id=conv_id,
                organization_id=user.organization_id,
                user_id=user.user_id,
                persona="pm_buddy",
                title=req.prompt[:60],
            )
            db.add(conv)
            await db.flush()

        # Save user message
        user_msg = AIMessage(
            id=uuid4(),
            organization_id=user.organization_id,
            conversation_id=conv_id,
            sender_type="user",
            content=req.prompt,
            created_at=datetime.now(timezone.utc),
        )
        db.add(user_msg)
        await db.flush()
    except Exception:
        pass

    res = await AIOrchestrator.process_message(
        session=db,
        organization_id=user.organization_id,
        user_id=user.user_id,
        conversation_id=conv_id,
        prompt=req.prompt,
        user_permissions=user.permissions,
    )

    # Save assistant message
    try:
        assistant_msg = AIMessage(
            id=uuid4(),
            organization_id=user.organization_id,
            conversation_id=conv_id,
            sender_type="assistant",
            content=res.get("text", ""),
            structured_payload=res.get("blocks"),
            created_at=datetime.now(timezone.utc),
        )
        db.add(assistant_msg)
        await db.commit()
    except Exception:
        pass

    return res


@router.get("/history")
async def get_chat_history(
    conversation_id: UUID | None = None,
    user: CurrentTenantUser = Depends(require_permission("ai.chat")),
    db: AsyncSession = Depends(get_db),
):
    target_conv_id = conversation_id
    if not target_conv_id:
        # Find latest active conversation for user
        conv_stmt = (
            select(AIConversation)
            .where(
                AIConversation.organization_id == user.organization_id,
                AIConversation.user_id == user.user_id,
            )
            .order_by(AIConversation.updated_at.desc())
            .limit(1)
        )
        latest_conv = (await db.execute(conv_stmt)).scalar_one_or_none()
        if latest_conv:
            target_conv_id = latest_conv.id

    if not target_conv_id:
        return {"conversation_id": None, "messages": []}

    msg_stmt = (
        select(AIMessage)
        .where(
            AIMessage.conversation_id == target_conv_id,
            AIMessage.organization_id == user.organization_id,
        )
        .order_by(AIMessage.created_at.asc())
    )
    messages = (await db.execute(msg_stmt)).scalars().all()

    return {
        "conversation_id": str(target_conv_id),
        "messages": [
            {
                "id": str(m.id),
                "sender": m.sender_type,
                "text": m.content,
                "blocks": m.structured_payload or [],
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in messages
        ],
    }
