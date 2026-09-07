import hashlib
import io
import logging
import re
from typing import Any, List, Optional
from uuid import UUID, uuid4

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import KnowledgeChunk, KnowledgeDocument, utc_now
from app.services.embedding_service import embedding_service

logger = logging.getLogger(__name__)


def extract_text_from_bytes(file_bytes: bytes, filename: str) -> str:
    """Extracts raw text from PDF, DOCX, TXT, or Markdown bytes."""
    lower = filename.lower()
    if lower.endswith(".pdf"):
        try:
            import pypdf
            reader = pypdf.PdfReader(io.BytesIO(file_bytes))
            pages = [page.extract_text() or "" for page in reader.pages]
            return "\n\n".join(pages)
        except Exception as e:
            logger.warning(f"Failed to parse PDF with pypdf: {e}")
            return file_bytes.decode("utf-8", errors="ignore")

    elif lower.endswith(".docx"):
        try:
            import docx
            doc = docx.Document(io.BytesIO(file_bytes))
            return "\n\n".join([p.text for p in doc.paragraphs if p.text.strip()])
        except Exception as e:
            logger.warning(f"Failed to parse DOCX: {e}")
            return file_bytes.decode("utf-8", errors="ignore")

    else:
        # Markdown, TXT, CSV, or plain text
        return file_bytes.decode("utf-8", errors="ignore")


def chunk_text(text_content: str, max_chunk_chars: int = 800, overlap: int = 100) -> List[str]:
    """Splits cleaned text into overlapping chunks respecting paragraph/sentence boundaries."""
    cleaned = re.sub(r"\r\n", "\n", text_content)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()

    if not cleaned:
        return []

    if len(cleaned) <= max_chunk_chars:
        return [cleaned]

    paragraphs = cleaned.split("\n\n")
    chunks = []
    current_chunk = ""

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue

        if len(current_chunk) + len(para) + 2 <= max_chunk_chars:
            current_chunk = f"{current_chunk}\n\n{para}".strip()
        else:
            if current_chunk:
                chunks.append(current_chunk)
            # If a single paragraph is excessively long, split by sentences or chunks
            if len(para) > max_chunk_chars:
                start = 0
                while start < len(para):
                    end = start + max_chunk_chars
                    sub_chunk = para[start:end].strip()
                    if sub_chunk:
                        chunks.append(sub_chunk)
                    start += (max_chunk_chars - overlap)
                current_chunk = ""
            else:
                current_chunk = para

    if current_chunk:
        chunks.append(current_chunk)

    return chunks


