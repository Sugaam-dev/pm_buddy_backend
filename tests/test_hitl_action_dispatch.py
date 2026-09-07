import pytest
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4
from fastapi import HTTPException

from app.models.entities import AIAction, Approval, AuditLog, OutboxEvent, Project, Ticket
from app.services.action_service import ActionService


class ActionTestSession:
    """Mock async session supporting polymorphic entity mutations and queries."""

    def __init__(self, entities: list[Any] | None = None):
        self.entities: dict[UUID, Any] = {e.id: e for e in (entities or []) if hasattr(e, "id")}
        self.added: list[Any] = []
        self.committed = False
        self.flushed = False

    def add(self, obj: Any):
        self.added.append(obj)
        if hasattr(obj, "id"):
            self.entities[obj.id] = obj

    async def flush(self):
        self.flushed = True

    async def commit(self):
        self.committed = True

    async def execute(self, stmt):
        entities_list = list(self.entities.values())

        class MockResult:
            def __init__(self, items):
                self.items = items

            def scalar_one_or_none(self):
                return self.items[0] if self.items else None

            def scalars(self):
                class MockScalars:
                    def __init__(self, inner):
                        self.inner = inner

                    def all(self):
                        return self.inner

                return MockScalars(self.items)

            def all(self):
                return [(i,) for i in self.items]

        # Determine target entity from statement string representation
        stmt_str = str(stmt).lower()
        if "ai_actions" in stmt_str:
            matches = [e for e in entities_list if isinstance(e, AIAction)]
            return MockResult(matches)
        elif "tickets" in stmt_str:
            matches = [e for e in entities_list if isinstance(e, Ticket)]
            return MockResult(matches)
        elif "approvals" in stmt_str:
            matches = [e for e in entities_list if isinstance(e, Approval)]
            return MockResult(matches)
        elif "projects" in stmt_str:
            matches = [e for e in entities_list if isinstance(e, Project)]
            return MockResult(matches)

        return MockResult(entities_list)


@pytest.mark.asyncio
async def test_dispatch_assign_ticket():
    """Verifies that confirming an 'assign_ticket' action mutates the real Ticket assignee."""
    org_id = uuid4()
    user_id = uuid4()
    ticket_id = uuid4()
    new_assignee_id = uuid4()
    action_id = uuid4()

    ticket = Ticket(
        id=ticket_id,
        organization_id=org_id,
        ticket_number="INC-101",
        title="Production API latency spike",
        category="infrastructure",
        severity="critical",
        priority="P0",
        status="open",
        affected_service="api-gateway",
        sla_due_at=datetime.now(timezone.utc) + timedelta(hours=2),
    )

    action = AIAction(
        id=action_id,
        organization_id=org_id,
        conversation_id=uuid4(),
        tool_name="propose_ticket_assignment",
        action_type="assign_ticket",
        payload={
            "ticket_id": str(ticket_id),
            "assignee_id": str(new_assignee_id),
            "notes": "Assigned to on-call engineer",
        },
        status="WAITING_FOR_CONFIRMATION",
        idempotency_key="act_assign_1",
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=15),
    )

    session = ActionTestSession(entities=[ticket, action])
    result = await ActionService.confirm_action(
        session=session,
        organization_id=org_id,
        user_id=user_id,
        action_id=action_id,
    )

    assert result["status"] == "COMPLETED"
    assert result["result"]["assignee_id"] == str(new_assignee_id)
    assert ticket.assignee_id == new_assignee_id
    assert ticket.status == "in_progress"

    # Verify audit log & outbox
    audit_logs = [obj for obj in session.added if isinstance(obj, AuditLog)]
    assert len(audit_logs) == 1
    assert audit_logs[0].result == "SUCCESS"

    outbox_events = [obj for obj in session.added if isinstance(obj, OutboxEvent)]
    assert any(o.event_type == "ACTION_COMPLETED" for o in outbox_events)


