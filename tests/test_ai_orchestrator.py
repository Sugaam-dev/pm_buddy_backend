import pytest
from datetime import datetime, timezone
from uuid import uuid4

from app.ai.orchestrator import AIOrchestrator
from app.services.action_service import ActionService
from app.services.calendar_service import LocalCalendarProvider


class InMemoryTestSession:
    """In-memory mock session supporting the AI orchestrator tests."""
    def __init__(self):
        self.added = []
        self.actions = {}

    def add(self, obj):
        self.added.append(obj)
        if hasattr(obj, "id"):
            self.actions[str(obj.id)] = obj

    async def flush(self):
        pass

    async def commit(self):
        pass

    async def execute(self, stmt):
        class MockResult:
            def scalars(self):
                class MockScalars:
                    def all(self):
                        return []
                return MockScalars()
            def all(self):
                return []
            def scalar_one_or_none(self):
                return None
        return MockResult()


@pytest.mark.asyncio
async def test_pm_buddy_approvals_query():
    session = InMemoryTestSession()
    org_id = uuid4()
    user_id = uuid4()
    conv_id = uuid4()

    response = await AIOrchestrator.process_message(
        session=session,
        organization_id=org_id,
        user_id=user_id,
        conversation_id=conv_id,
        prompt="What approvals are pending?",
        user_permissions=["approval.read"],
    )

    assert "approval" in response["text"].lower()
    assert len(response["blocks"]) >= 1
    approval_block = next((b for b in response["blocks"] if b["type"] == "approval_list"), None)
    assert approval_block is not None


@pytest.mark.asyncio
async def test_pm_buddy_schedule_meeting_hitl_flow():
    session = InMemoryTestSession()
    org_id = uuid4()
    user_id = uuid4()
    conv_id = uuid4()

    # Step 1: User asks for available time
    res_slots = await AIOrchestrator.process_message(
        session=session,
        organization_id=org_id,
        user_id=user_id,
        conversation_id=conv_id,
        prompt="Find a suitable time for an architecture review with Rahul",
        user_permissions=["calendar.read", "calendar.write"],
    )

    assert any(b["type"] == "calendar_slots" for b in res_slots["blocks"])

    # Step 2: User requests slot at 2:00 PM -> Generates WAITING_FOR_CONFIRMATION action
    res_confirm = await AIOrchestrator.process_message(
        session=session,
        organization_id=org_id,
        user_id=user_id,
        conversation_id=conv_id,
        prompt="Schedule for 2:00 PM - 2:30 PM",
        user_permissions=["calendar.read", "calendar.write"],
    )

    action_block = next((b for b in res_confirm["blocks"] if b["type"] == "action_confirmation"), None)
    assert action_block is not None
    assert action_block["action_id"] is not None
    assert "human confirmation is required" in res_confirm["text"].lower()


@pytest.mark.asyncio
async def test_pm_buddy_create_meeting_natural_language_datetime():
    from uuid import UUID
    session = InMemoryTestSession()
    org_id = UUID("11111111-1111-1111-1111-111111111111")
    user_id = uuid4()
    conv_id = uuid4()

    # User specifies exact relative date and time in message
    res = await AIOrchestrator.process_message(
        session=session,
        organization_id=org_id,
        user_id=user_id,
        conversation_id=conv_id,
        prompt="Create a meeting with Rahul tomorrow at 10 AM",
        user_permissions=["calendar.read", "calendar.write"],
    )

    action_block = next((b for b in res["blocks"] if b["type"] == "action_confirmation"), None)
    assert action_block is not None
    data = action_block["data"]
    assert "10:00:00" in data["start_time"]
    assert "rahul@pmrgsolution.com" in data["attendee_emails"]


@pytest.mark.asyncio
async def test_pm_buddy_schedule_inquiry():
    session = InMemoryTestSession()
    org_id = uuid4()
    user_id = uuid4()
    conv_id = uuid4()

    # User asks "What is my schedule now?" -> must return upcoming meetings, not slot options
    res = await AIOrchestrator.process_message(
        session=session,
        organization_id=org_id,
        user_id=user_id,
        conversation_id=conv_id,
        prompt="What is my schedule now?",
        user_permissions=["calendar.read", "calendar.write"],
    )

    assert any(b["type"] == "calendar_events" for b in res["blocks"])
    assert not any(b["type"] == "calendar_slots" for b in res["blocks"])