class KnowledgeService:
    @staticmethod
    async def ingest_document(
        session: AsyncSession,
        organization_id: UUID,
        title: str,
        content: str,
        project_id: Optional[UUID] = None,
        document_type: str = "document",
        description: Optional[str] = None,
        source_type: str = "upload",
        source_url: Optional[str] = None,
        created_by: Optional[UUID] = None,
    ) -> KnowledgeDocument:
        """Stores a document, generates text chunks, computes 768-d vector embeddings, and indexes them."""
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()

        doc = KnowledgeDocument(
            id=uuid4(),
            organization_id=organization_id,
            project_id=project_id,
            title=title.strip(),
            description=description.strip() if description else None,
            document_type=document_type,
            source_type=source_type,
            source_url=source_url,
            content=content,
            content_hash=content_hash,
            status="ready",
            created_by=created_by,
            updated_by=created_by,
        )
        session.add(doc)
        await session.flush()

        # Chunk content
        chunks = chunk_text(content)
        if chunks:
            # Batch generate embeddings
            embeddings = await embedding_service.embed_batch(chunks)
            for idx, (chunk_str, emb) in enumerate(zip(chunks, embeddings)):
                chunk_record = KnowledgeChunk(
                    id=uuid4(),
                    organization_id=organization_id,
                    document_id=doc.id,
                    chunk_index=idx,
                    content=chunk_str,
                    embedding=emb,
                    token_count=len(chunk_str.split()),
                    metadata_={
                        "title": title,
                        "document_type": document_type,
                        "project_id": str(project_id) if project_id else None,
                    },
                )
                session.add(chunk_record)

        await session.commit()
        await session.refresh(doc)
        return doc

    @staticmethod
    async def list_documents(
        session: AsyncSession,
        organization_id: UUID,
        project_id: Optional[UUID] = None,
        document_type: Optional[str] = None,
        status: Optional[str] = "ready",
    ) -> List[KnowledgeDocument]:
        """Lists knowledge documents filtered by organization, project, and status."""
        query = select(KnowledgeDocument).where(KnowledgeDocument.organization_id == organization_id)
        if project_id:
            query = query.where(KnowledgeDocument.project_id == project_id)
        if document_type:
            query = query.where(KnowledgeDocument.document_type == document_type)
        if status:
            query = query.where(KnowledgeDocument.status == status)

        query = query.order_by(KnowledgeDocument.created_at.desc())
        result = await session.execute(query)
        return list(result.scalars().all())

    @staticmethod
    async def get_document_by_id(
        session: AsyncSession,
        organization_id: UUID,
        document_id: UUID,
    ) -> Optional[KnowledgeDocument]:
        """Retrieves a single document with tenant verification."""
        stmt = select(KnowledgeDocument).where(
            KnowledgeDocument.id == document_id,
            KnowledgeDocument.organization_id == organization_id,
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def delete_document(
        session: AsyncSession,
        organization_id: UUID,
        document_id: UUID,
    ) -> bool:
        """Deletes a document and its cascaded chunks."""
        doc = await KnowledgeService.get_document_by_id(session, organization_id, document_id)
        if not doc:
            return False

        await session.delete(doc)
        await session.commit()
        return True

    @staticmethod
    async def search_knowledge(
        session: AsyncSession,
        organization_id: UUID,
        query: str,
        project_id: Optional[UUID] = None,
        top_k: int = 5,
        min_similarity: float = 0.3,
    ) -> List[dict]:
        """Performs pgvector cosine similarity search strictly scoped to tenant and project.
        Returns top-K relevant chunks with source citations.
        """
        if not query.strip():
            return []

        query_emb = await embedding_service.embed(query)
        emb_str = f"[{','.join(str(x) for x in query_emb)}]"

        where_clauses = ["c.organization_id = CAST(:org_id AS uuid)", "d.status = 'ready'"]
        params = {
            "query_emb": emb_str,
            "org_id": str(organization_id),
            "top_k": top_k,
        }
        if project_id:
            where_clauses.append("d.project_id = CAST(:project_id AS uuid)")
            params["project_id"] = str(project_id)

        sql = f"""
            SELECT 
                c.id, 
                c.document_id, 
                c.chunk_index, 
                c.content, 
                c.metadata,
                d.title AS document_title, 
                d.document_type, 
                d.project_id,
                1 - (c.embedding <=> CAST(:query_emb AS vector)) AS similarity
            FROM knowledge_chunks c
            JOIN knowledge_documents d ON c.document_id = d.id
            WHERE {" AND ".join(where_clauses)}
            ORDER BY c.embedding <=> CAST(:query_emb AS vector) ASC
            LIMIT :top_k;
        """

        try:
            result = await session.execute(text(sql), params)
            rows = result.fetchall()
        except Exception as e:
            logger.error(f"pgvector query error: {e}. Falling back to keyword search.")
            await session.rollback()
            # Graceful fallback: text ILIKE match
            kw_clauses = ["c.organization_id = CAST(:org_id AS uuid)", "(c.content ILIKE :kw OR d.title ILIKE :kw)"]
            kw_params = {
                "org_id": str(organization_id),
                "kw": f"%{query[:50]}%",
                "top_k": top_k,
            }
            if project_id:
                kw_clauses.append("d.project_id = CAST(:project_id AS uuid)")
                kw_params["project_id"] = str(project_id)

            ilike_sql = f"""
                SELECT 
                    c.id, 
                    c.document_id, 
                    c.chunk_index, 
                    c.content, 
                    c.metadata,
                    d.title AS document_title, 
                    d.document_type, 
                    d.project_id,
                    0.75 AS similarity
                FROM knowledge_chunks c
                JOIN knowledge_documents d ON c.document_id = d.id
                WHERE {" AND ".join(kw_clauses)}
                LIMIT :top_k;
            """
            result = await session.execute(text(ilike_sql), kw_params)
            rows = result.fetchall()

        results = []
        for r in rows:
            sim = float(r[8]) if r[8] is not None else 0.0
            if sim >= min_similarity or len(results) == 0:
                results.append({
                    "chunk_id": str(r[0]),
                    "document_id": str(r[1]),
                    "document_title": r[5],
                    "document_type": r[6],
                    "project_id": str(r[7]) if r[7] else None,
                    "chunk_index": r[2],
                    "content": r[3],
                    "similarity": round(sim, 4),
                    "citation": f"According to: {r[5]} (Section: Part {r[2] + 1})",
                })

        return results