@pytest.mark.asyncio
async def test_dispatch_send_escalation():
    """Verifies that confirming 'send_escalation' creates escalation domain outbox event and audit log."""
    org_id = uuid4()
    user_id = uuid4()
    action_id = uuid4()
    approval_id = uuid4()

    action = AIAction(
        id=action_id,
        organization_id=org_id,
        conversation_id=uuid4(),
        tool_name="propose_escalation",
        action_type="send_escalation",
        payload={
            "approval_id": str(approval_id),
            "escalate_to": "cto@acme.com",
            "reason": "SLA breach of 48 hours on security audit gate",
        },
        status="WAITING_FOR_CONFIRMATION",
        idempotency_key="act_esc_1",
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=15),
    )

    session = ActionTestSession(entities=[action])
    result = await ActionService.confirm_action(
        session=session,
        organization_id=org_id,
        user_id=user_id,
        action_id=action_id,
    )

    assert result["status"] == "COMPLETED"
    assert result["result"]["escalated"] is True

    # Check APPROVAL_ESCALATED domain event
    outbox_events = [obj for obj in session.added if isinstance(obj, OutboxEvent)]
    esc_event = next((o for o in outbox_events if o.event_type == "APPROVAL_ESCALATED"), None)
    assert esc_event is not None
    assert esc_event.payload["escalate_to"] == "cto@acme.com"


@pytest.mark.asyncio
async def test_dispatch_approve_gate():
    """Verifies that confirming 'approve_gate' mutates the Approval status."""
    org_id = uuid4()
    user_id = uuid4()
    approval_id = uuid4()
    action_id = uuid4()

    approval = Approval(
        id=approval_id,
        organization_id=org_id,
        project_id=uuid4(),
        title="Security Compliance Review",
        stage="compliance",
        status="pending",
        approver_id=user_id,
        sla_due_at=datetime.now(timezone.utc) + timedelta(days=1),
    )

    action = AIAction(
        id=action_id,
        organization_id=org_id,
        conversation_id=uuid4(),
        tool_name="propose_gate_approval",
        action_type="approve_gate",
        payload={
            "approval_id": str(approval_id),
            "decision": "approved",
            "notes": "Verified SOC2 compliance checklist.",
        },
        status="WAITING_FOR_CONFIRMATION",
        idempotency_key="act_appr_1",
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=15),
    )

    session = ActionTestSession(entities=[approval, action])
    result = await ActionService.confirm_action(
        session=session,
        organization_id=org_id,
        user_id=user_id,
        action_id=action_id,
    )

    assert result["status"] == "COMPLETED"
    assert result["result"]["status"] == "approved"
    assert approval.status == "approved"


@pytest.mark.asyncio
async def test_dispatch_change_project_status():
    """Verifies that confirming 'change_project_status' mutates project status and health."""
    org_id = uuid4()
    user_id = uuid4()
    project_id = uuid4()
    action_id = uuid4()

    project = Project(
        id=project_id,
        organization_id=org_id,
        name="Project Alpha",
        key="ALPHA",
        status="active",
        health="on_track",
    )

    action = AIAction(
        id=action_id,
        organization_id=org_id,
        conversation_id=uuid4(),
        tool_name="propose_project_status_change",
        action_type="change_project_status",
        payload={
            "project_id": str(project_id),
            "status": "on_hold",
            "health": "critical",
            "reason": "Unresolved database migration blocker",
        },
        status="WAITING_FOR_CONFIRMATION",
        idempotency_key="act_proj_1",
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=15),
    )

    session = ActionTestSession(entities=[project, action])
    result = await ActionService.confirm_action(
        session=session,
        organization_id=org_id,
        user_id=user_id,
        action_id=action_id,
    )

    assert result["status"] == "COMPLETED"
    assert result["result"]["status"] == "on_hold"
    assert result["result"]["health"] == "critical"
    assert project.status == "on_hold"
    assert project.health == "critical"


@pytest.mark.asyncio
async def test_idempotent_confirmation():
    """Verifies that re-confirming an already COMPLETED action returns idempotent success."""
    org_id = uuid4()
    user_id = uuid4()
    action_id = uuid4()

    action = AIAction(
        id=action_id,
        organization_id=org_id,
        conversation_id=uuid4(),
        tool_name="propose_calendar_meeting",
        action_type="create_calendar_meeting",
        payload={"title": "Team Sync"},
        status="COMPLETED",
        result={"event_id": "mock_event_123"},
        idempotency_key="act_idemp_1",
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=15),
    )

    session = ActionTestSession(entities=[action])
    result = await ActionService.confirm_action(
        session=session,
        organization_id=org_id,
        user_id=user_id,
        action_id=action_id,
    )

    assert result["status"] == "COMPLETED"
    assert result["message"] == "Action previously executed successfully."
