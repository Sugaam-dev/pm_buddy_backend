-- =============================================================================
-- Migration 004: Features Completion (RAG, Dependencies, Notifications)
-- PM Buddy — AI Operations & Governance Platform
-- =============================================================================

CREATE EXTENSION IF NOT EXISTS "vector";

-- -----------------------------------------------------------------------------
-- 1. Knowledge Base (RAG Documents & Chunks)
-- -----------------------------------------------------------------------------
ALTER TABLE knowledge_documents 
    ADD COLUMN IF NOT EXISTS project_id UUID REFERENCES projects(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS description TEXT,
    ADD COLUMN IF NOT EXISTS source_type VARCHAR(64) DEFAULT 'upload',
    ADD COLUMN IF NOT EXISTS storage_path VARCHAR(500),
    ADD COLUMN IF NOT EXISTS content TEXT DEFAULT '',
    ADD COLUMN IF NOT EXISTS status VARCHAR(32) DEFAULT 'ready',
    ADD COLUMN IF NOT EXISTS created_by UUID,
    ADD COLUMN IF NOT EXISTS updated_by UUID;

CREATE INDEX IF NOT EXISTS idx_knowledge_docs_org_proj 
    ON knowledge_documents(organization_id, project_id);
CREATE INDEX IF NOT EXISTS idx_knowledge_docs_status 
    ON knowledge_documents(organization_id, status);

-- Alter embedding vector to 768 dimensions for Gemini text-embedding-004
ALTER TABLE knowledge_chunks 
    ALTER COLUMN embedding TYPE vector(768);

ALTER TABLE knowledge_chunks 
    ADD COLUMN IF NOT EXISTS metadata JSONB DEFAULT '{}';

CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_org 
    ON knowledge_chunks(organization_id);
CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_doc 
    ON knowledge_chunks(document_id);

-- -----------------------------------------------------------------------------
-- 2. Task Dependencies
-- -----------------------------------------------------------------------------
ALTER TABLE task_dependencies
    ADD COLUMN IF NOT EXISTS project_id UUID REFERENCES projects(id) ON DELETE CASCADE,
    ADD COLUMN IF NOT EXISTS created_by UUID;

CREATE INDEX IF NOT EXISTS idx_task_deps_org 
    ON task_dependencies(organization_id);
CREATE INDEX IF NOT EXISTS idx_task_deps_task 
    ON task_dependencies(task_id);
CREATE INDEX IF NOT EXISTS idx_task_deps_depends 
    ON task_dependencies(depends_on_task_id);

-- -----------------------------------------------------------------------------
-- 3. In-App Notifications
-- -----------------------------------------------------------------------------
ALTER TABLE notifications
    ADD COLUMN IF NOT EXISTS severity VARCHAR(32) DEFAULT 'info',
    ADD COLUMN IF NOT EXISTS event_type VARCHAR(64) DEFAULT 'GENERAL',
    ADD COLUMN IF NOT EXISTS source_entity VARCHAR(64),
    ADD COLUMN IF NOT EXISTS source_id UUID,
    ADD COLUMN IF NOT EXISTS action_link VARCHAR(255);

CREATE INDEX IF NOT EXISTS idx_notifications_org_user 
    ON notifications(organization_id, user_id, is_read);
CREATE INDEX IF NOT EXISTS idx_notifications_created 
    ON notifications(organization_id, created_at DESC);
