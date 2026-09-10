from datetime import datetime, timezone
from uuid import UUID, uuid4
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.orchestrator import AIOrchestrator
from app.core.database import get_db
from app.core.security import CurrentTenantUser, require_permission
from app.models.entities import AIConversation, AIMessage

router = APIRouter(prefix="/chat", tags=["PM Buddy AI Chat"])


class ChatMessageRequest(BaseModel):
    conversation_id: UUID | None = Field(None, description="UUID of thread, created if null")
    prompt: str = Field(..., description="User prompt or question to PM Buddy")


class RenameConversationRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=255, description="New conversation title")


@router.post("/message")
async def send_chat_message(
    req: ChatMessageRequest,
    user: CurrentTenantUser = Depends(require_permission("ai.chat")),
    db: AsyncSession = Depends(get_db),
):
    if req.conversation_id:
        # IDOR check: conversation must belong strictly to this user and organization
        conv_stmt = select(AIConversation).where(
            AIConversation.id == req.conversation_id,
            AIConversation.organization_id == user.organization_id,
            AIConversation.user_id == user.user_id,
        )
        conv = (await db.execute(conv_stmt)).scalar_one_or_none()
        if not conv:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found.")
        conv_id = req.conversation_id
    else:
        conv_id = uuid4()
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

    res = await AIOrchestrator.process_message(
        session=db,
        organization_id=user.organization_id,
        user_id=user.user_id,
        conversation_id=conv_id,
        prompt=req.prompt,
        user_permissions=user.permissions,
    )

    # Save assistant message
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
    conv.updated_at = datetime.now(timezone.utc)
    await db.commit()

    res["conversation_id"] = str(conv_id)
    return res


@router.get("/history")
async def get_chat_history(
    conversation_id: UUID | None = None,
    user: CurrentTenantUser = Depends(require_permission("ai.chat")),
    db: AsyncSession = Depends(get_db),
):
    if conversation_id:
        conv_stmt = select(AIConversation).where(
            AIConversation.id == conversation_id,
            AIConversation.organization_id == user.organization_id,
            AIConversation.user_id == user.user_id,
        )
        conv = (await db.execute(conv_stmt)).scalar_one_or_none()
        if not conv:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found.")
        target_conv_id = conv.id
    else:
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
        if not latest_conv:
            return {"conversation_id": None, "messages": []}
        target_conv_id = latest_conv.id

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


@router.get("/conversations")
async def list_conversations(
    user: CurrentTenantUser = Depends(require_permission("ai.chat")),
    db: AsyncSession = Depends(get_db),
):
    """Lists conversations strictly belonging to the authenticated user and organization."""
    stmt = (
        select(AIConversation)
        .where(
            AIConversation.organization_id == user.organization_id,
            AIConversation.user_id == user.user_id,
        )
        .order_by(AIConversation.updated_at.desc())
    )
    convs = (await db.execute(stmt)).scalars().all()
    return [
        {
            "id": str(c.id),
            "title": c.title,
            "created_at": c.created_at.isoformat() if c.created_at else None,
            "updated_at": c.updated_at.isoformat() if c.updated_at else None,
        }
        for c in convs
    ]


@router.get("/conversations/{conversation_id}")
async def get_conversation_detail(
    conversation_id: UUID,
    user: CurrentTenantUser = Depends(require_permission("ai.chat")),
    db: AsyncSession = Depends(get_db),
):
    """Fetches conversation metadata and messages with strict IDOR 404 protection."""
    conv_stmt = select(AIConversation).where(
        AIConversation.id == conversation_id,
        AIConversation.organization_id == user.organization_id,
        AIConversation.user_id == user.user_id,
    )
    conv = (await db.execute(conv_stmt)).scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found.")

    msg_stmt = (
        select(AIMessage)
        .where(
            AIMessage.conversation_id == conversation_id,
            AIMessage.organization_id == user.organization_id,
        )
        .order_by(AIMessage.created_at.asc())
    )
    messages = (await db.execute(msg_stmt)).scalars().all()

    return {
        "id": str(conv.id),
        "title": conv.title,
        "created_at": conv.created_at.isoformat() if conv.created_at else None,
        "updated_at": conv.updated_at.isoformat() if conv.updated_at else None,
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


@router.delete("/conversations/{conversation_id}")
async def delete_conversation(
    conversation_id: UUID,
    user: CurrentTenantUser = Depends(require_permission("ai.chat")),
    db: AsyncSession = Depends(get_db),
):
    """Deletes conversation with strict IDOR 404 protection."""
    conv_stmt = select(AIConversation).where(
        AIConversation.id == conversation_id,
        AIConversation.organization_id == user.organization_id,
        AIConversation.user_id == user.user_id,
    )
    conv = (await db.execute(conv_stmt)).scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found.")

    await db.execute(
        delete(AIMessage).where(
            AIMessage.conversation_id == conversation_id,
            AIMessage.organization_id == user.organization_id,
        )
    )
    await db.delete(conv)
    await db.commit()
    return {"deleted": True, "conversation_id": str(conversation_id)}

