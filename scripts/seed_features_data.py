import asyncio
import sys
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import delete, select, text
from app.core.database import AsyncSessionLocal
from app.models.entities import KnowledgeChunk, KnowledgeDocument, Notification, Task, TaskDependency
from app.services.dependency_service import DependencyService
from app.services.knowledge_service import KnowledgeService
from app.services.notification_service import NotificationService

ORG_ACME = UUID("11111111-1111-1111-1111-111111111111")
ORG_GLOBEX = UUID("22222222-2222-2222-2222-222222222222")

USER_ALICE_PM = UUID("10000000-0000-0000-0000-000000000001")
USER_CHARLIE_CTO = UUID("10000000-0000-0000-0000-000000000003")
USER_SARAH_ADMIN = UUID("10000000-0000-0000-0000-000000000004")
USER_RAHUL_ENG = UUID("10000000-0000-0000-0000-000000000005")

PROJ_PORTAL = UUID("a0000001-0000-0000-0000-000000000001")
PROJ_MOBILE = UUID("a0000001-0000-0000-0000-000000000002")
PROJ_PAYMENT = UUID("a0000001-0000-0000-0000-000000000003")
PROJ_GLOBEX_SEC = UUID("b0000001-0000-0000-0000-000000000001")

DOC_PAYMENT_ADR = """
# ADR-042: Payment Gateway Microservice & Dual Tokenization Architecture

## Status
Accepted — 2026-06-15

## Context
The Payment Gateway requires high availability (99.99%) and strict PCI-DSS Level 1 compliance. 
A single payment processor introduces unacceptable vendor lock-in and downtime risk.

## Decision
We adopt a dual-routing tokenization gateway:
1. **Primary Processor**: Stripe for North America credit and debit card transactions.
2. **Secondary Processor**: Adyen for European cross-border, SEPA, and alternative payment methods.
3. **Cardholder Data Isolation**: No raw Primary Account Numbers (PAN) ever touch Acme application databases. All credit card inputs are captured via PCI-certified iframes and tokenized immediately into vaulted cryptographic tokens.
4. **Fallback Circuit Breaker**: If Stripe 5xx error rate exceeds 2% over a 60-second window, the payment router automatically shifts traffic to Adyen without customer session disruption.

## Consequences
- Requires dual webhook synchronization workers.
- Aurora PostgreSQL cluster stores only token references (`tok_...`) and transaction metadata.
- Emergency freeze procedures require approval from the Security Gate before deploying schema changes.
"""

DOC_P0_RUNBOOK = """
# Runbook: P0 Incident Escalation & Executive Response Protocol

## Severity Definition
- **P0 / Sev-1**: Complete service outage affecting checkout, authentication, or customer data integrity.
- **SLA Breach Threshold**: 60 minutes response time, 120 minutes resolution target.

## Incident Escalation Workflow
1. **Automated Triage**: When an error budget or SLA alert breaches, PM Buddy automatically flags the ticket as P0 and calculates the breach score.
2. **On-Call Notification**: PagerDuty and internal SMS alert dispatched to primary on-call engineer (Rahul) and delivery lead (Alice).
3. **War Room Activation**: An emergency Google Meet war room is scheduled automatically.
4. **Executive Escalation**: If time-to-mitigation exceeds 45 minutes, incident commander must escalate to Chief Technology Officer (Charlie).
5. **Customer Communications**: Support lead updates status page within 15 minutes of confirmed P0.

## Postmortem Requirements
Every P0 incident requires a blameless postmortem published within 48 hours, reviewed in the weekly Architecture Gate.
"""

DOC_MOBILE_PRD = """
# Product Requirements Document (PRD): Mobile App Biometric Authentication & Offline Sync

## Project Overview
Acme Mobile App v2.0 brings enterprise-grade biometric security and seamless offline-first capability.

## Key Functional Requirements
1. **Biometric Enrollment**: Support FaceID on iOS and BiometricPrompt on Android 10+.
2. **Zero-Knowledge Encryption**: Encryption keys derived from biometric hardware enclave.
3. **Offline Delta Sync**: Mobile clients can view cached projects and queue task status transitions while disconnected.
4. **Conflict Resolution**: Last-write-wins with server timestamp authority. Overdue task modifications are rejected if state conflict occurs.

## Compliance and Dependencies
- Requires Mobile Staging API gateway v2.4.
- Security Gate approval required before TestFlight public beta distribution.
"""

DOC_GLOBEX_SECRET = """
# Globex Internal Security Architecture & Proprietary Trading System

## Confidentiality: Globex Corp Strictly Confidential
This document is proprietary to Globex Systems.
Key architecture components:
- High-frequency order matching engine running on custom FPGA hardware.
- Multi-region replication across Frankfurt and Tokyo.
- Zero-trust access policies strictly enforced for Globex engineers.
"""


