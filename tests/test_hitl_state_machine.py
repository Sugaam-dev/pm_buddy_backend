import pytest
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from fastapi import HTTPException

from app.services.action_service import ActionService
from app.models.entities import AIAction


class MockSession:
    """Mock async session for hermetic action testing."""
    def __init__(self, action: AIAction | None = None):
        self.action = action
        self.added = []
        self.committed = False
        self.flushed = False

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        self.flushed = True

    async def commit(self):
        self.committed = True

    async def execute(self, stmt):
        class ScalarResult:
            def __init__(self, val):
                self.val = val
            def scalar_one_or_none(self):
                return self.val
        return ScalarResult(self.action)


@pytest.mark.asyncio
async def test_action_proposal_creation():
    session = MockSession()
    org_id = uuid4()
    conv_id = uuid4()

    proposal = await ActionService.propose_action(
        session=session,
        organization_id=org_id,
        conversation_id=conv_id,
        tool_name="create_calendar_meeting",
        action_type="create_calendar_meeting",
        payload={"title": "Architecture Gate Review"},
        expires_in_minutes=15,
    )

    assert proposal["status"] == "WAITING_FOR_CONFIRMATION"
    assert proposal["tool_name"] == "create_calendar_meeting"
    assert session.flushed is True


@pytest.mark.asyncio
async def test_action_confirm_expired_rejected():
    org_id = uuid4()
    user_id = uuid4()
    action_id = uuid4()

    expired_action = AIAction(
        id=action_id,
        organization_id=org_id,
        conversation_id=uuid4(),
        tool_name="create_calendar_meeting",
        action_type="create_calendar_meeting",
        payload={"title": "Meeting"},
        status="WAITING_FOR_CONFIRMATION",
        idempotency_key="test_key_1",
        expires_at=datetime.now(timezone.utc) - timedelta(minutes=5),  # Expired
    )
    session = MockSession(action=expired_action)

    with pytest.raises(HTTPException) as exc_info:
        await ActionService.confirm_action(
            session=session,
            organization_id=org_id,
            user_id=user_id,
            action_id=action_id,
        )

    assert exc_info.value.status_code == 410
    assert "expired" in exc_info.value.detail.lower()
