import pytest
from uuid import uuid4

from app.core.database import AsyncSessionLocal
from app.models.entities import KnowledgeChunk, KnowledgeDocument, Organization
from app.services.knowledge_service import KnowledgeService, chunk_text


@pytest.mark.asyncio
async def test_text_chunking():
    sample_text = (
        "Paragraph 1: Architecture decision.\n\n"
        "Paragraph 2: The database uses Aurora PostgreSQL with read replicas.\n\n"
        "Paragraph 3: All mutations are captured in transactional outbox."
    )
    chunks = chunk_text(sample_text, max_chunk_chars=100, overlap=20)
    assert len(chunks) >= 2
    assert any("Architecture decision" in c for c in chunks)


@pytest.mark.asyncio
async def test_rag_ingest_and_search():
    async with AsyncSessionLocal() as session:
        org_id = uuid4()
        org = Organization(id=org_id, name="RAG Test Org", slug=f"rag-org-{org_id.hex[:8]}")
        session.add(org)
        await session.commit()

        # Ingest document
        doc = await KnowledgeService.ingest_document(
            session=session,
            organization_id=org_id,
            title="ADR-999: Cloud Infrastructure Resilience",
            content="This document mandates AWS multi-region failover and DynamoDB global tables for billing.",
            document_type="architecture_decision",
            description="High availability billing resilience specification.",
        )
        assert doc.id is not None
        assert doc.status == "ready"

        # Search within tenant
        results = await KnowledgeService.search_knowledge(
            session=session,
            organization_id=org_id,
            query="multi-region failover billing",
            top_k=3,
        )
        assert len(results) >= 1
        top_res = results[0]
        assert "Cloud Infrastructure Resilience" in top_res["document_title"]
        assert "According to: ADR-999" in top_res["citation"]

        # Clean up
        await KnowledgeService.delete_document(session, org_id, doc.id)
        await session.delete(org)
        await session.commit()


@pytest.mark.asyncio
async def test_rag_tenant_isolation():
    async with AsyncSessionLocal() as session:
        org_a = uuid4()
        org_b = uuid4()

        o_a = Organization(id=org_a, name="Org A", slug=f"org-a-{org_a.hex[:8]}")
        o_b = Organization(id=org_b, name="Org B", slug=f"org-b-{org_b.hex[:8]}")
        session.add_all([o_a, o_b])
        await session.commit()

        doc_b = await KnowledgeService.ingest_document(
            session=session,
            organization_id=org_b,
            title="Secret Strategy Org B",
            content="Proprietary confidential algorithms exclusively for Org B.",
            document_type="confidential",
        )

        # Org A searches for Org B's secret content
        results_a = await KnowledgeService.search_knowledge(
            session=session,
            organization_id=org_a,
            query="Proprietary confidential algorithms",
            top_k=5,
        )
        # Must return 0 results because Org A cannot see Org B's documents
        assert len(results_a) == 0

        # Clean up
        await KnowledgeService.delete_document(session, org_b, doc_b.id)
        await session.delete(o_a)
        await session.delete(o_b)
        await session.commit()
