import pytest
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4
from httpx import ASGITransport, AsyncClient

from app.core.database import AsyncSessionLocal
from app.core.security import create_demo_token, DEMO_USERS
from app.main import app
from app.models.entities import AIAction, AIConversation, AIMessage, Organization, Project, Ticket
from app.services.action_service import ActionService
from app.services.attendee_resolver import AttendeeResolver
from app.services.ticket_service import TicketService
from app.ai.orchestrator import AIOrchestrator
from app.ai.tools import execute_tool

NEXTGEN_ORG_ID = UUID("22222222-2222-2222-2222-222222222222")
PMRG_ORG_ID = UUID("11111111-1111-1111-1111-111111111111")


# =============================================================================
# 1. TICKET CREATION & P0 NORMALIZATION REGRESSION TESTS
# =============================================================================

@pytest.mark.asyncio
async def test_client_operator_can_create_ticket_with_ticket_create():
    """Client Operator has ticket.create and can successfully create a ticket."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        token = create_demo_token("operator@nextgen.com")
        res = await client.post(
            "/api/v1/tickets/",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "title": "Network Gateway Timeout",
                "description": "API requests timing out at edge router",
                "severity": "high",
                "priority": "P2",
            }
        )
        assert res.status_code == 200
        data = res.json()
        assert data["title"] == "Network Gateway Timeout"
        assert data["organization_id"] == str(NEXTGEN_ORG_ID)


@pytest.mark.asyncio
async def test_client_operator_cannot_assign_tickets_without_ticket_assign():
    """Client Operator lacks ticket.assign and cannot reassign tickets."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        token = create_demo_token("operator@nextgen.com")
        fake_ticket_id = uuid4()
        res = await client.post(
            f"/api/v1/tickets/{fake_ticket_id}/assign",
            headers={"Authorization": f"Bearer {token}"},
            json={"assignee_id": str(uuid4())}
        )
        assert res.status_code == 403


@pytest.mark.asyncio
async def test_ai_create_ticket_tool_authorizes_ticket_create():
    """AI create_ticket tool accepts ticket.create without requiring ticket.write."""
    async with AsyncSessionLocal() as session:
        user_id = UUID("20000000-0000-0000-0000-000000000002")
        conv_id = uuid4()
        user_perms = ["ticket.create", "ticket.read", "ai.chat"]

        res = await execute_tool(
            session=session,
            organization_id=NEXTGEN_ORG_ID,
            user_id=user_id,
            conversation_id=conv_id,
            tool_name="create_ticket",
            arguments={
                "title": "Bill API Crash Investigation",
                "severity": "critical",
                "priority": "P0",
            },
            user_permissions=user_perms,
        )
        assert res["success"] is True
        assert "INC-" in res["data"]["ticket"]["ticket_number"]
        assert res["data"]["ticket"]["priority"] == "P0"
        assert res["data"]["ticket"]["severity"] == "critical"


@pytest.mark.asyncio
async def test_p0_natural_language_severity_normalization():
    """Verify natural-language variations of P0/Critical map cleanly to P0 priority and critical severity."""
    async with AsyncSessionLocal() as session:
        user_id = UUID("20000000-0000-0000-0000-000000000002")
        perms = ["ticket.create", "ticket.read", "ai.chat"]

        test_cases = [
            ("create one p0 ticket for bill api cresh", "Bill api cresh", "P0", "critical"),
            ("create a P0 ticket for payment gateway fail", "Payment gateway fail", "P0", "critical"),
            ("create a critical ticket for db corrupted", "Db corrupted", "P0", "critical"),
            ("create one priority 0 ticket for memory leak", "Memory leak", "P0", "critical"),
            ("create a critical priority ticket for server down", "Server down", "P0", "critical"),
        ]

        for prompt, expected_title_sub, expected_prio, expected_sev in test_cases:
            conv_id = uuid4()
            res = await AIOrchestrator.process_message(
                session=session,
                organization_id=NEXTGEN_ORG_ID,
                user_id=user_id,
                conversation_id=conv_id,
                prompt=prompt,
                user_permissions=perms,
            )
            assert res.get("text")
            assert "Ticket Created" in res["text"]
            assert expected_prio in res["text"]
            assert expected_sev.upper() in res["text"]


# =============================================================================
# 2. DETERMINISTIC ATTENDEE RESOLUTION REGRESSION TESTS
# =============================================================================

