import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

# Ensure app package is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import delete, select, text
from app.core.database import engine

# -----------------------------------------------------------------------------
# Canonical IDs
# -----------------------------------------------------------------------------
ORG_ACME = UUID("11111111-1111-1111-1111-111111111111")
ORG_GLOBEX = UUID("22222222-2222-2222-2222-222222222222")

ROLE_ADMIN = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
ROLE_PM = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
ROLE_CTO = UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")
ROLE_CEO = UUID("dddddddd-dddd-dddd-dddd-dddddddddddd")
ROLE_TEAM_LEAD = UUID("eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee")
ROLE_ENGINEER = UUID("ffffffff-ffff-ffff-ffff-ffffffffffff")
ROLE_VIEWER = UUID("99999999-9999-9999-9999-999999999999")

USER_ALICE_PM = UUID("10000000-0000-0000-0000-000000000001")
USER_BOB_LEAD = UUID("10000000-0000-0000-0000-000000000002")
USER_CHARLIE_CTO = UUID("10000000-0000-0000-0000-000000000003")
USER_SARAH_ADMIN = UUID("10000000-0000-0000-0000-000000000004")
USER_RAHUL_ENG = UUID("10000000-0000-0000-0000-000000000005")
USER_DAVE_VIEWER = UUID("10000000-0000-0000-0000-000000000009")
USER_GLOBEX_PM = UUID("20000000-0000-0000-0000-000000000001")

PROJ_PORTAL = UUID("a0000001-0000-0000-0000-000000000001")
PROJ_MOBILE = UUID("a0000001-0000-0000-0000-000000000002")
PROJ_PAYMENT = UUID("a0000001-0000-0000-0000-000000000003")
PROJ_GLOBEX_SEC = UUID("b0000001-0000-0000-0000-000000000001")


