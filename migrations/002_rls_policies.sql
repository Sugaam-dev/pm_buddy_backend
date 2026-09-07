-- =============================================================================
-- Migration 002: Row Level Security (RLS) Policies
-- Multi-Tenant Defense-in-Depth Isolation
-- =============================================================================

-- Enable Row Level Security on all tenant-owned tables
ALTER TABLE organizations ENABLE ROW LEVEL SECURITY;
ALTER TABLE organization_members ENABLE ROW LEVEL SECURITY;
ALTER TABLE roles ENABLE ROW LEVEL SECURITY;
ALTER TABLE projects ENABLE ROW LEVEL SECURITY;
ALTER TABLE project_members ENABLE ROW LEVEL SECURITY;
ALTER TABLE milestones ENABLE ROW LEVEL SECURITY;
ALTER TABLE tasks ENABLE ROW LEVEL SECURITY;
ALTER TABLE task_dependencies ENABLE ROW LEVEL SECURITY;
ALTER TABLE tickets ENABLE ROW LEVEL SECURITY;
ALTER TABLE ticket_comments ENABLE ROW LEVEL SECURITY;
ALTER TABLE ticket_assignments ENABLE ROW LEVEL SECURITY;
ALTER TABLE approvals ENABLE ROW LEVEL SECURITY;
ALTER TABLE approval_steps ENABLE ROW LEVEL SECURITY;
ALTER TABLE governance_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE risks ENABLE ROW LEVEL SECURITY;
ALTER TABLE risk_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE sla_rules ENABLE ROW LEVEL SECURITY;
ALTER TABLE calendar_connections ENABLE ROW LEVEL SECURITY;
ALTER TABLE calendar_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE ai_conversations ENABLE ROW LEVEL SECURITY;
ALTER TABLE ai_messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE ai_tool_calls ENABLE ROW LEVEL SECURITY;
ALTER TABLE ai_actions ENABLE ROW LEVEL SECURITY;
ALTER TABLE outbox_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE notifications ENABLE ROW LEVEL SECURITY;
ALTER TABLE idempotency_keys ENABLE ROW LEVEL SECURITY;
ALTER TABLE knowledge_documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE knowledge_chunks ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_logs ENABLE ROW LEVEL SECURITY;

-- Helper function to extract session tenant ID
CREATE OR REPLACE FUNCTION current_tenant_id() RETURNS UUID AS $$
BEGIN
    RETURN NULLIF(current_setting('app.current_tenant_id', true), '')::UUID;
END;
$$ LANGUAGE plpgsql STABLE;

-- -----------------------------------------------------------------------------
-- Standard RLS Tenant Isolation Policies
-- Evaluates: organization_id == current_tenant_id()
-- -----------------------------------------------------------------------------

CREATE POLICY rls_org_isolation ON organizations
    FOR ALL USING (id = current_tenant_id());

CREATE POLICY rls_members_isolation ON organization_members
    FOR ALL USING (organization_id = current_tenant_id());

CREATE POLICY rls_roles_isolation ON roles
    FOR ALL USING (organization_id IS NULL OR organization_id = current_tenant_id());

CREATE POLICY rls_projects_isolation ON projects
    FOR ALL USING (organization_id = current_tenant_id());

CREATE POLICY rls_proj_members_isolation ON project_members
    FOR ALL USING (organization_id = current_tenant_id());

CREATE POLICY rls_milestones_isolation ON milestones
    FOR ALL USING (organization_id = current_tenant_id());

CREATE POLICY rls_tasks_isolation ON tasks
    FOR ALL USING (organization_id = current_tenant_id());

CREATE POLICY rls_task_deps_isolation ON task_dependencies
    FOR ALL USING (organization_id = current_tenant_id());

CREATE POLICY rls_tickets_isolation ON tickets
    FOR ALL USING (organization_id = current_tenant_id());

CREATE POLICY rls_ticket_comments_isolation ON ticket_comments
    FOR ALL USING (organization_id = current_tenant_id());

CREATE POLICY rls_ticket_assign_isolation ON ticket_assignments
    FOR ALL USING (organization_id = current_tenant_id());

CREATE POLICY rls_approvals_isolation ON approvals
    FOR ALL USING (organization_id = current_tenant_id());

CREATE POLICY rls_approval_steps_isolation ON approval_steps
    FOR ALL USING (organization_id = current_tenant_id());

CREATE POLICY rls_gov_events_isolation ON governance_events
    FOR ALL USING (organization_id = current_tenant_id());

CREATE POLICY rls_risks_isolation ON risks
    FOR ALL USING (organization_id = current_tenant_id());

CREATE POLICY rls_risk_events_isolation ON risk_events
    FOR ALL USING (organization_id = current_tenant_id());

CREATE POLICY rls_sla_rules_isolation ON sla_rules
    FOR ALL USING (organization_id = current_tenant_id());

CREATE POLICY rls_cal_conn_isolation ON calendar_connections
    FOR ALL USING (organization_id = current_tenant_id());

CREATE POLICY rls_cal_events_isolation ON calendar_events
    FOR ALL USING (organization_id = current_tenant_id());

CREATE POLICY rls_ai_conv_isolation ON ai_conversations
    FOR ALL USING (organization_id = current_tenant_id());

CREATE POLICY rls_ai_msg_isolation ON ai_messages
    FOR ALL USING (organization_id = current_tenant_id());

CREATE POLICY rls_ai_tools_isolation ON ai_tool_calls
    FOR ALL USING (organization_id = current_tenant_id());

CREATE POLICY rls_ai_actions_isolation ON ai_actions
    FOR ALL USING (organization_id = current_tenant_id());

CREATE POLICY rls_outbox_isolation ON outbox_events
    FOR ALL USING (organization_id = current_tenant_id());

CREATE POLICY rls_notifications_isolation ON notifications
    FOR ALL USING (organization_id = current_tenant_id());

CREATE POLICY rls_idempotency_isolation ON idempotency_keys
    FOR ALL USING (organization_id = current_tenant_id());

CREATE POLICY rls_docs_isolation ON knowledge_documents
    FOR ALL USING (organization_id = current_tenant_id());

CREATE POLICY rls_chunks_isolation ON knowledge_chunks
    FOR ALL USING (organization_id = current_tenant_id());

CREATE POLICY rls_audit_isolation ON audit_logs
    FOR ALL USING (organization_id = current_tenant_id());