@pytest.mark.asyncio
async def test_attendee_resolution_nextgen_unresolved_no_alice():
    """In NextGen, requesting rahul, amit, shyam identifies all 3 as unresolved without Alice substitution."""
    async with AsyncSessionLocal() as session:
        resolution = await AttendeeResolver.resolve_attendees(
            session=session,
            organization_id=NEXTGEN_ORG_ID,
            attendee_tokens=["rahul", "amit", "shyam"],
        )
        assert resolution["all_resolved"] is False
        assert set(resolution["unresolved"]) == {"rahul", "amit", "shyam"}
        assert len(resolution["resolved"]) == 0
        # Verify no fabricated emails or Alice substitution
        assert not any("alice" in str(r).lower() for r in resolution["resolved"])
        assert not any("acme.com" in str(r).lower() for r in resolution["resolved"])


@pytest.mark.asyncio
async def test_attendee_resolution_pmrg_resolves_known_user():
    """In PMRG Solution, rahul resolves to rahul@pmrgsolution.com, while amit and shyam remain unresolved."""
    async with AsyncSessionLocal() as session:
        resolution = await AttendeeResolver.resolve_attendees(
            session=session,
            organization_id=PMRG_ORG_ID,
            attendee_tokens=["rahul", "amit", "shyam"],
        )
        assert resolution["all_resolved"] is False
        assert len(resolution["resolved"]) == 1
        assert resolution["resolved"][0]["email"] == "rahul@pmrgsolution.com"
        assert set(resolution["unresolved"]) == {"amit", "shyam"}


@pytest.mark.asyncio
async def test_ai_meeting_scheduling_pauses_when_attendees_unresolved():
    """AI meeting scheduling pauses and reports unresolved attendees rather than proposing false attendees."""
    async with AsyncSessionLocal() as session:
        user_id = UUID("20000000-0000-0000-0000-000000000002")
        conv_id = uuid4()
        perms = ["calendar.read", "calendar.write", "calendar.meeting.confirm", "ai.chat"]

        prompt = "create one meeting with rahul amit shyam for team brief on 15/09/2026 at 15:30 for 30 min"
        res = await AIOrchestrator.process_message(
            session=session,
            organization_id=NEXTGEN_ORG_ID,
            user_id=user_id,
            conversation_id=conv_id,
            prompt=prompt,
            user_permissions=perms,
        )

        assert "Meeting Scheduling Paused" in res["text"]
        assert "Cannot schedule until" in res["text"]
        assert "rahul" in res["text"].lower()
        assert "amit" in res["text"].lower()
        assert "shyam" in res["text"].lower()
        # Verify Alice is NOT substituted
        assert "alice" not in res["text"].lower()


# =============================================================================
# 3. MEETING CONFIRMATION & DOMAIN-SPECIFIC PERMISSION TESTS
# =============================================================================

@pytest.mark.asyncio
async def test_client_operator_can_confirm_calendar_meeting_with_domain_permission():
    """Client Operator with calendar.meeting.confirm can confirm their own proposed meeting."""
    async with AsyncSessionLocal() as session:
        user_id = UUID("20000000-0000-0000-0000-000000000002")
        conv_id = uuid4()

        conv = AIConversation(
            id=conv_id,
            organization_id=NEXTGEN_ORG_ID,
            user_id=user_id,
            title="Meeting Thread",
        )
        session.add(conv)
        await session.flush()

        import random
        from app.models.entities import CalendarEvent
        rand_hours = random.randint(100, 10000)
        start = datetime.now(timezone.utc) + timedelta(days=100, hours=rand_hours)
        end = start + timedelta(minutes=30)

        proposal = await ActionService.propose_action(
            session=session,
            organization_id=NEXTGEN_ORG_ID,
            conversation_id=conv_id,
            tool_name="create_calendar_meeting",
            action_type="create_calendar_meeting",
            payload={
                "title": f"NextGen Sync {rand_hours}",
                "start_time": start.isoformat(),
                "end_time": end.isoformat(),
                "attendee_emails": ["operator@nextgen.com"],
            },
            expires_in_minutes=15,
        )
        await session.commit()
        action_id = UUID(proposal["action_id"])

        # Confirm using Client Operator's permissions (calendar.meeting.confirm, NO action.execute)
        op_perms = DEMO_USERS["operator@nextgen.com"]["permissions"]
        assert "calendar.meeting.confirm" in op_perms
        assert "action.execute" not in op_perms

        confirmed = await ActionService.confirm_action(
            session=session,
            organization_id=NEXTGEN_ORG_ID,
            user_id=user_id,
            action_id=action_id,
            user_permissions=op_perms,
        )
        assert confirmed["status"] == "COMPLETED"
        assert confirmed["result"]["title"] == f"NextGen Sync {rand_hours}"


