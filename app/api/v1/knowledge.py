import base64
from typing import List, Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query, Security, UploadFile, File, Form, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import CurrentTenantUser, get_current_tenant_user, require_permission
from app.services.knowledge_service import KnowledgeService, extract_text_from_bytes

router = APIRouter(prefix="/knowledge", tags=["Knowledge Base / RAG"])


class IngestDocumentRequest(BaseModel):
    title: str = Field(..., description="Document title")
    content: str = Field(..., description="Full text or markdown content")
    project_id: Optional[UUID] = Field(None, description="Optional associated project UUID")
    document_type: str = Field("document", description="Type: architecture_decision, runbook, requirements, etc.")
    description: Optional[str] = Field(None, description="Short summary or abstract")
    source_type: str = Field("manual", description="Source: manual, upload, sync")
    source_url: Optional[str] = Field(None, description="Original URL or reference link")


class KnowledgeSearchRequest(BaseModel):
    query: str = Field(..., description="Semantic search query")
    project_id: Optional[UUID] = Field(None, description="Optional project filter")
    top_k: int = Field(5, ge=1, le=20, description="Max relevant chunks")
    min_similarity: float = Field(0.2, ge=0.0, le=1.0, description="Minimum cosine similarity threshold")


class DocumentResponse(BaseModel):
    id: UUID
    organization_id: UUID
    project_id: Optional[UUID]
    title: str
    description: Optional[str]
    document_type: str
    source_type: str
    source_url: Optional[str]
    status: str
    created_at: str

    class Config:
        from_attributes = True


@router.get("/documents", response_model=List[DocumentResponse])
async def list_documents(
    project_id: Optional[UUID] = Query(None),
    document_type: Optional[str] = Query(None),
    user: CurrentTenantUser = Depends(require_permission("project.read")),
    session: AsyncSession = Depends(get_db),
):
    docs = await KnowledgeService.list_documents(
        session=session,
        organization_id=user.organization_id,
        project_id=project_id,
        document_type=document_type,
    )
    return [
        DocumentResponse(
            id=d.id,
            organization_id=d.organization_id,
            project_id=d.project_id,
            title=d.title,
            description=d.description,
            document_type=d.document_type,
            source_type=d.source_type,
            source_url=d.source_url,
            status=d.status,
            created_at=d.created_at.isoformat(),
        )
        for d in docs
    ]


@router.post("/documents", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED)
async def ingest_document(
    body: IngestDocumentRequest,
    user: CurrentTenantUser = Depends(require_permission("project.write")),
    session: AsyncSession = Depends(get_db),
):
    doc = await KnowledgeService.ingest_document(
        session=session,
        organization_id=user.organization_id,
        title=body.title,
        content=body.content,
        project_id=body.project_id,
        document_type=body.document_type,
        description=body.description,
        source_type=body.source_type,
        source_url=body.source_url,
        created_by=user.user_id,
    )
    return DocumentResponse(
        id=doc.id,
        organization_id=doc.organization_id,
        project_id=doc.project_id,
        title=doc.title,
        description=doc.description,
        document_type=doc.document_type,
        source_type=doc.source_type,
        source_url=doc.source_url,
        status=doc.status,
        created_at=doc.created_at.isoformat(),
    )


@router.post("/upload", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED)
async def upload_document(
    file: UploadFile = File(...),
    title: Optional[str] = Form(None),
    project_id: Optional[UUID] = Form(None),
    document_type: str = Form("document"),
    description: Optional[str] = Form(None),
    user: CurrentTenantUser = Depends(require_permission("project.write")),
    session: AsyncSession = Depends(get_db),
):
    file_bytes = await file.read()
    extracted_text = extract_text_from_bytes(file_bytes, file.filename or "upload.txt")
    if not extracted_text.strip():
        raise HTTPException(status_code=400, detail="Could not extract readable text from uploaded file.")

    doc_title = title or file.filename or "Uploaded Document"
    doc = await KnowledgeService.ingest_document(
        session=session,
        organization_id=user.organization_id,
        title=doc_title,
        content=extracted_text,
        project_id=project_id,
        document_type=document_type,
        description=description or f"Uploaded file: {file.filename}",
        source_type="upload",
        created_by=user.user_id,
    )
    return DocumentResponse(
        id=doc.id,
        organization_id=doc.organization_id,
        project_id=doc.project_id,
        title=doc.title,
        description=doc.description,
        document_type=doc.document_type,
        source_type=doc.source_type,
        source_url=doc.source_url,
        status=doc.status,
        created_at=doc.created_at.isoformat(),
    )


@router.get("/documents/{document_id}")
async def get_document(
    document_id: UUID,
    user: CurrentTenantUser = Depends(require_permission("project.read")),
    session: AsyncSession = Depends(get_db),
):
    doc = await KnowledgeService.get_document_by_id(session, user.organization_id, document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    return {
        "id": str(doc.id),
        "organization_id": str(doc.organization_id),
        "project_id": str(doc.project_id) if doc.project_id else None,
        "title": doc.title,
        "description": doc.description,
        "document_type": doc.document_type,
        "source_type": doc.source_type,
        "content": doc.content,
        "status": doc.status,
        "created_at": doc.created_at.isoformat(),
    }


@router.delete("/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: UUID,
    user: CurrentTenantUser = Depends(require_permission("project.write")),
    session: AsyncSession = Depends(get_db),
):
    success = await KnowledgeService.delete_document(session, user.organization_id, document_id)
    if not success:
        raise HTTPException(status_code=404, detail="Document not found")
    return None


@router.post("/search")
async def search_knowledge(
    body: KnowledgeSearchRequest,
    user: CurrentTenantUser = Depends(require_permission("project.read")),
    session: AsyncSession = Depends(get_db),
):
    chunks = await KnowledgeService.search_knowledge(
        session=session,
        organization_id=user.organization_id,
        query=body.query,
        project_id=body.project_id,
        top_k=body.top_k,
        min_similarity=body.min_similarity,
    )
    return {
        "query": body.query,
        "count": len(chunks),
        "chunks": chunks,
    }
