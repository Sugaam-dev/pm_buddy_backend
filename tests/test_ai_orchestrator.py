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