async def seed_data():
    now = datetime.now(timezone.utc)
    print("Beginning repeatable demo database reset and seed...")

    async with engine.begin() as conn:
        raw_conn = await conn.get_raw_connection()

        # 1. Clean existing demo transactional tables safely
        print("Cleaning demo operational tables in Acme and Globex organizations...")
        await raw_conn.driver_connection.execute("""
            DELETE FROM task_dependencies;
            DELETE FROM tasks WHERE organization_id IN ('11111111-1111-1111-1111-111111111111', '22222222-2222-2222-2222-222222222222');
            DELETE FROM tickets WHERE organization_id IN ('11111111-1111-1111-1111-111111111111', '22222222-2222-2222-2222-222222222222');
            DELETE FROM approvals WHERE organization_id IN ('11111111-1111-1111-1111-111111111111', '22222222-2222-2222-2222-222222222222');
            DELETE FROM risks WHERE organization_id IN ('11111111-1111-1111-1111-111111111111', '22222222-2222-2222-2222-222222222222');
            DELETE FROM calendar_events WHERE organization_id IN ('11111111-1111-1111-1111-111111111111', '22222222-2222-2222-2222-222222222222');
            DELETE FROM calendar_connections WHERE organization_id IN ('11111111-1111-1111-1111-111111111111', '22222222-2222-2222-2222-222222222222');
            DELETE FROM sla_rules WHERE organization_id IN ('11111111-1111-1111-1111-111111111111', '22222222-2222-2222-2222-222222222222');
            DELETE FROM projects WHERE organization_id IN ('11111111-1111-1111-1111-111111111111', '22222222-2222-2222-2222-222222222222');
            DELETE FROM organization_members WHERE organization_id IN ('11111111-1111-1111-1111-111111111111', '22222222-2222-2222-2222-222222222222');
            DELETE FROM organizations WHERE id IN ('11111111-1111-1111-1111-111111111111', '22222222-2222-2222-2222-222222222222');
        """)

        # 2. Organizations
        print("Inserting Organizations...")
        await raw_conn.driver_connection.execute("""
            INSERT INTO organizations (id, name, slug, plan, settings) VALUES
            ('11111111-1111-1111-1111-111111111111', 'Acme Corp', 'acme-corp', 'enterprise', '{"sla_strict_mode": true, "auto_assign_tickets": false}'),
            ('22222222-2222-2222-2222-222222222222', 'Globex Systems', 'globex-sys', 'enterprise', '{"sla_strict_mode": false, "auto_assign_tickets": true}')
            ON CONFLICT (id) DO NOTHING;
        """)

        # 3. Roles & Permissions
        print("Inserting Roles & Permissions...")
        await raw_conn.driver_connection.execute("""
            INSERT INTO roles (id, organization_id, name, description, is_system_role) VALUES
            ('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', NULL, 'ADMIN', 'Tenant Administrator', true),
            ('bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb', NULL, 'PM', 'Project Manager & Delivery Lead', true),
            ('cccccccc-cccc-cccc-cccc-cccccccccccc', NULL, 'CTO', 'Chief Technology Officer', true),
            ('dddddddd-dddd-dddd-dddd-dddddddddddd', NULL, 'CEO', 'Chief Executive Officer', true),
            ('eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee', NULL, 'TEAM_LEAD', 'Technical Team Lead', true),
            ('ffffffff-ffff-ffff-ffff-ffffffffffff', NULL, 'ENGINEER', 'Software / DevOps Engineer', true),
            ('99999999-9999-9999-9999-999999999999', NULL, 'VIEWER', 'Read-Only Stakeholder', true)
            ON CONFLICT (id) DO NOTHING;

            INSERT INTO permissions (id, code, description, module) VALUES
            ('00000000-0000-0000-0000-000000000001', 'project.read', 'View projects and dashboards', 'projects'),
            ('00000000-0000-0000-0000-000000000002', 'project.write', 'Create and modify projects', 'projects'),
            ('00000000-0000-0000-0000-000000000003', 'task.read', 'View tasks and priority breakdown', 'tasks'),
            ('00000000-0000-0000-0000-000000000004', 'task.write', 'Create and update tasks', 'tasks'),
            ('00000000-0000-0000-0000-000000000005', 'ticket.read', 'View tickets and SLA status', 'tickets'),
            ('00000000-0000-0000-0000-000000000006', 'ticket.write', 'Create and modify tickets', 'tickets'),
            ('00000000-0000-0000-0000-000000000007', 'ticket.assign', 'Assign tickets to engineers', 'tickets'),
            ('00000000-0000-0000-0000-000000000008', 'approval.read', 'View approvals and bottleneck analytics', 'approvals'),
            ('00000000-0000-0000-0000-000000000009', 'approval.approve', 'Sign off on governance gates', 'approvals'),
            ('00000000-0000-0000-0000-000000000010', 'risk.read', 'View risk matrix', 'risks'),
            ('00000000-0000-0000-0000-000000000011', 'calendar.read', 'View schedule and availability', 'calendar'),
            ('00000000-0000-0000-0000-000000000012', 'calendar.write', 'Book and modify calendar events', 'calendar'),
            ('00000000-0000-0000-0000-000000000013', 'ai.chat', 'Interact with PM Buddy and AI assistants', 'ai'),
            ('00000000-0000-0000-0000-000000000014', 'action.execute', 'Confirm and execute HITL actions', 'actions')
            ON CONFLICT (code) DO NOTHING;

            INSERT INTO role_permissions (role_id, permission_id)
            SELECT 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb', id FROM permissions ON CONFLICT DO NOTHING;
            INSERT INTO role_permissions (role_id, permission_id)
            SELECT 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', id FROM permissions ON CONFLICT DO NOTHING;
            INSERT INTO role_permissions (role_id, permission_id)
            SELECT 'cccccccc-cccc-cccc-cccc-cccccccccccc', id FROM permissions ON CONFLICT DO NOTHING;
        """)

        # 4. Organization Members
        print("Inserting Organization Members (Admin, PM, Team Lead, Engineer, Viewer)...")
        await raw_conn.driver_connection.execute("""
            INSERT INTO organization_members (id, organization_id, user_id, role_id, status) VALUES
            ('1a000001-0000-0000-0000-000000000001', '11111111-1111-1111-1111-111111111111', '10000000-0000-0000-0000-000000000001', 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb', 'active'),
            ('1a000001-0000-0000-0000-000000000002', '11111111-1111-1111-1111-111111111111', '10000000-0000-0000-0000-000000000002', 'eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee', 'active'),
            ('1a000001-0000-0000-0000-000000000003', '11111111-1111-1111-1111-111111111111', '10000000-0000-0000-0000-000000000003', 'cccccccc-cccc-cccc-cccc-cccccccccccc', 'active'),
            ('1a000001-0000-0000-0000-000000000004', '11111111-1111-1111-1111-111111111111', '10000000-0000-0000-0000-000000000004', 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', 'active'),
            ('1a000001-0000-0000-0000-000000000005', '11111111-1111-1111-1111-111111111111', '10000000-0000-0000-0000-000000000005', 'ffffffff-ffff-ffff-ffff-ffffffffffff', 'active'),
            ('1a000001-0000-0000-0000-000000000009', '11111111-1111-1111-1111-111111111111', '10000000-0000-0000-0000-000000000009', '99999999-9999-9999-9999-999999999999', 'active'),
            ('1a000002-0000-0000-0000-000000000001', '22222222-2222-2222-2222-222222222222', '20000000-0000-0000-0000-000000000001', 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb', 'active')
            ON CONFLICT DO NOTHING;
        """)

        # 5. Projects (At least 3 projects)
        print("Inserting Projects (Customer Portal Revamp, Mobile App Release, Payment Infrastructure)...")
        await raw_conn.driver_connection.execute("""
            INSERT INTO projects (id, organization_id, name, key, description, status, health, owner_id, budget, spent, target_date) VALUES
            ('a0000001-0000-0000-0000-000000000001', '11111111-1111-1111-1111-111111111111', 'Customer Portal Revamp', 'PORTAL', 'Full redesign and modern stack migration of enterprise self-service customer portal.', 'active', 'at_risk', '10000000-0000-0000-0000-000000000001', 450000.00, 380000.00, now() + interval '30 days'),
            ('a0000001-0000-0000-0000-000000000002', '11111111-1111-1111-1111-111111111111', 'Mobile App Release', 'MOBILE', 'Cross-platform iOS and Android release for frictionless customer self-management.', 'active', 'on_track', '10000000-0000-0000-0000-000000000001', 280000.00, 140000.00, now() + interval '60 days'),
            ('a0000001-0000-0000-0000-000000000003', '11111111-1111-1111-1111-111111111111', 'Payment Infrastructure', 'PAY', 'Zero-downtime PCI-DSS compliance upgrade and multi-gateway routing architecture.', 'active', 'critical', '10000000-0000-0000-0000-000000000001', 600000.00, 540000.00, now() + interval '15 days'),
            ('b0000001-0000-0000-0000-000000000001', '22222222-2222-2222-2222-222222222222', 'Globex Secure Gateway', 'SEC', 'Zero Trust Perimeter Deployment', 'active', 'on_track', '20000000-0000-0000-0000-000000000001', 180000.00, 45000.00, now() + interval '90 days')
            ON CONFLICT (id) DO NOTHING;
        """)

        # 6. Tasks (12 tasks with P0, P1, P2, P3, overdue, upcoming, blocked, dependencies)
        print("Inserting Tasks (P0, P1, P2, P3, Overdue, Blocked, Dependencies)...")
        await raw_conn.driver_connection.execute("""
            INSERT INTO tasks (id, organization_id, project_id, title, description, status, priority, priority_score, assignee_id, due_date, is_blocked, blocker_reason) VALUES
            -- P0 Critical Task (Overdue & Blocked)
            ('2a000001-0000-0000-0000-000000000001', '11111111-1111-1111-1111-111111111111', 'a0000001-0000-0000-0000-000000000003', 'Patch Payment Gateway SSL Handshake Vulnerability', 'Emergency fix for TLS renegotiation vulnerability impacting checkout pipeline.', 'in_progress', 'P0', 96, '10000000-0000-0000-0000-000000000005', now() - interval '1 day', true, 'Awaiting security clearance sign-off from compliance team'),
            
            -- P0 Critical Task (Upcoming)
            ('2a000001-0000-0000-0000-000000000002', '11111111-1111-1111-1111-111111111111', 'a0000001-0000-0000-0000-000000000001', 'Deploy Kubernetes Helm Chart Manifests to Staging', 'Deploy microservices into staging cluster and verify healthcheck endpoints.', 'todo', 'P0', 91, '10000000-0000-0000-0000-000000000002', now() + interval '8 hours', false, NULL),
            
            -- P1 High Priority Tasks
            ('2a000001-0000-0000-0000-000000000003', '11111111-1111-1111-1111-111111111111', 'a0000001-0000-0000-0000-000000000001', 'Configure OAuth2 OpenID Connect Integration', 'Setup Okta SSO endpoints for API gateway authorization.', 'todo', 'P1', 79, '10000000-0000-0000-0000-000000000002', now() + interval '2 days', false, NULL),
            ('2a000001-0000-0000-0000-000000000004', '11111111-1111-1111-1111-111111111111', 'a0000001-0000-0000-0000-000000000003', 'Database Sharding Load & Failover Stress Test', 'Run pgbench load tests simulating 10,000 req/sec transactions across read replicas.', 'in_progress', 'P1', 75, '10000000-0000-0000-0000-000000000005', now() - interval '2 days', true, 'Awaiting staging database replica provisioning'),
            ('2a000001-0000-0000-0000-000000000005', '11111111-1111-1111-1111-111111111111', 'a0000001-0000-0000-0000-000000000002', 'Finalize Mobile Biometric Authentication Protocol', 'Integrate FaceID and TouchID credentials storage in secure enclave.', 'in_progress', 'P1', 70, '10000000-0000-0000-0000-000000000002', now() + interval '3 days', false, NULL),
            
            -- P2 Normal Tasks
            ('2a000001-0000-0000-0000-000000000006', '11111111-1111-1111-1111-111111111111', 'a0000001-0000-0000-0000-000000000002', 'Design Mobile Push Notification Service', 'Build APNS and FCM notification relays with deduplication.', 'todo', 'P2', 52, '10000000-0000-0000-0000-000000000002', now() + interval '5 days', false, NULL),
            ('2a000001-0000-0000-0000-000000000007', '11111111-1111-1111-1111-111111111111', 'a0000001-0000-0000-0000-000000000001', 'Responsive Layout QA Across Tablet Form Factors', 'Verify viewport breakpoints and CSS grid alignments on iPad and Android tablets.', 'in_progress', 'P2', 48, '10000000-0000-0000-0000-000000000005', now() + interval '4 days', false, NULL),
            ('2a000001-0000-0000-0000-000000000008', '11111111-1111-1111-1111-111111111111', 'a0000001-0000-0000-0000-000000000003', 'Automate Webhook Notification Retries', 'Add exponential backoff queue for failing partner webhook delivery.', 'todo', 'P2', 45, '10000000-0000-0000-0000-000000000005', now() + interval '7 days', false, NULL),
            
            -- P3 Routine Tasks
            ('2a000001-0000-0000-0000-000000000009', '11111111-1111-1111-1111-111111111111', 'a0000001-0000-0000-0000-000000000001', 'Update Swagger OpenAPI Documentation', 'Generate latest schema contracts and update developer portal spec.', 'todo', 'P3', 25, '10000000-0000-0000-0000-000000000005', now() + interval '10 days', false, NULL),
            ('2a000001-0000-0000-0000-000000000010', '11111111-1111-1111-1111-111111111111', 'a0000001-0000-0000-0000-000000000002', 'Archive Deprecated v1 REST Endpoints', 'Remove dead routing code and clean up legacy telemetry counters.', 'done', 'P3', 20, '10000000-0000-0000-0000-000000000002', now() - interval '5 days', false, NULL),
            ('2a000001-0000-0000-0000-000000000011', '11111111-1111-1111-1111-111111111111', 'a0000001-0000-0000-0000-000000000003', 'Review TLS Certificate Expiration Alerts', 'Audit Cloudflare and AWS ACM automated renewal alerts.', 'done', 'P3', 15, '10000000-0000-0000-0000-000000000005', now() - interval '3 days', false, NULL),
            ('2a000001-0000-0000-0000-000000000012', '11111111-1111-1111-1111-111111111111', 'a0000001-0000-0000-0000-000000000001', 'Optimize Frontend Asset Bundling with Turbopack', 'Analyze webpack bundle split chunks to reduce first load JS by 15KB.', 'todo', 'P2', 40, '10000000-0000-0000-0000-000000000001', now() + interval '6 days', false, NULL)
            ON CONFLICT (id) DO NOTHING;

            -- Task Dependencies
            INSERT INTO task_dependencies (id, organization_id, task_id, depends_on_task_id) VALUES
            ('3a000001-0000-0000-0000-000000000001', '11111111-1111-1111-1111-111111111111', '2a000001-0000-0000-0000-000000000002', '2a000001-0000-0000-0000-000000000001'),
            ('3a000001-0000-0000-0000-000000000002', '11111111-1111-1111-1111-111111111111', '2a000001-0000-0000-0000-000000000004', '2a000001-0000-0000-0000-000000000001')
            ON CONFLICT DO NOTHING;
        """)

        # 7. Tickets & Incidents (10 tickets: critical P0, SLA breach, warning, normal, unassigned, blocked, resolved)
        print("Inserting Tickets (Critical P0, SLA Breach, SLA Warning, Unassigned, Resolved)...")
        await raw_conn.driver_connection.execute("""
            INSERT INTO tickets (id, organization_id, project_id, ticket_number, title, description, category, severity, priority, status, affected_service, customer_name, assignee_id, team_id, sla_due_at, breach_risk_score, probable_cause, suggested_resolution) VALUES
            -- 1. P0 Critical Ticket (SLA Breached)
            ('4a000001-0000-0000-0000-000000000001', '11111111-1111-1111-1111-111111111111', 'a0000001-0000-0000-0000-000000000003', 'TCK-1042', 'Payment Gateway 502 Bad Gateway Spike on Checkout', 'Intermittent HTTP 502 error returned during customer credit card settlement.', 'incident', 'critical', 'P0', 'open', 'payment-gateway', 'Acme E-Commerce', '10000000-0000-0000-0000-000000000005', 'payments-team', now() - interval '2 hours', 95, 'Connection pool exhaustion between gateway service and payment partner API', 'Scale gateway connection pool and enable automated circuit breaker'),
            
            -- 2. P0 Critical Ticket (SLA Warning - 30 mins left)
            ('4a000001-0000-0000-0000-000000000002', '11111111-1111-1111-1111-111111111111', 'a0000001-0000-0000-0000-000000000001', 'TCK-1043', 'Authentication Token Expiration Loop in API Gateway', 'Customer session tokens prematurely invalidated causing repeated logins.', 'incident', 'critical', 'P0', 'in_progress', 'auth-service', 'Enterprise Client Global', '10000000-0000-0000-0000-000000000005', 'platform-core', now() + interval '30 minutes', 88, 'Clock skew between Kong gateway and Supabase JWKS validator', 'Sync NTP on API gateway nodes and increase leeway parameter to 30s'),
            
            -- 3. P1 High Ticket (SLA Warning - 90 mins left, Unassigned)
            ('4a000001-0000-0000-0000-000000000003', '11111111-1111-1111-1111-111111111111', 'a0000001-0000-0000-0000-000000000003', 'TCK-1044', 'Webhook Delivery Timeout for Stripe Settlement Events', 'Stripe webhooks failing with 30s timeouts on ledger database lock contention.', 'bug', 'high', 'P1', 'open', 'ledger-service', 'Fintech Partners Inc', NULL, 'payments-team', now() + interval '90 minutes', 78, 'Row lock contention on balance adjustment table during batch processing', 'Apply SELECT FOR UPDATE SKIP LOCKED on webhook batch handler'),
            
            -- 4. P1 High Ticket (Assigned to Bob)
            ('4a000001-0000-0000-0000-000000000004', '11111111-1111-1111-1111-111111111111', 'a0000001-0000-0000-0000-000000000002', 'TCK-1045', 'Mobile Push Notification Token Registration Memory Leak', 'APNS token registration endpoint leaks memory on unhandled invalid device tokens.', 'bug', 'high', 'P1', 'in_progress', 'notification-relay', 'Mobile Users', '10000000-0000-0000-0000-000000000002', 'mobile-team', now() + interval '6 hours', 60, 'Unclosed TCP connection in Apple APNS HTTP2 client handler', 'Use client context manager pattern and add memory limit alert'),
            
            -- 5. P2 Normal Ticket (Normal SLA, Unassigned)
            ('4a000001-0000-0000-0000-000000000005', '11111111-1111-1111-1111-111111111111', 'a0000001-0000-0000-0000-000000000001', 'TCK-1046', 'Customer Profile Image Upload Aspect Ratio Distortion', 'Uploaded PNG profile pictures stretched horizontally on circular avatar container.', 'bug', 'medium', 'P2', 'open', 'frontend-assets', 'Self-Serve Users', NULL, 'frontend-team', now() + interval '24 hours', 30, 'Missing CSS object-fit: cover on avatar image component', 'Add object-fit: cover and image compression before upload'),
            
            -- 6. P2 Normal Ticket (In Progress)
            ('4a000001-0000-0000-0000-000000000006', '11111111-1111-1111-1111-111111111111', 'a0000001-0000-0000-0000-000000000001', 'TCK-1047', 'Export Project CSV Missing Milestone Tag Column', 'Report generator exports tasks and tickets but drops milestone reference.', 'feature', 'medium', 'P2', 'in_progress', 'reporting-api', 'Internal PMO', '10000000-0000-0000-0000-000000000001', 'core-services', now() + interval '36 hours', 25, 'SQL join in export service omits milestones table', 'Add LEFT JOIN milestones and include column in CSV format'),
            
            -- 7. P2 Blocked Ticket
            ('4a000001-0000-0000-0000-000000000007', '11111111-1111-1111-1111-111111111111', 'a0000001-0000-0000-0000-000000000003', 'TCK-1048', 'Audit Trail Sync Latency in Cold Storage Bucket', 'Archived audit logs delayed by 4 hours during S3 multi-part batch upload.', 'task', 'medium', 'P2', 'open', 'audit-archiver', 'Compliance Officer', '10000000-0000-0000-0000-000000000005', 'security-team', now() + interval '48 hours', 40, 'Rate limit hit on AWS S3 PutObject API', 'Batch audit events into 10MB tar.gz archives before upload'),
            
            -- 8. P3 Routine Ticket (Open)
            ('4a000001-0000-0000-0000-000000000008', '11111111-1111-1111-1111-111111111111', 'a0000001-0000-0000-0000-000000000002', 'TCK-1049', 'Update Copyright Year in Mobile About Screen', 'Copyright notice reads 2025 instead of 2026.', 'task', 'low', 'P3', 'open', 'mobile-app', 'Legal Team', '10000000-0000-0000-0000-000000000002', 'mobile-team', now() + interval '72 hours', 10, 'Hardcoded string in strings.xml', 'Dynamically bind copyright year to current calendar year'),
            
            -- 9. Resolved Ticket
            ('4a000001-0000-0000-0000-000000000009', '11111111-1111-1111-1111-111111111111', 'a0000001-0000-0000-0000-000000000001', 'TCK-1040', 'CORS Origin Mismatch on Staging Auth Subdomain', 'Staging web client blocked by CORS header on auth.staging.acme.com.', 'bug', 'high', 'P1', 'resolved', 'auth-proxy', 'DevOps Team', '10000000-0000-0000-0000-000000000005', 'platform-core', now() - interval '24 hours', 0, 'Missing wildcard subdomain in CORS origin list', 'Added staging subdomain pattern to CORS allowlist'),
            
            -- 10. Resolved Ticket
            ('4a000001-0000-0000-0000-000000000010', '11111111-1111-1111-1111-111111111111', 'a0000001-0000-0000-0000-000000000002', 'TCK-1041', 'App Crash on Android 11 Devices During First Launch', 'NullPointerException when device lacks biometric hardware.', 'bug', 'critical', 'P0', 'resolved', 'mobile-app', 'Android Users', '10000000-0000-0000-0000-000000000002', 'mobile-team', now() - interval '48 hours', 0, 'Unchecked BiometricManager.canAuthenticate() response', 'Added safe fallback to PIN authentication when hardware absent')
            ON CONFLICT (id) DO NOTHING;
        """)

        # 8. Governance Approvals (At least 4: pending, approved, rejected, expiring)
        print("Inserting Approvals (Pending, Approved, Rejected, Expiring)...")
        await raw_conn.driver_connection.execute("""
            INSERT INTO approvals (id, organization_id, project_id, title, description, stage, status, requested_by_id, approver_id, sla_due_at, decision_notes) VALUES
            -- 1. Pending (SLA Breached - 4 days overdue)
            ('5a000001-0000-0000-0000-000000000001', '11111111-1111-1111-1111-111111111111', 'a0000001-0000-0000-0000-000000000003', 'Payment Cloud Infrastructure Budget Overrun Sign-off', 'Authorizes $65,000 additional AWS Aurora Serverless and multi-AZ failover allocation.', 'finance_gate', 'pending', '10000000-0000-0000-0000-000000000001', '10000000-0000-0000-0000-000000000004', now() - interval '4 days', NULL),
            
            -- 2. Pending (Expiring soon - 6 hours left)
            ('5a000001-0000-0000-0000-000000000002', '11111111-1111-1111-1111-111111111111', 'a0000001-0000-0000-0000-000000000001', 'Customer Portal Security & Penetration Testing Sign-off', 'Review third-party penetration test audit findings before public beta launch.', 'security_gate', 'pending', '10000000-0000-0000-0000-000000000001', '10000000-0000-0000-0000-000000000003', now() + interval '6 hours', NULL),
            
            -- 3. Approved
            ('5a000001-0000-0000-0000-000000000003', '11111111-1111-1111-1111-111111111111', 'a0000001-0000-0000-0000-000000000002', 'Mobile App Beta Distribution to TestFlight & Play Internal', 'Approve build v1.2.0-rc3 for 500 internal enterprise beta testers.', 'release_gate', 'approved', '10000000-0000-0000-0000-000000000001', '10000000-0000-0000-0000-000000000003', now() - interval '2 days', 'All crash-free metrics exceed 99.8% threshold. Approved for rollout.'),
            
            -- 4. Rejected
            ('5a000001-0000-0000-0000-000000000004', '11111111-1111-1111-1111-111111111111', 'a0000001-0000-0000-0000-000000000003', 'Bypass PCI-DSS Tokenization Audit for Fast-Track Deployment', 'Request to temporarily bypass PCI-DSS audit to meet Q3 milestone deadline.', 'compliance_gate', 'rejected', '10000000-0000-0000-0000-000000000001', '10000000-0000-0000-0000-000000000004', now() - interval '1 day', 'Non-negotiable compliance requirement. Tokenization verification must complete.')
            ON CONFLICT (id) DO NOTHING;
        """)

        # 9. Risks (At least 5 risks with varied probability/impact)
        print("Inserting Risks (Critical, High, Medium, Low)...")
        await raw_conn.driver_connection.execute("""
            INSERT INTO risks (id, organization_id, project_id, title, description, category, likelihood, impact, status, owner_id, mitigation_plan) VALUES
            -- Critical Risk (5 x 5 = 25)
            ('6a000001-0000-0000-0000-000000000001', '11111111-1111-1111-1111-111111111111', 'a0000001-0000-0000-0000-000000000003', 'Payment Gateway Compliance Revocation Due to Delayed PCI Audit', 'Failure to complete PCI-DSS audit before deadline will result in card network processing suspension.', 'compliance', 5, 5, 'active', '10000000-0000-0000-0000-000000000003', 'Contract external QSA auditor on emergency retainer and freeze non-essential schema changes.'),
            
            -- High Risk (4 x 4 = 16)
            ('6a000001-0000-0000-0000-000000000002', '11111111-1111-1111-1111-111111111111', 'a0000001-0000-0000-0000-000000000003', 'Single Point of Failure on Database Architect Key Personnel', 'Lead Architect Rahul holds sole institutional knowledge of custom sharding and event streaming bus.', 'resource', 4, 4, 'mitigating', '10000000-0000-0000-0000-000000000001', 'Pair programming rotation and comprehensive architecture documentation in runbooks.'),
            
            -- High Risk (3 x 5 = 15)
            ('6a000001-0000-0000-0000-000000000003', '11111111-1111-1111-1111-111111111111', 'a0000001-0000-0000-0000-000000000001', 'Cloud Infrastructure Cost Runaway from Uncapped GPU Clusters', 'Spike in concurrent AI operations calls could exhaust monthly cloud infrastructure budget in 10 days.', 'financial', 3, 5, 'mitigating', '10000000-0000-0000-0000-000000000004', 'Set hard spending limits on AWS billing alarm and implement token bucket rate limiting on LLM gateway.'),
            
            -- Medium Risk (3 x 3 = 9)
            ('6a000001-0000-0000-0000-000000000004', '11111111-1111-1111-1111-111111111111', 'a0000001-0000-0000-0000-000000000002', 'App Store Review Delay for Biometric Enrollment Flow', 'Apple review team frequently flags custom keychain access protocols requiring 7-day review appeals.', 'schedule', 3, 3, 'active', '10000000-0000-0000-0000-000000000002', 'Submit binary for expedited review with detailed video walkthrough demonstrating biometric privacy.'),
            
            -- Low Risk (2 x 2 = 4)
            ('6a000001-0000-0000-0000-000000000005', '11111111-1111-1111-1111-111111111111', 'a0000001-0000-0000-0000-000000000001', 'Third-Party Analytics CDN Latency Fluctuation', 'Mixpanel script loading might delay time-to-interactive on slow 3G connections.', 'technical', 2, 2, 'identified', '10000000-0000-0000-0000-000000000005', 'Load analytics scripts asynchronously with defer attribute and fall back to zero-blocking beacon API.')
            ON CONFLICT (id) DO NOTHING;
        """)

        # 10. SLA Rules
        print("Inserting SLA Rules...")
        await raw_conn.driver_connection.execute("""
            INSERT INTO sla_rules (organization_id, entity_type, severity, warning_threshold_minutes, breach_threshold_minutes) VALUES
            ('11111111-1111-1111-1111-111111111111', 'approval', 'finance_gate', 2880, 4320),
            ('11111111-1111-1111-1111-111111111111', 'approval', 'security_gate', 1440, 2880),
            ('11111111-1111-1111-1111-111111111111', 'ticket', 'critical', 60, 120),
            ('11111111-1111-1111-1111-111111111111', 'ticket', 'high', 240, 480),
            ('11111111-1111-1111-1111-111111111111', 'ticket', 'medium', 1440, 2880)
            ON CONFLICT DO NOTHING;
        """)

        # 11. Calendar Connections & Realistic Local Calendar Events
        print("Inserting Calendar Connections & Events (Conflicting events, Available slots)...")
        await raw_conn.driver_connection.execute("""
            INSERT INTO calendar_connections (id, organization_id, user_id, provider, calendar_email, is_active) VALUES
            ('8a000001-0000-0000-0000-000000000001', '11111111-1111-1111-1111-111111111111', '10000000-0000-0000-0000-000000000001', 'local', 'alice.pm@acme.com', true),
            ('8a000001-0000-0000-0000-000000000005', '11111111-1111-1111-1111-111111111111', '10000000-0000-0000-0000-000000000005', 'local', 'rahul.arch@acme.com', true)
            ON CONFLICT DO NOTHING;

            -- Event 1: Morning Standup (Today 09:00 - 09:30 UTC)
            INSERT INTO calendar_events (id, organization_id, connection_id, external_event_id, title, description, start_time, end_time, attendees, status) VALUES
            ('7a000001-0000-0000-0000-000000000001', '11111111-1111-1111-1111-111111111111', '8a000001-0000-0000-0000-000000000001', 'local_evt_001', 'Daily Core Platform Standup', 'Review active blockers and incident triage', now() - interval '1 hour', now() - interval '30 minutes', '["alice.pm@acme.com", "bob.lead@acme.com", "rahul.arch@acme.com"]', 'confirmed'),
            
            -- Event 2: Conflicting Event (Today 14:00 - 15:00 UTC) - Busy block
            ('7a000001-0000-0000-0000-000000000002', '11111111-1111-1111-1111-111111111111', '8a000001-0000-0000-0000-000000000005', 'local_evt_002', 'Q3 Cloud Cost Reduction Steering Committee', 'Executive review of GPU and database provisioning budget', now() + interval '3 hours', now() + interval '4 hours', '["rahul.arch@acme.com", "sarah.admin@acme.com"]', 'confirmed'),
            
            -- Event 3: Upcoming Tomorrow Strategy Meeting
            ('7a000001-0000-0000-0000-000000000003', '11111111-1111-1111-1111-111111111111', '8a000001-0000-0000-0000-000000000001', 'local_evt_003', 'Payment Infrastructure Incident Post-Mortem', 'Deep-dive review into checkout gateway 502 spike', now() + interval '1 day', now() + interval '1 day 1 hour', '["alice.pm@acme.com", "rahul.arch@acme.com", "charlie.cto@acme.com"]', 'confirmed')
            ON CONFLICT (id) DO NOTHING;
        """)

    print("Successfully seeded all realistic demo operational data into Supabase database!")


if __name__ == "__main__":
    asyncio.run(seed_data())