async def main():
    print("Seeding Knowledge Base, Task Dependencies, and Notifications...")
    async with AsyncSessionLocal() as session:
        # Clean existing test records for these features
        await session.execute(delete(KnowledgeChunk))
        await session.execute(delete(KnowledgeDocument))
        await session.execute(delete(TaskDependency))
        await session.execute(delete(Notification))
        await session.commit()

        # 1. Ingest Knowledge Documents
        print("Ingesting Knowledge Documents into Supabase pgvector...")
        doc1 = await KnowledgeService.ingest_document(
            session=session,
            organization_id=ORG_ACME,
            project_id=PROJ_PAYMENT,
            title="ADR-042: Payment Gateway Microservice & Dual Tokenization",
            content=DOC_PAYMENT_ADR,
            document_type="architecture_decision",
            description="Dual-routing architecture decision for Stripe and Adyen with PCI-DSS isolation.",
            created_by=USER_CHARLIE_CTO,
        )
        print(f"Created ADR Document: {doc1.title}")

        doc2 = await KnowledgeService.ingest_document(
            session=session,
            organization_id=ORG_ACME,
            project_id=None,
            title="Runbook: P0 Incident Escalation & Executive Response Protocol",
            content=DOC_P0_RUNBOOK,
            document_type="runbook",
            description="Standard operating procedures and escalation pathways for P0 incidents.",
            created_by=USER_ALICE_PM,
        )
        print(f"Created Runbook Document: {doc2.title}")

        doc3 = await KnowledgeService.ingest_document(
            session=session,
            organization_id=ORG_ACME,
            project_id=PROJ_MOBILE,
            title="PRD: Mobile App Biometric Authentication & Offline Sync",
            content=DOC_MOBILE_PRD,
            document_type="requirements",
            description="Product requirements for iOS and Android biometric auth and offline cache.",
            created_by=USER_ALICE_PM,
        )
        print(f"Created PRD Document: {doc3.title}")

        # Ingest Globex isolated document (Organization B)
        doc_globex = await KnowledgeService.ingest_document(
            session=session,
            organization_id=ORG_GLOBEX,
            project_id=PROJ_GLOBEX_SEC,
            title="Globex Internal Security Architecture",
            content=DOC_GLOBEX_SECRET,
            document_type="security_policy",
            description="Globex confidential trading platform security.",
            created_by=None,
        )
        print(f"Created Globex Document: {doc_globex.title}")

        # 2. Add Task Dependencies
        print("Configuring Task Dependencies...")
        tasks_res = await session.execute(
            select(Task).where(Task.organization_id == ORG_ACME).order_by(Task.created_at.asc())
        )
        tasks = tasks_res.scalars().all()
        if len(tasks) >= 3:
            # Task 1 depends on Task 0
            dep1 = await DependencyService.add_dependency(
                session=session,
                organization_id=ORG_ACME,
                project_id=tasks[1].project_id,
                task_id=tasks[1].id,  # successor
                depends_on_task_id=tasks[0].id,  # predecessor
                dependency_type="blocks",
                created_by=USER_ALICE_PM,
            )
            print(f"Added dependency: {tasks[1].title} BLOCKED BY {tasks[0].title}")

            if len(tasks) >= 4:
                dep2 = await DependencyService.add_dependency(
                    session=session,
                    organization_id=ORG_ACME,
                    project_id=tasks[3].project_id,
                    task_id=tasks[3].id,
                    depends_on_task_id=tasks[2].id,
                    dependency_type="depends_on",
                    created_by=USER_ALICE_PM,
                )
                print(f"Added dependency: {tasks[3].title} DEPENDS ON {tasks[2].title}")

        # 3. Create Realistic Notifications
        print("Creating Initial In-App Notifications...")
        await NotificationService.create_notification(
            session=session,
            organization_id=ORG_ACME,
            user_id=USER_ALICE_PM,
            title="Critical SLA Breach on TCK-1044",
            message="Ticket TCK-1044 (Database Connection Pool Exhaustion) has breached its 60-minute SLA response target.",
            severity="critical",
            event_type="SLA_BREACH",
            source_entity="ticket",
            action_link="/tickets?id=4a000001-0000-0000-0000-000000000004",
        )

        await NotificationService.create_notification(
            session=session,
            organization_id=ORG_ACME,
            user_id=USER_ALICE_PM,
            title="Overdue Governance Gate Approval",
            message="Payment Cloud Infrastructure Budget Overrun Sign-off is 4 days overdue for Finance Gate.",
            severity="warning",
            event_type="APPROVAL_PENDING",
            source_entity="approval",
            action_link="/approvals?id=5a000001-0000-0000-0000-000000000001",
        )

        await NotificationService.create_notification(
            session=session,
            organization_id=ORG_ACME,
            user_id=USER_ALICE_PM,
            title="Emergency Incident Sync Scheduled",
            message="Daily Core Platform Standup confirmed for 09:00 AM UTC with Alice, Bob, and Rahul.",
            severity="info",
            event_type="MEETING_SCHEDULED",
            source_entity="calendar_event",
            action_link="/calendar",
        )

        await NotificationService.create_notification(
            session=session,
            organization_id=ORG_ACME,
            user_id=USER_ALICE_PM,
            title="Project Mobile App Moved to At Risk",
            message="Project Mobile App health score dropped to 65 due to 2 overdue beta testing tasks.",
            severity="warning",
            event_type="PROJECT_AT_RISK",
            source_entity="project",
            action_link="/projects?id=a0000001-0000-0000-0000-000000000002",
        )

    print("Seeding of Knowledge Documents, Task Dependencies, and Notifications COMPLETE!")


if __name__ == "__main__":
    asyncio.run(main())
