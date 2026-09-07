-- =============================================================================
-- Migration 003: Multi-Tenant Enterprise Seed Data
-- Demonstrates PM Buddy, Dashboards, Priority Engine, and SLA Governance
-- =============================================================================

-- -----------------------------------------------------------------------------
-- 1. Organizations
-- -----------------------------------------------------------------------------
INSERT INTO organizations (id, name, slug, plan, settings) VALUES
('11111111-1111-1111-1111-111111111111', 'Acme Corporation', 'acme-corp', 'enterprise', '{"sla_strict_mode": true, "auto_assign_tickets": false}'),
('22222222-2222-2222-2222-222222222222', 'Globex Systems', 'globex-sys', 'enterprise', '{"sla_strict_mode": false, "auto_assign_tickets": true}')
ON CONFLICT (id) DO NOTHING;

-- -----------------------------------------------------------------------------
-- 2. System Roles & Permissions
-- -----------------------------------------------------------------------------
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
('p01', 'project.read', 'View projects and dashboards', 'projects'),
('p02', 'project.write', 'Create and modify projects', 'projects'),
('p03', 'task.read', 'View tasks and priority breakdown', 'tasks'),
('p04', 'task.write', 'Create and update tasks', 'tasks'),
('p05', 'ticket.read', 'View tickets and SLA status', 'tickets'),
('p06', 'ticket.write', 'Create and modify tickets', 'tickets'),
('p07', 'ticket.assign', 'Assign tickets to engineers', 'tickets'),
('p08', 'approval.read', 'View approvals and bottleneck analytics', 'approvals'),
('p09', 'approval.approve', 'Sign off on governance gates', 'approvals'),
('p10', 'risk.read', 'View risk matrix', 'risks'),
('p11', 'calendar.read', 'View schedule and availability', 'calendar'),
('p12', 'calendar.write', 'Book and modify calendar events', 'calendar'),
('p13', 'ai.chat', 'Interact with PM Buddy and AI assistants', 'ai'),
('p14', 'action.execute', 'Confirm and execute HITL actions', 'actions')
ON CONFLICT (code) DO NOTHING;

-- Map permissions to PM and ADMIN roles
INSERT INTO role_permissions (role_id, permission_id)
SELECT 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb', id FROM permissions
ON CONFLICT DO NOTHING;

INSERT INTO role_permissions (role_id, permission_id)
SELECT 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', id FROM permissions
ON CONFLICT DO NOTHING;

-- -----------------------------------------------------------------------------
-- 3. Organization Members (Org A: Acme Corp)
-- -----------------------------------------------------------------------------
-- Predefined User IDs (matching demo accounts)
-- User Alice (PM): 10000000-0000-0000-0000-000000000001
-- User Bob (Lead): 10000000-0000-0000-0000-000000000002
-- User Charlie (CTO): 10000000-0000-0000-0000-000000000003
-- User Sarah (Finance Approver): 10000000-0000-0000-0000-000000000004
-- User Rahul (Architect): 10000000-0000-0000-0000-000000000005