@pytest.mark.asyncio
async def test_pm_buddy_create_meeting_dmy_dev_team():
    from uuid import UUID
    session = InMemoryTestSession()
    org_id = UUID("11111111-1111-1111-1111-111111111111")
    user_id = uuid4()
    conv_id = uuid4()

    prompt = "create onne meeting with dev team for requirement analysis on 13/09/2026 at 12:30:00"
    res = await AIOrchestrator.process_message(
        session=session,
        organization_id=org_id,
        user_id=user_id,
        conversation_id=conv_id,
        prompt=prompt,
        user_permissions=["calendar.read", "calendar.write"],
    )

    action_block = next((b for b in res["blocks"] if b["type"] == "action_confirmation"), None)
    assert action_block is not None
    data = action_block["data"]
    assert data["title"] == "Requirement Analysis"
    assert "2026-09-13T12:30:00" in data["start_time"]
    assert any("pmrgsolution.com" in em for em in data["attendee_emails"])


@pytest.mark.asyncio
async def test_pm_buddy_add_todo_task():
    session = InMemoryTestSession()
    org_id = uuid4()
    user_id = uuid4()
    conv_id = uuid4()

    prompt = "update my todo and add the new task to visit hr department for review"
    res = await AIOrchestrator.process_message(
        session=session,
        organization_id=org_id,
        user_id=user_id,
        conversation_id=conv_id,
        prompt=prompt,
        user_permissions=["task.read", "task.write"],
    )

    assert "Visit HR department for review" in res["text"] or "visit hr department for review" in res["text"].lower()
    assert "To-Do" in res["text"] or "task" in res["text"].lower()
    assert any(b["type"] == "tasks_list" for b in res["blocks"])


@pytest.mark.asyncio
async def test_pm_buddy_create_p1_ticket():
    session = InMemoryTestSession()
    org_id = uuid4()
    user_id = uuid4()
    conv_id = uuid4()

    prompt = "create one p1 ticket for payment infra rebuild"
    res = await AIOrchestrator.process_message(
        session=session,
        organization_id=org_id,
        user_id=user_id,
        conversation_id=conv_id,
        prompt=prompt,
        user_permissions=["ticket.read", "ticket.write"],
    )

    assert "Payment infra rebuild" in res["text"] or "payment infra rebuild" in res["text"].lower()
    assert "CRITICAL" in res["text"] or "P1" in res["text"]
    assert any(b["type"] == "table" for b in res["blocks"])


@pytest.mark.asyncio
async def test_gemini_multi_key_rotation_on_quota_limit():
    import os
    from unittest.mock import MagicMock, patch
    from app.ai.gemini_service import GeminiService
    from google.api_core.exceptions import ResourceExhausted

    # Mock 2 keys in environment
    with patch.dict(os.environ, {"GEMINI_API_KEYS": "key_failing,key_backup"}):
        GeminiService._models.clear()
        GeminiService._key_cooldowns.clear()
        GeminiService._current_key_index = 0

        mock_chat_fail = MagicMock()
        mock_chat_fail.send_message.side_effect = ResourceExhausted("429 Quota reached")

        mock_resp_backup = MagicMock()
        mock_resp_backup.parts = []
        mock_resp_backup.text = "Handled seamlessly by backup key!"
        mock_chat_backup = MagicMock()
        mock_chat_backup.send_message.return_value = mock_resp_backup

        mock_model_fail = MagicMock()
        mock_model_fail.start_chat.return_value = mock_chat_fail

        mock_model_backup = MagicMock()
        mock_model_backup.start_chat.return_value = mock_chat_backup

        def fake_get_model(api_key):
            if "failing" in api_key:
                return mock_model_fail
            return mock_model_backup

        with patch.object(GeminiService, "get_model", side_effect=fake_get_model):
            res = await GeminiService.generate_response(
                session=MagicMock(),
                organization_id=uuid4(),
                user_id=uuid4(),
                conversation_id=uuid4(),
                prompt="test multi key",
                user_permissions=["task.read"],
            )

            assert res["text"] == "Handled seamlessly by backup key!"