@pytest.mark.asyncio
async def test_client_operator_cannot_confirm_non_calendar_actions():
    """Client Operator cannot execute non-calendar actions (e.g. project status) with calendar.meeting.confirm."""
    async with AsyncSessionLocal() as session:
        user_id = UUID("20000000-0000-0000-0000-000000000002")
        conv_id = uuid4()

        conv = AIConversation(
            id=conv_id,
            organization_id=NEXTGEN_ORG_ID,
            user_id=user_id,
            title="Non Calendar Action",
        )
        session.add(conv)
        await session.flush()

        proposal = await ActionService.propose_action(
            session=session,
            organization_id=NEXTGEN_ORG_ID,
            conversation_id=conv_id,
            tool_name="change_project_status",
            action_type="change_project_status",
            payload={"project_id": str(uuid4()), "status": "completed"},
            expires_in_minutes=15,
        )
        await session.commit()
        action_id = UUID(proposal["action_id"])

        op_perms = DEMO_USERS["operator@nextgen.com"]["permissions"]

        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await ActionService.confirm_action(
                session=session,
                organization_id=NEXTGEN_ORG_ID,
                user_id=user_id,
                action_id=action_id,
                user_permissions=op_perms,
            )
        assert exc_info.value.status_code == 403
        assert "calendar.meeting.confirm" in exc_info.value.detail


# =============================================================================
# 4. PRIVATE CHAT HISTORY & IDOR ISOLATION REGRESSION TESTS
# =============================================================================

@pytest.mark.asyncio
async def test_private_chat_history_isolation_between_users_same_org():
    """User A's chat history is completely private from User B in the same organization."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. User A (Operator) creates a conversation and posts a message
        token_a = create_demo_token("operator@nextgen.com")
        send_res = await client.post(
            "/api/v1/chat/message",
            headers={"Authorization": f"Bearer {token_a}"},
            json={"prompt": "Confidential plans for User A only"}
        )
        assert send_res.status_code == 200
        conv_a_id = send_res.json()["conversation_id"]

        # 2. User B (Admin in same NextGen org) attempts to read User A's history
        token_b = create_demo_token("client.admin@nextgen.com")
        idor_hist_res = await client.get(
            f"/api/v1/chat/history?conversation_id={conv_a_id}",
            headers={"Authorization": f"Bearer {token_b}"}
        )
        assert idor_hist_res.status_code == 404

        # 3. User B attempts to access User A's conversation detail
        idor_detail_res = await client.get(
            f"/api/v1/chat/conversations/{conv_a_id}",
            headers={"Authorization": f"Bearer {token_b}"}
        )
        assert idor_detail_res.status_code == 404

        # 4. User B lists their conversations -> User A's conversation is NOT present
        list_res = await client.get(
            "/api/v1/chat/conversations",
            headers={"Authorization": f"Bearer {token_b}"}
        )
        assert list_res.status_code == 200
        b_conv_ids = [c["id"] for c in list_res.json()]
        assert conv_a_id not in b_conv_ids

        # 5. User A CAN access their own conversation
        own_res = await client.get(
            f"/api/v1/chat/conversations/{conv_a_id}",
            headers={"Authorization": f"Bearer {token_a}"}
        )
        assert own_res.status_code == 200
        assert own_res.json()["id"] == conv_a_id


@pytest.mark.asyncio
async def test_cross_tenant_chat_history_denied():
    """Cross-tenant user cannot access chat history from another organization."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        token_a = create_demo_token("operator@nextgen.com")
        send_res = await client.post(
            "/api/v1/chat/message",
            headers={"Authorization": f"Bearer {token_a}"},
            json={"prompt": "NextGen private prompt"}
        )
        conv_id = send_res.json()["conversation_id"]

        # PMRG user attempts to read NextGen conversation
        token_pmrg = create_demo_token("pm@pmrgsolution.com")
        res = await client.get(
            f"/api/v1/chat/history?conversation_id={conv_id}",
            headers={"Authorization": f"Bearer {token_pmrg}"}
        )
        assert res.status_code == 404