INSERT INTO organization_members (id, organization_id, user_id, role_id, status) VALUES
('m0000001-0000-0000-0000-000000000001', '11111111-1111-1111-1111-111111111111', '10000000-0000-0000-0000-000000000001', 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb', 'active'),
('m0000001-0000-0000-0000-000000000002', '11111111-1111-1111-1111-111111111111', '10000000-0000-0000-0000-000000000002', 'eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee', 'active'),
('m0000001-0000-0000-0000-000000000003', '11111111-1111-1111-1111-111111111111', '10000000-0000-0000-0000-000000000003', 'cccccccc-cccc-cccc-cccc-cccccccccccc', 'active'),
('m0000001-0000-0000-0000-000000000004', '11111111-1111-1111-1111-111111111111', '10000000-0000-0000-0000-000000000004', 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', 'active'),
('m0000001-0000-0000-0000-000000000005', '11111111-1111-1111-1111-111111111111', '10000000-0000-0000-0000-000000000005', 'ffffffff-ffff-ffff-ffff-ffffffffffff', 'active')
ON CONFLICT DO NOTHING;

-- Org B Members (Globex Systems)
INSERT INTO organization_members (id, organization_id, user_id, role_id, status) VALUES
('m0000002-0000-0000-0000-000000000001', '22222222-2222-2222-2222-222222222222', '20000000-0000-0000-0000-000000000001', 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb', 'active')
ON CONFLICT DO NOTHING;

-- -----------------------------------------------------------------------------
-- 4. Projects (Org A: Acme Corp)
-- -----------------------------------------------------------------------------
INSERT INTO projects (id, organization_id, name, key, description, status, health, owner_id, budget, spent, target_date) VALUES
('a0000001-0000-0000-0000-000000000001', '11111111-1111-1111-1111-111111111111', 'Project Alpha', 'ALPHA', 'Next-Gen Cloud Microservices Transformation', 'active', 'at_risk', '10000000-0000-0000-0000-000000000001', 500000.00, 420000.00, now() + interval '30 days'),
('a0000001-0000-0000-0000-000000000002', '11111111-1111-1111-1111-111111111111', 'Project Beta', 'BETA', 'Customer Self-Service Mobile Application', 'active', 'healthy', '10000000-0000-0000-0000-000000000001', 250000.00, 110000.00, now() + interval '60 days'),
('a0000001-0000-0000-0000-000000000003', '11111111-1111-1111-1111-111111111111', 'Project Gamma', 'GAMMA', 'Enterprise Data Lake & Governance Sync', 'active', 'caution', '10000000-0000-0000-0000-000000000001', 350000.00, 210000.00, now() + interval '45 days')
ON CONFLICT (id) DO NOTHING;

-- Org B Project (Globex Systems)
INSERT INTO projects (id, organization_id, name, key, description, status, health, owner_id, budget, spent, target_date) VALUES
('b0000001-0000-0000-0000-000000000001', '22222222-2222-2222-2222-222222222222', 'Globex Secure Gateway', 'SEC', 'Zero Trust Perimeter Deployment', 'active', 'healthy', '20000000-0000-0000-0000-000000000001', 180000.00, 45000.00, now() + interval '90 days')
ON CONFLICT (id) DO NOTHING;

-- -----------------------------------------------------------------------------
-- 5. Tasks (Org A)
-- -----------------------------------------------------------------------------
INSERT INTO tasks (id, organization_id, project_id, title, description, status, priority, priority_score, assignee_id, due_date, is_blocked, blocker_reason) VALUES
('t0000001-0000-0000-0000-000000000001', '11111111-1111-1111-1111-111111111111', 'a0000001-0000-0000-0000-000000000001', 'Implement Kubernetes Helm Chart Manifests', 'Deploy microservices into staging cluster', 'in_progress', 'P0', 92, '10000000-0000-0000-0000-000000000005', now() - interval '2 days', true, 'Blocked on Finance Cloud Budget Gate Approval'),
('t0000001-0000-0000-0000-000000000002', '11111111-1111-1111-1111-111111111111', 'a0000001-0000-0000-0000-000000000001', 'Configure OAuth2 OpenID Connect Integration', 'Setup Okta auth endpoints for API gateway', 'todo', 'P1', 78, '10000000-0000-0000-0000-000000000002', now() + interval '1 day', false, NULL),
('t0000001-0000-0000-0000-000000000003', '11111111-1111-1111-1111-111111111111', 'a0000001-0000-0000-0000-000000000001', 'Database Sharding Load Stress Test', 'Run pgbench load tests simulating 10k req/s', 'todo', 'P1', 74, '10000000-0000-0000-0000-000000000005', now() + interval '3 days', true, 'Awaiting staging database provisioning'),
('t0000001-0000-0000-0000-000000000004', '11111111-1111-1111-1111-111111111111', 'a0000001-0000-0000-0000-000000000002', 'Design Mobile Push Notification Service', 'Build APNS and FCM notification relays', 'in_progress', 'P2', 55, '10000000-0000-0000-0000-000000000002', now() + interval '5 days', false, NULL)
ON CONFLICT (id) DO NOTHING;

-- -----------------------------------------------------------------------------
-- 6. Approvals (Org A: Acme Corp)
-- -----------------------------------------------------------------------------
INSERT INTO approvals (id, organization_id, project_id, title, description, stage, status, requested_by_id, approver_id, sla_due_at, decision_notes) VALUES
('ap000001-0000-0000-0000-000000000001', '11111111-1111-1111-1111-111111111111', 'a0000001-0000-0000-0000-000000000001', 'Cloud Infrastructure Budget Overrun Approval', 'Authorizes $45,000 extra AWS GPU compute cluster allocation', 'finance_gate', 'pending', '10000000-0000-0000-0000-000000000001', '10000000-0000-0000-0000-000000000004', now() - interval '4 days', NULL),
('ap000001-0000-0000-0000-000000000002', '11111111-1111-1111-1111-111111111111', 'a0000001-0000-0000-0000-000000000003', 'Enterprise Architecture Review Sign-off', 'Review multi-region event streaming topology', 'architecture_gate', 'pending', '10000000-0000-0000-0000-000000000001', '10000000-0000-0000-0000-000000000003', now() + interval '12 hours', NULL)
ON CONFLICT (id) DO NOTHING;

-- -----------------------------------------------------------------------------
-- 7. Tickets & Incidents (Org A)
-- -----------------------------------------------------------------------------
INSERT INTO tickets (id, organization_id, project_id, ticket_number, title, description, category, severity, priority, status, affected_service, customer_name, assignee_id, team_id, sla_due_at, breach_risk_score, probable_cause, suggested_resolution) VALUES
('tk000001-0000-0000-0000-000000000001', '11111111-1111-1111-1111-111111111111', 'a0000001-0000-0000-0000-000000000001', 'TCK-1042', 'Authentication Token Expiration Loop in API Gateway', 'Users reported repeated HTTP 401 Unauthorized errors during checkout flow.', 'incident', 'critical', 'P0', 'open', 'auth-service', 'Global Retail Corp', '10000000-0000-0000-0000-000000000005', 'platform-core', now() - interval '1 hour', 95, 'Clock skew between Kong gateway and JWT validator', 'Sync NTP on API gateway nodes and increase JWT leeway to 30s'),
('tk000001-0000-0000-0000-000000000002', '11111111-1111-1111-1111-111111111111', 'a0000001-0000-0000-0000-000000000002', 'TCK-1043', 'Database Connection Pool Exhaustion on Batch Ingestion', 'Nightly sync causes connection timeout spikes in Aurora read-replicas.', 'bug', 'high', 'P1', 'in_progress', 'data-sync-api', 'Internal Services', '10000000-0000-0000-0000-000000000002', 'data-eng', now() + interval '4 hours', 72, 'Async worker missing connection context closure', 'Enforce async context manager pattern in ingestion worker')
ON CONFLICT (id) DO NOTHING;

-- -----------------------------------------------------------------------------
-- 8. Risks Registry (Org A)
-- -----------------------------------------------------------------------------
INSERT INTO risks (id, organization_id, project_id, title, description, category, likelihood, impact, status, owner_id, mitigation_plan) VALUES
('rk000001-0000-0000-0000-000000000001', '11111111-1111-1111-1111-111111111111', 'a0000001-0000-0000-0000-000000000001', 'Cloud Provider Cost Overrun in Q4', 'Unoptimized LLM embedding calls and GPU cluster sizing', 'financial', 4, 5, 'mitigating', '10000000-0000-0000-0000-000000000001', 'Implement semantic caching on Redis and downsize idle nodes'),
('rk000001-0000-0000-0000-000000000002', '11111111-1111-1111-1111-111111111111', 'a0000001-0000-0000-0000-000000000001', 'Key Engineer Resignation / Architecture Single Point of Failure', 'Architect Rahul holds exclusive knowledge of event bus schema', 'resource', 3, 4, 'identified', '10000000-0000-0000-0000-000000000003', 'Document all bus protocols in knowledge base RAG and cross-train team lead')
ON CONFLICT (id) DO NOTHING;

-- -----------------------------------------------------------------------------
-- 9. SLA Rules (Org A)
-- -----------------------------------------------------------------------------
INSERT INTO sla_rules (organization_id, entity_type, severity, warning_threshold_minutes, breach_threshold_minutes) VALUES
('11111111-1111-1111-1111-111111111111', 'approval', 'finance_gate', 2880, 4320), -- 48h warning, 72h breach
('11111111-1111-1111-1111-111111111111', 'approval', 'architecture_gate', 1440, 2880), -- 24h warning, 48h breach
('11111111-1111-1111-1111-111111111111', 'ticket', 'critical', 120, 240), -- 2h warning, 4h breach
('11111111-1111-1111-1111-111111111111', 'ticket', 'high', 240, 480) -- 4h warning, 8h breach
ON CONFLICT DO NOTHING;

-- -----------------------------------------------------------------------------
-- 10. Calendar Connections & Availability (Org A)
-- -----------------------------------------------------------------------------
INSERT INTO calendar_connections (id, organization_id, user_id, provider, calendar_email, is_active) VALUES
('c0000001-0000-0000-0000-000000000001', '11111111-1111-1111-1111-111111111111', '10000000-0000-0000-0000-000000000001', 'local', 'alice.pm@acme.com', true),
('c0000001-0000-0000-0000-000000000005', '11111111-1111-1111-1111-111111111111', '10000000-0000-0000-0000-000000000005', 'local', 'rahul.arch@acme.com', true)
ON CONFLICT DO NOTHING;

INSERT INTO calendar_events (id, organization_id, connection_id, external_event_id, title, description, start_time, end_time, attendees, status) VALUES
('ce000001-0000-0000-0000-000000000001', '11111111-1111-1111-1111-111111111111', 'c0000001-0000-0000-0000-000000000001', 'local_evt_001', 'Daily PMO Standup', 'Project portfolio synchronization', now() + interval '2 hours', now() + interval '2 hours 30 minutes', '["alice.pm@acme.com", "bob.lead@acme.com"]', 'confirmed')
ON CONFLICT (id) DO NOTHING;
