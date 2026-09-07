import asyncio
import os
import sys
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.database import AsyncSessionLocal
from app.ai.orchestrator import AIOrchestrator
from app.services.action_service import ActionService
from app.services.ticket_service import TicketService
from app.services.approval_service import ApprovalService
from app.services.project_service import ProjectService
from app.models.entities import Ticket, Project, Approval, AuditLog, OutboxEvent
from sqlalchemy import select

ORG_ID = UUID("11111111-1111-1111-1111-111111111111")
USER_ALICE = UUID("10000000-0000-0000-0000-000000000001")
PERMS = ["project.read", "project.write", "task.read", "task.write", "ticket.read", "ticket.write", "ticket.assign", "approval.read", "approval.approve", "approval.write", "risk.read", "calendar.read", "calendar.write", "ai.chat", "action.execute"]

QUERIES = [
    "What should I focus on right now?",
    "Show me my highest priority tasks.",
    "Which tickets are at risk of SLA breach?",
    "Why is this task P0?",
    "What approvals are waiting for me?",
    "What are the biggest risks in my project?",
    "Find me a meeting slot tomorrow."
]

async def verify_queries_and_hitl():
    print("====================================================")
    print("1. VERIFYING 7 PM BUDDY NATURAL LANGUAGE QUERIES")
    print("====================================================")
    async with AsyncSessionLocal() as session:
        for idx, q in enumerate(QUERIES, 1):
            res = await AIOrchestrator._deterministic_fallback(
                session=session,
                organization_id=ORG_ID,
                user_id=USER_ALICE,
                conversation_id=UUID("00000000-0000-0000-0000-000000000099"),
                prompt=q,
                user_permissions=PERMS,
            )
            print(f"\n[Query {idx}]: \"{q}\"")
            print(f"Response Summary: {res['text'][:120]}...")
            print(f"Blocks generated: {len(res.get('blocks', []))} ({[b.get('type') for b in res.get('blocks', [])]})")
            assert len(res["text"]) > 0, f"Query {idx} returned empty text"

    print("\n====================================================")
    print("2. VERIFYING 3 HITL MUTATION WORKFLOWS (DATABASE -> AUDIT -> OUTBOX)")
    print("====================================================")

    CONV_ID = UUID("00000000-0000-0000-0000-000000000099")
    async with AsyncSessionLocal() as session:
        from app.models.entities import AIConversation
        conv_res = await session.execute(select(AIConversation).where(AIConversation.id == CONV_ID))
        if not conv_res.scalar_one_or_none():
            conv = AIConversation(
                id=CONV_ID,
                organization_id=ORG_ID,
                user_id=USER_ALICE,
                persona="pm_buddy",
                title="E2E Demo Verification Thread",
            )
            session.add(conv)
            await session.commit()
            print(f"Created demo AI conversation: {CONV_ID}")

    # Demo Flow 1: Assign highest priority ticket
    async with AsyncSessionLocal() as session:
        print("\n--- HITL Flow 1: Assign Highest Priority Ticket ---")
        tickets = await session.execute(select(Ticket).where(Ticket.organization_id == ORG_ID, Ticket.priority == 'P0', Ticket.assignee_id.is_(None)))
        t = tickets.scalars().first()
        if not t:
            # Fallback to TCK-1044 if unassigned
            t_res = await session.execute(select(Ticket).where(Ticket.organization_id == ORG_ID, Ticket.ticket_number == 'TCK-1044'))
            t = t_res.scalars().first()

        ticket_id = t.id
        print(f"Proposing assignment for Ticket: {t.ticket_number} (Currently assigned to: {t.assignee_id})")
        
        target_engineer = UUID("10000000-0000-0000-0000-000000000005") # Rahul
        action_res = await ActionService.propose_action(
            session=session,
            organization_id=ORG_ID,
            conversation_id=UUID("00000000-0000-0000-0000-000000000099"),
            tool_name="propose_ticket_assignment",
            action_type="assign_ticket",
            payload={"ticket_id": str(ticket_id), "assignee_id": str(target_engineer), "notes": "Emergency triage"},
        )
        action_id = UUID(action_res["action_id"])
        print(f"Action created with state: {action_res['status']} (Action ID: {action_id})")

        # Confirm HITL Action
        confirm_res = await ActionService.confirm_action(
            session=session,
            organization_id=ORG_ID,
            user_id=USER_ALICE,
            action_id=action_id,
        )
        print(f"Action confirmed: {confirm_res['status']}")

        # Verify mutation in DB
        await session.refresh(t)
        print(f"Verified Database Mutation -> Ticket {t.ticket_number} assignee_id is now: {t.assignee_id}")
        assert t.assignee_id == target_engineer

        # Verify Audit Log
        audit_res = await session.execute(select(AuditLog).where(AuditLog.organization_id == ORG_ID).order_by(AuditLog.created_at.desc()))
        latest_audit = audit_res.scalars().first()
        print(f"Verified Audit Log -> Action: {latest_audit.action}, Target: {latest_audit.target_id}")
        assert latest_audit.action == "assign_ticket"

        # Verify Outbox Message
        outbox_res = await session.execute(select(OutboxEvent).where(OutboxEvent.organization_id == ORG_ID).order_by(OutboxEvent.created_at.desc()))
        latest_outbox = outbox_res.scalars().first()
        print(f"Verified Transactional Outbox -> Event Type: {latest_outbox.event_type}, Status: {latest_outbox.status}, Payload: {latest_outbox.payload}")
        assert latest_outbox.event_type == "ACTION_COMPLETED"
        assert latest_outbox.payload.get("action_type") == "assign_ticket"

    # Demo Flow 2: Move project to at risk
    async with AsyncSessionLocal() as session:
        print("\n--- HITL Flow 2: Move Project to At Risk ---")
        p_res = await session.execute(select(Project).where(Project.organization_id == ORG_ID, Project.key == 'MOBILE'))
        proj = p_res.scalars().first()
        print(f"Project {proj.key} initial health: {proj.health}")

        action_res = await ActionService.propose_action(
            session=session,
            organization_id=ORG_ID,
            conversation_id=UUID("00000000-0000-0000-0000-000000000099"),
            tool_name="propose_project_status_change",
            action_type="change_project_status",
            payload={"project_id": str(proj.id), "status": "active", "health": "at_risk", "reason": "App Store review delay"},
        )
        action_id = UUID(action_res["action_id"])
        confirm_res = await ActionService.confirm_action(
            session=session,
            organization_id=ORG_ID,
            user_id=USER_ALICE,
            action_id=action_id,
        )
        await session.refresh(proj)
        print(f"Verified Database Mutation -> Project {proj.key} health is now: {proj.health}")
        assert proj.health == "at_risk"

    # Demo Flow 3: Approve pending governance gate
    async with AsyncSessionLocal() as session:
        print("\n--- HITL Flow 3: Approve Pending Governance Gate ---")
        a_res = await session.execute(select(Approval).where(Approval.organization_id == ORG_ID, Approval.status == 'pending'))
        appr = a_res.scalars().first()
        print(f"Approval '{appr.title}' initial status: {appr.status}")

        action_res = await ActionService.propose_action(
            session=session,
            organization_id=ORG_ID,
            conversation_id=UUID("00000000-0000-0000-0000-000000000099"),
            tool_name="propose_gate_approval",
            action_type="approve_gate",
            payload={"approval_id": str(appr.id), "decision": "approved", "notes": "Approved by PM in evening review"},
        )
        action_id = UUID(action_res["action_id"])
        confirm_res = await ActionService.confirm_action(
            session=session,
            organization_id=ORG_ID,
            user_id=USER_ALICE,
            action_id=action_id,
        )
        await session.refresh(appr)
        print(f"Verified Database Mutation -> Approval '{appr.title}' status is now: {appr.status}")
        assert appr.status == "approved"

    print("\n====================================================")
    print("ALL 7 QUERIES AND 3 HITL FLOWS VERIFIED 100% SUCCEEDED!")
    print("====================================================")

if __name__ == "__main__":
    asyncio.run(verify_queries_and_hitl())

