import pytest
from uuid import UUID
from app.ai.gemini_service import GeminiService, ALL_GEMINI_TOOLS
from app.ai.tools import TOOL_METADATA, execute_tool
from app.core.database import AsyncSessionLocal


def test_gemini_api_key_resolution():
    key = GeminiService.get_api_key()
    assert key is not None
    assert len(key) > 20


def test_gemini_tool_registry():
    # Verify all expected tools exist in Gemini tool definitions
    tool_names = [f.__name__ for f in ALL_GEMINI_TOOLS]
    assert "get_my_work" in tool_names
    assert "get_calendar_slots" in tool_names
    assert "get_upcoming_meetings" in tool_names
    assert "get_event_details" in tool_names
    assert "propose_calendar_meeting" in tool_names
    assert "propose_update_calendar_meeting" in tool_names
    assert "propose_cancel_calendar_meeting" in tool_names
    assert "propose_gate_approval" in tool_names


@pytest.mark.asyncio
async def test_gemini_hitl_action_interception():
    """Verify that proposing a calendar meeting intercepts execution and creates a WAITING_FOR_CONFIRMATION proposal."""
    from app.models.entities import AIConversation
    from uuid import uuid4

    async with AsyncSessionLocal() as session:
        org_id = UUID("11111111-1111-1111-1111-111111111111")
        user_id = UUID("10000000-0000-0000-0000-000000000001")
        conv_id = uuid4()
        perms = ["*"]

        # Ensure conversation exists for foreign key constraint
        conv = AIConversation(
            id=conv_id,
            organization_id=org_id,
            user_id=user_id,
            persona="pm_buddy",
            title="Test Conversation",
        )
        session.add(conv)
        await session.flush()

        res = await execute_tool(
            session=session,
            organization_id=org_id,
            user_id=user_id,
            conversation_id=conv_id,
            tool_name="propose_calendar_meeting",
            arguments={
                "title": "Security Gate Review",
                "attendee_emails": ["alice@acme.com", "charlie@acme.com"],
                "start_time": "2026-09-09T10:00:00Z",
                "end_time": "2026-09-09T10:30:00Z",
                "description": "Gate sign-off review",
            },
            user_permissions=perms,
        )

        assert res["success"] is True
        assert res["is_sensitive"] is True
        assert "action_id" in res
        assert "Confirm Action: Propose Calendar Meeting" in res["blocks"][0]["title"]
