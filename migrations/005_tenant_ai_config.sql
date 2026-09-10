-- =============================================================================
-- Migration 005: Tenant AI Configuration (Encrypted Multi-Tenant API Keys)
-- PM Buddy — AI Operations & Governance Platform
-- =============================================================================

CREATE TABLE IF NOT EXISTS tenant_ai_configs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    provider VARCHAR(50) NOT NULL DEFAULT 'google_gemini',
    encrypted_api_key TEXT NOT NULL,
    key_fingerprint VARCHAR(100) NOT NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'connected',
    last_verified_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
    created_by UUID,
    updated_by UUID,
    CONSTRAINT uq_tenant_ai_config UNIQUE (organization_id, provider)
);

CREATE INDEX IF NOT EXISTS idx_tenant_ai_config_org ON tenant_ai_configs(organization_id);

ALTER TABLE tenant_ai_configs ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies 
        WHERE tablename = 'tenant_ai_configs' AND policyname = 'rls_tenant_ai_configs_isolation'
    ) THEN
        CREATE POLICY rls_tenant_ai_configs_isolation ON tenant_ai_configs
            FOR ALL USING (organization_id = current_tenant_id());
    END IF;
END $$;
